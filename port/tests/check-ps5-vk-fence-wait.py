#!/usr/bin/env python3
"""Offline Vulkan fence wait API/zero-timeout busy-poll correctness gates.

Extracts the actual current RPCS3 wait_for_fence implementation from WSL
source, compiles it unchanged with deterministic Vulkan stubs, and tests:
immediate, producer-completes, explicit timed Vulkan wait, and device loss.
Does NOT change the PS5 fence policy or claim performance improvement.
"""
from pathlib import Path
import argparse
import subprocess
import tempfile

HARNESS = r"""
#include <atomic>
#include <cassert>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <thread>
using u64 = uint64_t;
using VkResult = int;
constexpr VkResult VK_SUCCESS = 0;
constexpr VkResult VK_TIMEOUT = 2;
constexpr VkResult VK_NOT_READY = 1;
constexpr VkResult VK_ERROR_DEVICE_LOST = -4;
constexpr int VK_FALSE = 0;
namespace utils { std::atomic<unsigned> polls{0}; void pause() { polls++;__asm__ volatile("pause":::"memory"); } }
struct logger { unsigned errors = 0; void error(const char*) { errors++; } } rsx_log;
std::atomic<unsigned> gpu_checks{0}, wait_calls{0}, flush_calls{0};
std::atomic<u64> timeout_last{0};
std::atomic<VkResult> gpu_result{VK_NOT_READY};
std::atomic<VkResult> injected_wait_result{VK_TIMEOUT};
void die_with_error(VkResult) { rsx_log.errors++; }
using VkDevice = int;
VkDevice gpu_handle = 3;
VkDevice* g_render_device = &gpu_handle;
VkResult vkGetFenceStatus(VkDevice, int) {
    gpu_checks++;
    return gpu_result.load(std::memory_order_acquire);
}
VkResult vkWaitForFences(VkDevice, unsigned num, const int*, int wait_all, u64 ns) {
    assert(num == 1 && wait_all == VK_FALSE);
    wait_calls++;
    timeout_last = ns;
    if (injected_wait_result.load() == VK_ERROR_DEVICE_LOST) return VK_ERROR_DEVICE_LOST;
    if (gpu_result.load() == VK_SUCCESS) return VK_SUCCESS;
    std::this_thread::sleep_for(std::chrono::microseconds(100));
    return gpu_result.load() == VK_SUCCESS ? VK_SUCCESS : VK_TIMEOUT;
}
namespace ps5_frame_trace {
  enum class event { vk_fence_begin,vk_fence_end };
  static unsigned starts=0,ends=0;
  void mark(event e) { if (e==event::vk_fence_begin) ++starts;else ++ends; }
}
namespace vk {
struct fence {
    int handle=22;
    void wait_flush(){ flush_calls++; }
};
EXTRACTED
}
int main() {
    using namespace std::chrono_literals;
    vk::fence f;
    // Already signalled: busy-poll path returns immediately.
    gpu_result = VK_SUCCESS;
    assert(vk::wait_for_fence(&f,0)==VK_SUCCESS);
    assert(gpu_checks==1 && wait_calls==0 && flush_calls==1);
    // A producer completes after the consumer entered the poll loop.
    gpu_result = VK_NOT_READY;
    std::thread writer([]{ std::this_thread::sleep_for(4ms);gpu_result=VK_SUCCESS; });
    auto before_polls=utils::polls.load();
    assert(vk::wait_for_fence(&f,0)==VK_SUCCESS);
    writer.join();
    assert(utils::polls>before_polls);
#if PS5_VK_FENCE_TIMED_WAIT
    assert(wait_calls>0); // a bounded Vulkan wait actually ran
#else
    assert(wait_calls==0); // byte-for-byte baseline policy
#endif
    // Explicit timed path invokes Vulkan API with timeout_us * 1000.
    // Count relative to the prior delayed completion: diagnostic mode
    // may also have used bounded waits during that previous stage.
    const unsigned wait_before_timeout=wait_calls.load();
    gpu_result=VK_NOT_READY;
    assert(vk::wait_for_fence(&f,200)==VK_TIMEOUT);
    assert(wait_calls==wait_before_timeout+1 && timeout_last==200000 && gpu_checks>1);
    gpu_result=VK_SUCCESS;
    assert(vk::wait_for_fence(&f,300)==VK_SUCCESS);
    assert(wait_calls==wait_before_timeout+2 && timeout_last==300000);
    // A driver error must be returned, not retried forever.
    gpu_result=VK_ERROR_DEVICE_LOST;
    assert(vk::wait_for_fence(&f,0)==VK_ERROR_DEVICE_LOST);
    assert(rsx_log.errors==1);
#if PS5_VK_FENCE_TIMED_WAIT
    // Error delivered *during* the bounded Vulkan wait must propagate.
    injected_wait_result=VK_ERROR_DEVICE_LOST;
    gpu_result=VK_NOT_READY;
    assert(vk::wait_for_fence(&f,0)==VK_ERROR_DEVICE_LOST);
    assert(rsx_log.errors==2);
    injected_wait_result=VK_TIMEOUT;
#endif
    assert(ps5_frame_trace::starts==ps5_frame_trace::ends);
    assert(ps5_frame_trace::starts==(PS5_VK_FENCE_TIMED_WAIT ? 6u:5u));
    std::puts("PASS: actual Vulkan fence wait: busy-poll completion, delayed signal, Vulkan timeout conversion, error, flush and trace pairing");
}
"""


def function(text: str) -> str:
    marker = "\tVkResult wait_for_fence(fence* pFence, u64 timeout)"
    assert text.count(marker) == 1, "function changed, re-review required"
    begin = text.index(marker)
    open_brace = text.index("{", begin)
    level = 0
    for idx in range(open_brace, len(text)):
        if text[idx] == "{":
            level += 1
        elif text[idx] == "}":
            level -= 1
            if level == 0:
                body = text[begin:idx + 1]
                break
    else:
        raise AssertionError("unbalanced wait_for_fence source")
    for term in ("vkWaitForFences", "vkGetFenceStatus", "VK_NOT_READY", "utils::pause()", "pFence->wait_flush()"):
        assert term in body, term
    return body


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, default=Path.home() / "work/rpcs3-latest")
    args = p.parse_args()
    body = function((args.source / "rpcs3/Emu/RSX/VK/vkutils/sync.cpp").read_text("utf8"))
    with tempfile.TemporaryDirectory(prefix="ps5-fence-wait-") as d:
        tmp = Path(d)
        src = tmp / "fence.cpp"
        src.write_text(HARNESS.replace("EXTRACTED", body))
        exe = tmp / "fence"
        for mode in (0, 1):
            binary = tmp / f"fence-mode-{mode}"
            subprocess.run(["clang++-19","-std=c++20","-D__PROSPERO__",f"-DPS5_VK_FENCE_TIMED_WAIT={mode}",
                            "-O2","-Wall","-Wextra","-Werror","-pthread",str(src),"-o",str(binary)],
                           capture_output=True,text=True,check=True,timeout=45)
            result = subprocess.run([str(binary)],capture_output=True,text=True,check=False,timeout=16)
            if result.returncode:
                raise RuntimeError(f"mode={mode} failed: {result.returncode}: {result.stdout} {result.stderr}")
            print(f"mode {mode}: {result.stdout.strip()}")


if __name__ == "__main__":
    main()
