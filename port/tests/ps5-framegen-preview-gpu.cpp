// Exercise the production preview copy/readback and detector on real Vulkan.
// No WSI or console gameplay claim: this is a device-local transfer test.
#include "ps5_framegen.cpp"
#include <cassert>
#include <vector>

int main()
{
    VkInstance instance{};
    VkApplicationInfo app{}; app.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO; app.apiVersion = VK_API_VERSION_1_1;
    VkInstanceCreateInfo ici{}; ici.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO; ici.pApplicationInfo = &app;
    assert(vkCreateInstance(&ici, nullptr, &instance) == VK_SUCCESS);
    uint32_t count = 0;
    assert(vkEnumeratePhysicalDevices(instance, &count, nullptr) == VK_SUCCESS && count > 0);
    std::vector<VkPhysicalDevice> gpus(count);
    assert(vkEnumeratePhysicalDevices(instance, &count, gpus.data()) == VK_SUCCESS);
    const auto gpu = gpus[0];
    vkGetPhysicalDeviceQueueFamilyProperties(gpu, &count, nullptr);
    std::vector<VkQueueFamilyProperties> families(count);
    vkGetPhysicalDeviceQueueFamilyProperties(gpu, &count, families.data());
    uint32_t family = 0;
    while (family < count && !(families[family].queueFlags & VK_QUEUE_GRAPHICS_BIT)) ++family;
    assert(family < count);
    const float priority = 1;
    VkDeviceQueueCreateInfo qci{}; qci.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO;
    qci.queueFamilyIndex = family; qci.queueCount = 1; qci.pQueuePriorities = &priority;
    VkDeviceCreateInfo dci{}; dci.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO;
    dci.queueCreateInfoCount = 1; dci.pQueueCreateInfos = &qci;
    assert(vkCreateDevice(gpu, &dci, nullptr, &state.device) == VK_SUCCESS);
    const auto device = state.device;
    VkQueue queue{}; vkGetDeviceQueue(device, family, 0, &queue);
    state.width = state.height = 64;
    assert(make_image(gpu, state.real[0]) == VK_SUCCESS);
    assert(make_preview(gpu) == VK_SUCCESS);
    VkCommandPoolCreateInfo pci{}; pci.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
    pci.queueFamilyIndex = family; pci.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
    assert(vkCreateCommandPool(device, &pci, nullptr, &state.pool) == VK_SUCCESS);
    VkCommandBufferAllocateInfo cai{}; cai.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
    cai.commandPool = state.pool; cai.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY; cai.commandBufferCount = 1;
    assert(vkAllocateCommandBuffers(device, &cai, &state.cmd) == VK_SUCCESS);
    VkFenceCreateInfo fci{}; fci.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
    assert(vkCreateFence(device, &fci, nullptr, &state.fence) == VK_SUCCESS);
    auto preview = [&](bool white)
    {
        assert(begin() == VK_SUCCESS);
        layout(state.real[0], VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
        const float rgb = white ? 1.f : 0.f;
        const VkClearColorValue colour{{rgb, rgb, rgb, 1.f}};
        const VkImageSubresourceRange range{VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
        vkCmdClearColorImage(state.cmd, state.real[0].image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, &colour, 1, &range);
        record_preview(state.real[0]);
        assert(submit(queue, VK_NULL_HANDLE) == VK_SUCCESS);
        if (!state.preview.coherent)
        {
            VkMappedMemoryRange mapped{}; mapped.sType = VK_STRUCTURE_TYPE_MAPPED_MEMORY_RANGE;
            mapped.memory = state.preview.memory; mapped.size = VK_WHOLE_SIZE;
            assert(vkInvalidateMappedMemoryRanges(device, 1, &mapped) == VK_SUCCESS);
        }
        auto data = static_cast<const uint8_t *>(state.preview.mapped);
        for (unsigned i = 0; i < ps5_framegen::probe_bytes; ++i)
            assert(data[i] == (i % 4 == 3 || white ? 255 : 0));
        return state.motion.accept({data, ps5_framegen::probe_bytes});
    };
    assert(!preview(false)); assert(!preview(false)); assert(preview(false));
    assert(!preview(true)); assert(!preview(true)); assert(preview(true));
    destroy();
    vkDestroyDevice(device, nullptr);
    vkDestroyInstance(instance, nullptr);
    std::puts("PASS real Vulkan downsample/readback pixel values and Adaptive reject/recover");
}
