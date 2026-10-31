// Lifecycle/WSI contract tests with mocked Vulkan and neural dispatch.
// Real shader/weight correctness is checked separately with upstream tests.
// SPDX-License-Identifier: MIT
#include "ps5_framegen.h"
#include "framegen.h"
#include "framegen_policy.h"
#include <algorithm>
#include <array>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <map>
#include <mutex>
#include <thread>
#include <vector>

namespace
{
uintptr_t id = 100;
template<class T> T fresh() { return reinterpret_cast<T>(++id); }
template<class T> T h(uintptr_t n) { return reinterpret_cast<T>(n); }
std::map<VkSemaphore, bool> semaphores;
std::map<VkFence, bool> fences;
std::map<VkImage, VkImageLayout> layouts;
std::map<VkDeviceMemory, std::vector<uint8_t>> allocations;
std::map<VkBuffer, VkDeviceMemory> buffers;
std::array<uint8_t, ps5_framegen::probe_bytes> preview_pixels{};
bool host_visible = true, host_coherent = true, fail_map{}, readback_pending{};
int invalidations{};
int images_alive{}, networks_alive{}, generated{}, submissions{}, creates{}, acquires{};
bool fail_image{};
bool queue_locked{};
void lock_queue() { assert(!queue_locked); queue_locked = true; }
void unlock_queue() { assert(queue_locked); queue_locked = false; }
VkResult acquire_result = VK_SUCCESS, submit_result = VK_SUCCESS, present_result = VK_SUCCESS;
std::vector<uint32_t> presented;
std::mutex present_mutex;
std::condition_variable present_changed;
bool hold_real{}, real_entered{};
VkResult real_present_result = VK_SUCCESS;
thread_local bool inside_frame{};
std::vector<uint32_t> shown()
{
    std::lock_guard lock(present_mutex);
    return presented;
}
void await_present(size_t count)
{
    std::unique_lock lock(present_mutex);
    assert(present_changed.wait_for(lock, std::chrono::seconds(2), [&] { return presented.size() >= count; }));
}
const VkDevice device = h<VkDevice>(1);
const VkPhysicalDevice gpu = h<VkPhysicalDevice>(2);
const VkQueue queue = h<VkQueue>(3);
const VkSwapchainKHR swapchain = h<VkSwapchainKHR>(4);
const VkSemaphore rendered = h<VkSemaphore>(5);
const VkImage images[] = {h<VkImage>(6), h<VkImage>(7), h<VkImage>(8)};
void reset_swap_images()
{
    for (auto image : images) layouts[image] = VK_IMAGE_LAYOUT_PRESENT_SRC_KHR;
}
bool frame(VkResult &r, uint32_t width = 64, VkFormat format = VK_FORMAT_B8G8R8A8_UNORM, uint32_t mode = 1)
{
    semaphores[rendered] = true;
    inside_frame = true;
    const auto handled = rpcs3ps5_framegen_present(device, gpu, queue, 0, swapchain, width, 64,
        format, images, 3, 0, rendered, &r, mode, lock_queue, unlock_queue);
    inside_frame = false;
    return handled;
}
}

struct fg_context {};
VkResult fg_context_create(const fg_create_info *info, fg_context **out, char *, size_t)
{
    assert(info->slots == 1 && info->output_format == VK_FORMAT_R8G8B8A8_UNORM);
    *out = new fg_context; ++networks_alive; return VK_SUCCESS;
}
void fg_context_destroy(fg_context *ctx) { if (ctx) { delete ctx; --networks_alive; } }
VkResult fg_context_load_network(fg_context *, const void *, size_t size, char *, size_t)
{ assert(size > 1'000'000); return VK_SUCCESS; }
void fg_record_generate(fg_context *, VkCommandBuffer, uint32_t slot, fg_method method,
    const fg_frame_pair *pair, VkImageView output)
{
    assert(slot == 0 && method == FG_METHOD_NEURAL && pair->t == 0.5f);
    assert(pair->prev_color && pair->next_color && pair->prev_color != pair->next_color && output);
    ++generated;
}

