// MihawkGen integration: two real colour frames -> midpoint -> current frame.
// SPDX-License-Identifier: GPL-3.0-or-later
#include "ps5_framegen.h"
#include "framegen_policy.h"
#include "framegen.h"
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <thread>

extern "C" const unsigned char rpcs3ps5_fg_model_start[], rpcs3ps5_fg_model_end[];
#ifdef RPCS3PS5_CORE
extern "C" void rpcs3ps5_boot_log(const char *format, ...);
#define FG_LOG(...) rpcs3ps5_boot_log(__VA_ARGS__)
#else
#define FG_LOG(...) std::fprintf(stderr, __VA_ARGS__)
#endif

namespace
{
using Clock = std::chrono::steady_clock;
std::mutex mutex;
std::atomic<uint32_t> refresh_millihz{60'000};
struct Image
{
    VkImage image{};
    VkDeviceMemory memory{};
    VkImageView view{};
    VkImageLayout layout{VK_IMAGE_LAYOUT_UNDEFINED};
};
struct Preview
{
    Image image;
    VkBuffer buffer{};
    VkDeviceMemory memory{};
    void *mapped{};
    bool coherent{};
};
struct Presenter
{
    VkDevice device{};
    VkSwapchainKHR swapchain{};
    VkCommandPool pool{};
    VkCommandBuffer cmd{};
    VkFence fence{};
    VkSemaphore acquired{};
    fg_context *network{};
    Image real[2], generated;
    Preview preview;
    ps5_framegen::adaptive_motion_guard motion;
    uint32_t mode{}, adaptive_eligible{}, adaptive_skipped{}, adaptive_frames{};
    uint32_t width{}, height{}, current{};
    bool history{}, failed{}, logged_generation{};
    Clock::time_point arrival{};
    void (*lock_queue)(){};
    void (*unlock_queue)(){};
} state;

VkResult present(VkQueue queue, uint32_t index);

// Only the completed real image is handed to this worker. GPU commands,
// acquisitions and resource reuse stay on the caller; pacing must not stall
// the caller and become part of its next source-frame interval.
class DeferredPresent
{
    std::mutex guard;
    std::condition_variable changed;
    std::thread worker;
    bool pending{}, stopping{};
    VkQueue queue{};
    uint32_t index{};
    Clock::time_point deadline{};
    VkResult result{VK_SUCCESS};

    void run()
    {
        std::unique_lock lock(guard);
        for (;;)
        {
            changed.wait(lock, [&] { return pending || stopping; });
            if (stopping) return;
            changed.wait_until(lock, deadline, [&] { return stopping; });
            if (stopping) return;
            const auto job_queue = queue;
            const auto job_index = index;
            lock.unlock();
            const auto outcome = present(job_queue, job_index);
            lock.lock();
            result = outcome;
            pending = false;
            changed.notify_all();
        }
    }

public:
    ~DeferredPresent()
    {
        drain();
        { std::lock_guard lock(guard); stopping = true; }
        changed.notify_all();
        if (worker.joinable()) worker.join();
    }

    VkResult drain()
    {
        std::unique_lock lock(guard);
        changed.wait(lock, [&] { return !pending; });
        const auto outcome = result;
        result = VK_SUCCESS;
        return outcome;
    }

    void schedule(VkQueue q, uint32_t i, Clock::time_point when)
    {
        std::lock_guard lock(guard);
        // The caller drains before any resource/swapchain reuse.
        if (!worker.joinable()) worker = std::thread([this] { run(); });
        queue = q; index = i; deadline = when; pending = true;
        changed.notify_all();
    }
} deferred;

// Share RPCS3's submit guard with its offload worker. Never hold it during
// a CPU sleep or fence wait, which could block another required submission.
struct QueueGuard
{
    QueueGuard() { if (state.lock_queue) state.lock_queue(); }
    ~QueueGuard() { if (state.unlock_queue) state.unlock_queue(); }
};

void destroy()
{
    deferred.drain();
    auto &s = state;
    if (!s.device) return;
    // Also covers an interrupted/error submit and the last WSI presentation.
    { QueueGuard guard; vkDeviceWaitIdle(s.device); }
    fg_context_destroy(s.network);
    for (auto *i : {&s.real[0], &s.real[1], &s.generated, &s.preview.image})
    {
        if (i->view) vkDestroyImageView(s.device, i->view, nullptr);
        if (i->image) vkDestroyImage(s.device, i->image, nullptr);
        if (i->memory) vkFreeMemory(s.device, i->memory, nullptr);
    }
    if (s.preview.mapped) vkUnmapMemory(s.device, s.preview.memory);
    if (s.preview.buffer) vkDestroyBuffer(s.device, s.preview.buffer, nullptr);
    if (s.preview.memory) vkFreeMemory(s.device, s.preview.memory, nullptr);
    if (s.acquired) vkDestroySemaphore(s.device, s.acquired, nullptr);
    if (s.fence) vkDestroyFence(s.device, s.fence, nullptr);
    if (s.pool) vkDestroyCommandPool(s.device, s.pool, nullptr);
    state = {};
}

VkResult make_image(VkPhysicalDevice gpu, Image &out, uint32_t width = 0, uint32_t height = 0)
{
    const auto &s = state;
    VkImageCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO;
    info.imageType = VK_IMAGE_TYPE_2D;
    info.format = VK_FORMAT_R8G8B8A8_UNORM;
    info.extent = {width ? width : s.width, height ? height : s.height, 1};
    info.mipLevels = info.arrayLayers = 1;
    info.samples = VK_SAMPLE_COUNT_1_BIT;
    info.tiling = VK_IMAGE_TILING_OPTIMAL;
    info.usage = VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT |
        VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_STORAGE_BIT;
    VkResult r = vkCreateImage(s.device, &info, nullptr, &out.image);
    if (r != VK_SUCCESS) return r;
    VkMemoryRequirements requirements{};
    vkGetImageMemoryRequirements(s.device, out.image, &requirements);
    VkPhysicalDeviceMemoryProperties memory{};
    vkGetPhysicalDeviceMemoryProperties(gpu, &memory);
    uint32_t type = memory.memoryTypeCount;
    for (uint32_t i = 0; i < memory.memoryTypeCount; ++i)
        if ((requirements.memoryTypeBits & (1u << i)) &&
            (memory.memoryTypes[i].propertyFlags & VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT))
        { type = i; break; }
    if (type == memory.memoryTypeCount) return VK_ERROR_FEATURE_NOT_PRESENT;
    VkMemoryAllocateInfo alloc{};
    alloc.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    alloc.allocationSize = requirements.size;
    alloc.memoryTypeIndex = type;
    if ((r = vkAllocateMemory(s.device, &alloc, nullptr, &out.memory)) != VK_SUCCESS) return r;
    if ((r = vkBindImageMemory(s.device, out.image, out.memory, 0)) != VK_SUCCESS) return r;
    VkImageViewCreateInfo view{};
    view.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO;
    view.image = out.image;
    view.viewType = VK_IMAGE_VIEW_TYPE_2D;
    view.format = info.format;
    view.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
    return vkCreateImageView(s.device, &view, nullptr, &out.view);
}

VkResult make_preview(VkPhysicalDevice gpu)
{
    auto &s = state;
    auto &p = s.preview;
    VkResult r = make_image(gpu, p.image, ps5_framegen::probe_width, ps5_framegen::probe_height);
    if (r != VK_SUCCESS) return r;
    VkBufferCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    info.size = ps5_framegen::probe_bytes;
    info.usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT;
    info.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    if ((r = vkCreateBuffer(s.device, &info, nullptr, &p.buffer)) != VK_SUCCESS) return r;
    VkMemoryRequirements requirements{};
    vkGetBufferMemoryRequirements(s.device, p.buffer, &requirements);
    VkPhysicalDeviceMemoryProperties memory{};
    vkGetPhysicalDeviceMemoryProperties(gpu, &memory);
    uint32_t type = memory.memoryTypeCount;
    unsigned best = 0;
    for (uint32_t i = 0; i < memory.memoryTypeCount; ++i)
    {
        const auto flags = memory.memoryTypes[i].propertyFlags;
        if (!(requirements.memoryTypeBits & (1u << i)) || !(flags & VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT)) continue;
        const unsigned score = 1 + ((flags & VK_MEMORY_PROPERTY_HOST_COHERENT_BIT) ? 2 : 0) +
            ((flags & VK_MEMORY_PROPERTY_HOST_CACHED_BIT) ? 1 : 0);
        if (score > best) { best = score; type = i; }
    }
    if (type == memory.memoryTypeCount) return VK_ERROR_FEATURE_NOT_PRESENT;
    p.coherent = memory.memoryTypes[type].propertyFlags & VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
    VkMemoryAllocateInfo alloc{};
    alloc.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    alloc.allocationSize = requirements.size;
    alloc.memoryTypeIndex = type;
    if ((r = vkAllocateMemory(s.device, &alloc, nullptr, &p.memory)) != VK_SUCCESS) return r;
    if ((r = vkBindBufferMemory(s.device, p.buffer, p.memory, 0)) != VK_SUCCESS) return r;
    return vkMapMemory(s.device, p.memory, 0, VK_WHOLE_SIZE, 0, &p.mapped);
}

bool init(VkDevice device, VkPhysicalDevice gpu, uint32_t family,
    VkSwapchainKHR swapchain, uint32_t width, uint32_t height, VkFormat format, uint32_t mode,
    void (*lock_queue)(), void (*unlock_queue)())
{
    auto &s = state;
    if (s.device == device && s.swapchain == swapchain && s.width == width && s.height == height && s.mode == mode)
        return !s.failed;
    destroy();
    s.device = device; s.swapchain = swapchain; s.width = width; s.height = height;
    s.mode = mode;
    s.lock_queue = lock_queue; s.unlock_queue = unlock_queue;
    // Shader output is RGBA8. Blits convert the swapchain's RGBA/BGRA order.
    VkFormatProperties source{}, rgba{};
    vkGetPhysicalDeviceFormatProperties(gpu, format, &source);
    vkGetPhysicalDeviceFormatProperties(gpu, VK_FORMAT_R8G8B8A8_UNORM, &rgba);
    const auto blit = VK_FORMAT_FEATURE_BLIT_SRC_BIT | VK_FORMAT_FEATURE_BLIT_DST_BIT;
    const auto needed = blit | VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT | VK_FORMAT_FEATURE_STORAGE_IMAGE_BIT |
        VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT;
    VkResult r = VK_ERROR_FORMAT_NOT_SUPPORTED;
    char error[256] = "unsupported colour format/features";
    if ((format == VK_FORMAT_B8G8R8A8_UNORM || format == VK_FORMAT_R8G8B8A8_UNORM) &&
        (source.optimalTilingFeatures & blit) == blit && (rgba.optimalTilingFeatures & needed) == needed)
    {
        const fg_create_info info{device, gpu, width, height, 1, VK_FORMAT_R8G8B8A8_UNORM, 0, 0};
        r = fg_context_create(&info, &s.network, error, sizeof(error));
        if (r == VK_SUCCESS)
            r = fg_context_load_network(s.network, rpcs3ps5_fg_model_start,
                size_t(rpcs3ps5_fg_model_end - rpcs3ps5_fg_model_start), error, sizeof(error));
        for (auto *i : {&s.real[0], &s.real[1], &s.generated})
            if (r == VK_SUCCESS) r = make_image(gpu, *i);
        if (r == VK_SUCCESS && mode == 2) r = make_preview(gpu);
        VkCommandPoolCreateInfo pool{};
        pool.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
        pool.queueFamilyIndex = family;
        pool.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
        if (r == VK_SUCCESS) r = vkCreateCommandPool(device, &pool, nullptr, &s.pool);
        VkCommandBufferAllocateInfo cmd{};
        cmd.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
        cmd.commandPool = s.pool; cmd.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY; cmd.commandBufferCount = 1;
        if (r == VK_SUCCESS) r = vkAllocateCommandBuffers(device, &cmd, &s.cmd);
        VkFenceCreateInfo fence{}; fence.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
        if (r == VK_SUCCESS) r = vkCreateFence(device, &fence, nullptr, &s.fence);
        VkSemaphoreCreateInfo sem{}; sem.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO;
        if (r == VK_SUCCESS) r = vkCreateSemaphore(device, &sem, nullptr, &s.acquired);
    }
    if (r != VK_SUCCESS)
    {
        FG_LOG("PS5 FrameGen: unavailable (%d, %s); normal presentation\n", int(r), error);
        destroy();
        // Remember failure until swapchain recreation, avoiding allocation retries each frame.
        s.device = device; s.swapchain = swapchain; s.width = width; s.height = height; s.mode = mode; s.failed = true;
        s.lock_queue = lock_queue; s.unlock_queue = unlock_queue;
        return false;
    }
    s.arrival = Clock::now();
    FG_LOG("PS5 FrameGen: MihawkGen ready %ux%u, %s mode, display %u mHz\n",
        width, height, mode == 2 ? "Adaptive" : "On", refresh_millihz.load());
    return true;
}

void barrier(VkImage image, VkImageLayout before, VkImageLayout after)
{
    VkImageMemoryBarrier b{}; b.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
    b.srcAccessMask = before == VK_IMAGE_LAYOUT_UNDEFINED ? 0 : VK_ACCESS_MEMORY_READ_BIT | VK_ACCESS_MEMORY_WRITE_BIT;
    b.dstAccessMask = VK_ACCESS_MEMORY_READ_BIT | VK_ACCESS_MEMORY_WRITE_BIT;
    b.oldLayout = before; b.newLayout = after;
    b.srcQueueFamilyIndex = b.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    b.image = image; b.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
    vkCmdPipelineBarrier(state.cmd, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,
        0, 0, nullptr, 0, nullptr, 1, &b);
}
void layout(Image &i, VkImageLayout next)
{
    barrier(i.image, i.layout, next); i.layout = next;
}
void blit(VkImage src, VkImage dst)
{
    VkImageBlit region{};
    region.srcSubresource = region.dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1};
    region.srcOffsets[1] = region.dstOffsets[1] = {int32_t(state.width), int32_t(state.height), 1};
    vkCmdBlitImage(state.cmd, src, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, dst,
        VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &region, VK_FILTER_NEAREST);
}
void record_preview(Image &source)
{
    auto &s = state;
    layout(source, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
    layout(s.preview.image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
    VkImageBlit region{};
    region.srcSubresource = region.dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1};
    region.srcOffsets[1] = {int32_t(s.width), int32_t(s.height), 1};
    region.dstOffsets[1] = {int32_t(ps5_framegen::probe_width), int32_t(ps5_framegen::probe_height), 1};
    vkCmdBlitImage(s.cmd, source.image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, s.preview.image.image,
        VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &region, VK_FILTER_LINEAR);
    layout(source, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);
    layout(s.preview.image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
    VkBufferImageCopy copy{};
    copy.imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1};
    copy.imageExtent = {ps5_framegen::probe_width, ps5_framegen::probe_height, 1};
    vkCmdCopyImageToBuffer(s.cmd, s.preview.image.image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
        s.preview.buffer, 1, &copy);
    VkBufferMemoryBarrier host{};
    host.sType = VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER;
    host.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
    host.dstAccessMask = VK_ACCESS_HOST_READ_BIT;
    host.srcQueueFamilyIndex = host.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    host.buffer = s.preview.buffer;
    host.size = VK_WHOLE_SIZE;
    vkCmdPipelineBarrier(s.cmd, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_HOST_BIT,
        0, 0, nullptr, 1, &host, 0, nullptr);
}
VkResult begin()
{
    auto &s = state;
    VkResult r = vkResetCommandPool(s.device, s.pool, 0);
    if (r != VK_SUCCESS) return r;
    VkCommandBufferBeginInfo b{}; b.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    b.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    return vkBeginCommandBuffer(s.cmd, &b);
}
VkResult submit(VkQueue queue, VkSemaphore wait)
{
    auto &s = state;
    VkResult r = vkEndCommandBuffer(s.cmd);
    if (r != VK_SUCCESS) return r;
    if ((r = vkResetFences(s.device, 1, &s.fence)) != VK_SUCCESS) return r;
    const VkPipelineStageFlags stage = VK_PIPELINE_STAGE_ALL_COMMANDS_BIT;
    VkSubmitInfo info{}; info.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    info.commandBufferCount = 1; info.pCommandBuffers = &s.cmd;
    if (wait) { info.waitSemaphoreCount = 1; info.pWaitSemaphores = &wait; info.pWaitDstStageMask = &stage; }
    { QueueGuard guard; r = vkQueueSubmit(queue, 1, &info, s.fence); }
    if (r != VK_SUCCESS) return r;
    // Deliberately synchronous first integration: the one network descriptor slot,
    // histories, command buffer and acquire semaphore are never reused in flight.
    // WSI needs no wait semaphore after this completed GPU fence.
    return vkWaitForFences(s.device, 1, &s.fence, VK_TRUE, UINT64_MAX);
}
VkResult present(VkQueue queue, uint32_t index)
{
    VkPresentInfoKHR p{}; p.sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR;
    p.swapchainCount = 1; p.pSwapchains = &state.swapchain; p.pImageIndices = &index;
    QueueGuard guard;
    return vkQueuePresentKHR(queue, &p);
}
}

extern "C" void rpcs3ps5_framegen_set_refresh(uint32_t value)
{
    refresh_millihz.store(value ? value : 60'000);
}
extern "C" void rpcs3ps5_framegen_reset(VkDevice device)
{
    std::lock_guard lock(mutex);
    if (state.device == device) destroy();
}
extern "C" bool rpcs3ps5_framegen_present(VkDevice device, VkPhysicalDevice gpu, VkQueue queue,
    uint32_t family, VkSwapchainKHR swapchain, uint32_t width, uint32_t height,
    VkFormat format, const VkImage *images, uint32_t count, uint32_t index,
    VkSemaphore rendered, VkResult *result, uint32_t mode, void (*lock_queue)(), void (*unlock_queue)())
{
    if (!device || !gpu || !queue || !swapchain || !images || !result || index >= count ||
        !width || !height) return false;
    std::lock_guard lock(mutex);
    if (mode == 0 || mode > 2)
    {
        if (state.device == device) destroy();
        return false;
    }
    const bool same_swapchain = state.device == device && state.swapchain == swapchain;
    const auto deferred_result = deferred.drain();
    if (!init(device, gpu, family, swapchain, width, height, format, mode, lock_queue, unlock_queue)) return false;
    auto &s = state;
    const auto now = Clock::now();
    const auto interval = std::chrono::duration_cast<std::chrono::nanoseconds>(now - s.arrival).count();
    s.arrival = now;
    bool generate = ps5_framegen::should_generate(s.history, interval, refresh_millihz.load());
    auto &next = s.real[s.current];
    auto &previous = s.real[s.current ^ 1];
    auto fail = [&](VkResult r) { *result = r; s.failed = true;
        FG_LOG("PS5 FrameGen: presentation failed %d; requesting swapchain recovery\n", int(r)); return true; };
    VkResult r = begin();
    if (r != VK_SUCCESS) return fail(r);
    if (same_swapchain && deferred_result != VK_SUCCESS && deferred_result != VK_SUBOPTIMAL_KHR)
    {
        // Honour ownership even on an error reported by the previous job:
        // consume this call's render semaphore before requesting recovery.
        r = submit(queue, rendered);
        return fail(r == VK_SUCCESS ? deferred_result : r);
    }
    barrier(images[index], VK_IMAGE_LAYOUT_PRESENT_SRC_KHR, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
    layout(next, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
    blit(images[index], next.image);
    layout(next, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);
    VkSemaphore wait = rendered;
    if (mode == 2)
    {
        record_preview(next);
        barrier(images[index], VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, VK_IMAGE_LAYOUT_PRESENT_SRC_KHR);
        // Only the small policy-sized RGBA preview is read after its GPU fence. Never download a full
        // frame or wait for motion analysis on the asynchronous pacing worker.
        if ((r = submit(queue, wait)) != VK_SUCCESS) return fail(r);
        wait = VK_NULL_HANDLE;
        if (!s.preview.coherent)
        {
            VkMappedMemoryRange range{};
            range.sType = VK_STRUCTURE_TYPE_MAPPED_MEMORY_RANGE;
            range.memory = s.preview.memory; range.size = VK_WHOLE_SIZE;
            if ((r = vkInvalidateMappedMemoryRanges(device, 1, &range)) != VK_SUCCESS) return fail(r);
        }
        const bool reliable = s.motion.accept({static_cast<const uint8_t *>(s.preview.mapped), ps5_framegen::probe_bytes});
        if (generate) { ++s.adaptive_eligible; if (!reliable) ++s.adaptive_skipped; }
        generate &= reliable;
        if (++s.adaptive_frames == 120)
        {
            FG_LOG("PS5 FrameGen Adaptive: %u eligible, %u skipped for image change/recovery\n",
                s.adaptive_eligible, s.adaptive_skipped);
            s.adaptive_frames = s.adaptive_eligible = s.adaptive_skipped = 0;
        }
        if (generate && (r = begin()) != VK_SUCCESS) return fail(r);
    }
    if (generate)
    {
        layout(s.generated, VK_IMAGE_LAYOUT_GENERAL);
        fg_frame_pair pair{}; pair.prev_color = previous.view; pair.next_color = next.view; pair.t = 0.5f;
        fg_record_generate(s.network, s.cmd, 0, FG_METHOD_NEURAL, &pair, s.generated.view);
        layout(s.generated, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
        barrier(images[index], mode == 2 ? VK_IMAGE_LAYOUT_PRESENT_SRC_KHR : VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
            VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
        blit(s.generated.image, images[index]);
        barrier(images[index], VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_PRESENT_SRC_KHR);
    }
    else if (mode != 2) barrier(images[index], VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, VK_IMAGE_LAYOUT_PRESENT_SRC_KHR);
    if ((mode != 2 || generate) && (r = submit(queue, wait)) != VK_SUCCESS) return fail(r);
    r = present(queue, index);
    if (r != VK_SUCCESS && r != VK_SUBOPTIMAL_KHR) return fail(r);
    bool suboptimal = r == VK_SUBOPTIMAL_KHR ||
        (same_swapchain && deferred_result == VK_SUBOPTIMAL_KHR);
    if (generate)
    {
        // First show the midpoint, then acquire a distinct WSI image for the
        // real current frame. Neither is counted as an additional guest flip.
        const auto deadline = Clock::now() + std::chrono::nanoseconds(interval / 2);
        uint32_t real_index = 0;
        r = vkAcquireNextImageKHR(device, swapchain, 100'000'000, s.acquired, VK_NULL_HANDLE, &real_index);
        if (r != VK_SUCCESS && r != VK_SUBOPTIMAL_KHR) return fail(r);
        suboptimal |= r == VK_SUBOPTIMAL_KHR;
        if (real_index >= count) return fail(VK_ERROR_INITIALIZATION_FAILED);
        if ((r = begin()) != VK_SUCCESS) return fail(r);
        layout(next, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
        barrier(images[real_index], VK_IMAGE_LAYOUT_PRESENT_SRC_KHR, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
        blit(next.image, images[real_index]);
        layout(next, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);
        barrier(images[real_index], VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_PRESENT_SRC_KHR);
        if ((r = submit(queue, s.acquired)) != VK_SUCCESS) return fail(r);
        // The image and acquire semaphore are GPU-complete. Present it later
        // while RPCS3 renders the next source frame. Drain before reuse/reset.
        deferred.schedule(queue, real_index, deadline);
        if (!s.logged_generation)
        {
            FG_LOG("PS5 FrameGen: first neural midpoint presented; real frame queued on pacing worker\n");
            s.logged_generation = true;
        }
    }
    s.history = true; s.current ^= 1;
    *result = suboptimal ? VK_SUBOPTIMAL_KHR : VK_SUCCESS;
    return true;
}
