// PS5 presentation bridge. SPDX-License-Identifier: MIT
#pragma once
#include <vulkan/vulkan.h>
#include <stdbool.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
// Called only on the presentation thread, with the same graphics/present queue.
// false leaves the caller's image and semaphore untouched. true consumes the
// render semaphore and returns the result of our presentation(s) in result.
bool rpcs3ps5_framegen_present(VkDevice device, VkPhysicalDevice gpu, VkQueue queue,
    uint32_t family, VkSwapchainKHR swapchain, uint32_t width, uint32_t height,
    VkFormat format, const VkImage *images, uint32_t count, uint32_t index,
    VkSemaphore rendered, VkResult *result, uint32_t mode, void (*lock_queue)(void), void (*unlock_queue)(void));
// Must run before destroying/replacing the swapchain or its device.
void rpcs3ps5_framegen_reset(VkDevice device);
void rpcs3ps5_framegen_set_refresh(uint32_t refresh_millihz);
#ifdef __cplusplus
}
#endif