extern "C"
{
VKAPI_ATTR VkResult VKAPI_CALL vkDeviceWaitIdle(VkDevice) { assert(queue_locked); return VK_SUCCESS; }
VKAPI_ATTR void VKAPI_CALL vkGetPhysicalDeviceFormatProperties(VkPhysicalDevice, VkFormat, VkFormatProperties *p)
{
    p->optimalTilingFeatures = VK_FORMAT_FEATURE_BLIT_SRC_BIT | VK_FORMAT_FEATURE_BLIT_DST_BIT |
        VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT | VK_FORMAT_FEATURE_STORAGE_IMAGE_BIT |
        VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT;
}
VKAPI_ATTR VkResult VKAPI_CALL vkCreateImage(VkDevice, const VkImageCreateInfo *p, const VkAllocationCallbacks *, VkImage *out)
{
    ++creates;
    if (fail_image) return VK_ERROR_OUT_OF_DEVICE_MEMORY;
    assert(p->format == VK_FORMAT_R8G8B8A8_UNORM);
    *out = fresh<VkImage>(); layouts[*out] = VK_IMAGE_LAYOUT_UNDEFINED; ++images_alive; return VK_SUCCESS;
}
VKAPI_ATTR void VKAPI_CALL vkDestroyImage(VkDevice, VkImage i, const VkAllocationCallbacks *) { layouts.erase(i); --images_alive; }
VKAPI_ATTR void VKAPI_CALL vkGetImageMemoryRequirements(VkDevice, VkImage, VkMemoryRequirements *p)
{ p->size = 4096; p->alignment = 64; p->memoryTypeBits = 1; }
VKAPI_ATTR void VKAPI_CALL vkGetPhysicalDeviceMemoryProperties(VkPhysicalDevice, VkPhysicalDeviceMemoryProperties *p)
{
    p->memoryTypeCount = 1; p->memoryTypes[0].propertyFlags = VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT;
    if (host_visible) p->memoryTypes[0].propertyFlags |= VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT;
    if (host_coherent) p->memoryTypes[0].propertyFlags |= VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
}
VKAPI_ATTR VkResult VKAPI_CALL vkAllocateMemory(VkDevice, const VkMemoryAllocateInfo *p, const VkAllocationCallbacks *, VkDeviceMemory *out)
{ *out = fresh<VkDeviceMemory>(); allocations[*out].resize(p->allocationSize); return VK_SUCCESS; }
VKAPI_ATTR void VKAPI_CALL vkFreeMemory(VkDevice, VkDeviceMemory memory, const VkAllocationCallbacks *) { allocations.erase(memory); }
VKAPI_ATTR VkResult VKAPI_CALL vkCreateBuffer(VkDevice, const VkBufferCreateInfo *p, const VkAllocationCallbacks *, VkBuffer *out)
{ assert(p->size == preview_pixels.size()); *out = fresh<VkBuffer>(); buffers[*out] = {}; return VK_SUCCESS; }
VKAPI_ATTR void VKAPI_CALL vkDestroyBuffer(VkDevice, VkBuffer buffer, const VkAllocationCallbacks *) { buffers.erase(buffer); }
VKAPI_ATTR void VKAPI_CALL vkGetBufferMemoryRequirements(VkDevice, VkBuffer, VkMemoryRequirements *p)
{ p->size = preview_pixels.size(); p->alignment = 64; p->memoryTypeBits = 1; }
VKAPI_ATTR VkResult VKAPI_CALL vkBindBufferMemory(VkDevice, VkBuffer b, VkDeviceMemory m, VkDeviceSize)
{ buffers[b] = m; return VK_SUCCESS; }
VKAPI_ATTR VkResult VKAPI_CALL vkMapMemory(VkDevice, VkDeviceMemory m, VkDeviceSize, VkDeviceSize, VkMemoryMapFlags, void **out)
{ if (fail_map) return VK_ERROR_MEMORY_MAP_FAILED; *out = allocations[m].data(); return VK_SUCCESS; }
VKAPI_ATTR void VKAPI_CALL vkUnmapMemory(VkDevice, VkDeviceMemory) {}
VKAPI_ATTR VkResult VKAPI_CALL vkInvalidateMappedMemoryRanges(VkDevice, uint32_t count, const VkMappedMemoryRange *r)
{ assert(!readback_pending && count == 1 && r->size == VK_WHOLE_SIZE); ++invalidations; return VK_SUCCESS; }
VKAPI_ATTR void VKAPI_CALL vkCmdCopyImageToBuffer(VkCommandBuffer, VkImage image, VkImageLayout layout,
    VkBuffer buffer, uint32_t count, const VkBufferImageCopy *p)
{
    assert(layouts[image] == layout && count == 1 && p->imageExtent.width == ps5_framegen::probe_width && p->imageExtent.height == ps5_framegen::probe_height);
    std::copy(preview_pixels.begin(), preview_pixels.end(), allocations[buffers[buffer]].begin());
    readback_pending = true;
}
VKAPI_ATTR VkResult VKAPI_CALL vkBindImageMemory(VkDevice, VkImage, VkDeviceMemory, VkDeviceSize) { return VK_SUCCESS; }
VKAPI_ATTR VkResult VKAPI_CALL vkCreateImageView(VkDevice, const VkImageViewCreateInfo *, const VkAllocationCallbacks *, VkImageView *out)
{ *out = fresh<VkImageView>(); return VK_SUCCESS; }
VKAPI_ATTR void VKAPI_CALL vkDestroyImageView(VkDevice, VkImageView, const VkAllocationCallbacks *) {}
VKAPI_ATTR VkResult VKAPI_CALL vkCreateCommandPool(VkDevice, const VkCommandPoolCreateInfo *, const VkAllocationCallbacks *, VkCommandPool *out)
{ *out = fresh<VkCommandPool>(); return VK_SUCCESS; }
VKAPI_ATTR void VKAPI_CALL vkDestroyCommandPool(VkDevice, VkCommandPool, const VkAllocationCallbacks *) {}
VKAPI_ATTR VkResult VKAPI_CALL vkAllocateCommandBuffers(VkDevice, const VkCommandBufferAllocateInfo *, VkCommandBuffer *out)
{ *out = fresh<VkCommandBuffer>(); return VK_SUCCESS; }
VKAPI_ATTR VkResult VKAPI_CALL vkCreateFence(VkDevice, const VkFenceCreateInfo *, const VkAllocationCallbacks *, VkFence *out)
{ *out = fresh<VkFence>(); fences[*out] = false; return VK_SUCCESS; }
VKAPI_ATTR void VKAPI_CALL vkDestroyFence(VkDevice, VkFence f, const VkAllocationCallbacks *) { fences.erase(f); }
VKAPI_ATTR VkResult VKAPI_CALL vkCreateSemaphore(VkDevice, const VkSemaphoreCreateInfo *, const VkAllocationCallbacks *, VkSemaphore *out)
{ *out = fresh<VkSemaphore>(); semaphores[*out] = false; return VK_SUCCESS; }
VKAPI_ATTR void VKAPI_CALL vkDestroySemaphore(VkDevice, VkSemaphore s, const VkAllocationCallbacks *) { semaphores.erase(s); }
VKAPI_ATTR VkResult VKAPI_CALL vkResetCommandPool(VkDevice, VkCommandPool, VkCommandPoolResetFlags) { return VK_SUCCESS; }
VKAPI_ATTR VkResult VKAPI_CALL vkBeginCommandBuffer(VkCommandBuffer, const VkCommandBufferBeginInfo *) { return VK_SUCCESS; }
VKAPI_ATTR VkResult VKAPI_CALL vkEndCommandBuffer(VkCommandBuffer) { return VK_SUCCESS; }
VKAPI_ATTR VkResult VKAPI_CALL vkResetFences(VkDevice, uint32_t count, const VkFence *f)
{ for (uint32_t i = 0; i < count; ++i) fences[f[i]] = false; return VK_SUCCESS; }
VKAPI_ATTR VkResult VKAPI_CALL vkWaitForFences(VkDevice, uint32_t count, const VkFence *f, VkBool32, uint64_t)
{ assert(!queue_locked); for (uint32_t i = 0; i < count; ++i) assert(fences[f[i]]); return VK_SUCCESS; }
VKAPI_ATTR VkResult VKAPI_CALL vkQueueSubmit(VkQueue, uint32_t count, const VkSubmitInfo *info, VkFence fence)
{
    ++submissions;
    assert(queue_locked);
    if (submit_result != VK_SUCCESS) return submit_result;
    for (uint32_t i = 0; i < count; ++i)
        for (uint32_t j = 0; j < info[i].waitSemaphoreCount; ++j)
        { const auto s = info[i].pWaitSemaphores[j]; assert(semaphores[s]); semaphores[s] = false; }
    readback_pending = false; fences[fence] = true; return VK_SUCCESS;
}
VKAPI_ATTR void VKAPI_CALL vkCmdPipelineBarrier(VkCommandBuffer, VkPipelineStageFlags, VkPipelineStageFlags,
    VkDependencyFlags, uint32_t, const VkMemoryBarrier *, uint32_t, const VkBufferMemoryBarrier *,
    uint32_t count, const VkImageMemoryBarrier *b)
{
    for (uint32_t i = 0; i < count; ++i)
    { assert(layouts[b[i].image] == b[i].oldLayout); layouts[b[i].image] = b[i].newLayout; }
}
VKAPI_ATTR void VKAPI_CALL vkCmdBlitImage(VkCommandBuffer, VkImage src, VkImageLayout sl,
    VkImage dst, VkImageLayout dl, uint32_t, const VkImageBlit *, VkFilter)
{ assert(layouts[src] == sl && layouts[dst] == dl); }
VKAPI_ATTR VkResult VKAPI_CALL vkQueuePresentKHR(VkQueue, const VkPresentInfoKHR *p)
{
    assert(p->waitSemaphoreCount == 0 && p->swapchainCount == 1);
    assert(queue_locked);
    assert(layouts[images[*p->pImageIndices]] == VK_IMAGE_LAYOUT_PRESENT_SRC_KHR);
    std::unique_lock lock(present_mutex);
    if (*p->pImageIndices == 1)
    {
        // Regression: a delayed real present must run outside the renderer's
        // call. The caller returns even while this presentation is held.
        assert(!inside_frame);
        real_entered = true;
        present_changed.notify_all();
        present_changed.wait(lock, [] { return !hold_real; });
    }
    presented.push_back(*p->pImageIndices);
    present_changed.notify_all();
    return *p->pImageIndices == 1 ? real_present_result : present_result;
}
VKAPI_ATTR VkResult VKAPI_CALL vkAcquireNextImageKHR(VkDevice, VkSwapchainKHR, uint64_t,
    VkSemaphore sem, VkFence, uint32_t *index)
{
    ++acquires;
    if (acquire_result != VK_SUCCESS && acquire_result != VK_SUBOPTIMAL_KHR) return acquire_result;
    assert(!semaphores[sem]); semaphores[sem] = true; *index = 1; return acquire_result;
}
}

int main()
{
    reset_swap_images(); VkResult r{};
    assert(frame(r) && r == VK_SUCCESS && shown().size() == 1 && generated == 0);
    assert(!semaphores[rendered]);
    std::this_thread::sleep_for(std::chrono::milliseconds(35));
    { std::lock_guard lock(present_mutex); hold_real = true; }
    assert(frame(r) && r == VK_SUCCESS && generated == 1 && acquires == 1);
    {
        std::unique_lock lock(present_mutex);
        assert(present_changed.wait_for(lock, std::chrono::seconds(2), [] { return real_entered; }));
        assert(presented.size() == 2 && presented[1] == 0);
        hold_real = false;
        present_changed.notify_all();
    }
    await_present(3);
    assert(shown()[2] == 1);
    assert(!semaphores[rendered]);
    // Resize discards history and destroys the previous network/images.
    assert(frame(r, 128) && r == VK_SUCCESS && generated == 1);
    assert(images_alive == 3 && networks_alive == 1);
    rpcs3ps5_framegen_reset(device);
    assert(images_alive == 0 && networks_alive == 0 && fences.empty());
    // Unsupported output and allocation failure leave render semaphore untouched.
    assert(!frame(r, 64, VK_FORMAT_R16G16B16A16_SFLOAT) && semaphores[rendered]);
    rpcs3ps5_framegen_reset(device); fail_image = true;
    assert(!frame(r) && semaphores[rendered]); const auto attempts = creates;
    assert(!frame(r) && creates == attempts && images_alive == 0 && networks_alive == 0);
    rpcs3ps5_framegen_reset(device); fail_image = false;
    // Errors after taking ownership must propagate, never present a second time.
    submit_result = VK_ERROR_DEVICE_LOST; const auto before_error = shown().size();
    assert(frame(r) && r == VK_ERROR_DEVICE_LOST && shown().size() == before_error);
    rpcs3ps5_framegen_reset(device); submit_result = VK_SUCCESS;
    assert(frame(r)); std::this_thread::sleep_for(std::chrono::milliseconds(35));
    acquire_result = VK_ERROR_OUT_OF_DATE_KHR;
    assert(frame(r) && r == VK_ERROR_OUT_OF_DATE_KHR);
    rpcs3ps5_framegen_reset(device); acquire_result = VK_SUCCESS;
    assert(frame(r)); std::this_thread::sleep_for(std::chrono::milliseconds(35));
    acquire_result = VK_SUBOPTIMAL_KHR;
    assert(frame(r) && r == VK_SUBOPTIMAL_KHR);
    rpcs3ps5_framegen_reset(device);
    acquire_result = VK_SUCCESS;
    // Worker failures are returned on the next call, after consuming the new
    // caller semaphore. No extra frame is presented on that error path.
    real_present_result = VK_ERROR_OUT_OF_DATE_KHR;
    assert(frame(r)); std::this_thread::sleep_for(std::chrono::milliseconds(35));
    const auto before_deferred = shown().size();
    assert(frame(r) && r == VK_SUCCESS);
    await_present(before_deferred + 2);
    assert(frame(r) && r == VK_ERROR_OUT_OF_DATE_KHR && !semaphores[rendered]);
    assert(shown().size() == before_deferred + 2);
    rpcs3ps5_framegen_reset(device);
    real_present_result = VK_SUBOPTIMAL_KHR;
    assert(frame(r)); std::this_thread::sleep_for(std::chrono::milliseconds(35));
    assert(frame(r) && r == VK_SUCCESS);
    assert(frame(r) && r == VK_SUBOPTIMAL_KHR);
    rpcs3ps5_framegen_reset(device);
    real_present_result = VK_SUCCESS;
    // Adaptive seeds its preview, resumes after two quiet pairs, then skips
    // the neural dispatch AND extra WSI acquire on a large frame change.
    auto adaptive = [&] { return frame(r, 64, VK_FORMAT_B8G8R8A8_UNORM, 2); };
    const auto initial_generated = generated, initial_acquires = acquires;
    preview_pixels.fill(0);
    assert(adaptive() && images_alive == 4 && generated == initial_generated);
    std::this_thread::sleep_for(std::chrono::milliseconds(35));
    assert(adaptive() && generated == initial_generated);
    std::this_thread::sleep_for(std::chrono::milliseconds(35));
    const auto adaptive_shown = shown().size();
    assert(adaptive() && generated == initial_generated + 1 && acquires == initial_acquires + 1);
    await_present(adaptive_shown + 2);
    preview_pixels.fill(255);
    std::this_thread::sleep_for(std::chrono::milliseconds(35));
    assert(adaptive() && generated == initial_generated + 1 && acquires == initial_acquires + 1 && !semaphores[rendered]);
    std::this_thread::sleep_for(std::chrono::milliseconds(35));
    assert(adaptive() && generated == initial_generated + 1);
    std::this_thread::sleep_for(std::chrono::milliseconds(35));
    assert(adaptive() && generated == initial_generated + 2);
    // A local 4x4 change occupies under 0.2% of the preview. It must use the
    // same real-only path as a cut: consume render semaphore, no extra acquire.
    for (unsigned y = 33; y < 37; ++y)
        for (unsigned x = 61; x < 65; ++x)
            for (unsigned c = 0; c < 3; ++c)
                preview_pixels[(y * ps5_framegen::probe_width + x) * 4 + c] = 0;
    std::this_thread::sleep_for(std::chrono::milliseconds(35));
    const auto local_generated = generated, local_acquires = acquires;
    const auto local_shown = shown().size();
    assert(adaptive() && generated == local_generated && acquires == local_acquires && !semaphores[rendered]);
    await_present(local_shown + 1);
    std::this_thread::sleep_for(std::chrono::milliseconds(35));
    assert(adaptive() && generated == local_generated);
    std::this_thread::sleep_for(std::chrono::milliseconds(35));
    assert(adaptive() && generated == local_generated + 1);
    // Off drains any pending real image, destroys resources and leaves the
    // new caller semaphore untouched for RPCS3's normal present path.
    assert(!frame(r, 64, VK_FORMAT_B8G8R8A8_UNORM, 0) && semaphores[rendered]);
    assert(images_alive == 0 && networks_alive == 0 && buffers.empty() && allocations.empty());
    assert(!frame(r, 64, VK_FORMAT_B8G8R8A8_UNORM, 99));
    host_coherent = false;
    const auto before_invalidate = invalidations;
    assert(adaptive() && invalidations == before_invalidate + 1);
    rpcs3ps5_framegen_reset(device);
    host_visible = false;
    assert(!adaptive() && semaphores[rendered] && images_alive == 0 && buffers.empty() && allocations.empty());
    assert(frame(r)); // On does not require host-visible preview memory.
    rpcs3ps5_framegen_reset(device);
    host_visible = host_coherent = true; fail_map = true;
    assert(!adaptive() && semaphores[rendered] && images_alive == 0 && buffers.empty() && allocations.empty());
    rpcs3ps5_framegen_reset(device); fail_map = false;
    assert(images_alive == 0 && networks_alive == 0 && fences.empty());
    assert(semaphores.size() == 1); // caller's semaphore alone remains
}
