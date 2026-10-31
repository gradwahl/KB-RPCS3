#!/usr/bin/env python3
"""Run the actual RPCS3 VK wait_for_event body with deterministic host stubs.

Section 2 correctness gate only: validates existing spin/sleep/timeout/error
semantics before any change.  Does not alter emulator source or console state.
"""
from __future__ import annotations
from pathlib import Path
import argparse
import subprocess
import tempfile

HOST = r"""
#include <algorithm>
#include <atomic>
#include <cassert>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <thread>
using u64 = uint64_t;
using s64 = int64_t;
using VkResult = int;
constexpr VkResult VK_SUCCESS = 0;
constexpr VkResult VK_TIMEOUT = 2;
constexpr VkResult VK_EVENT_SET = 3;
constexpr VkResult VK_EVENT_RESET = 4;
constexpr VkResult VK_ERROR_DEVICE_LOST = -4;
namespace utils {
    u64 get_tsc_freq() { return 1000000000ULL; }
    u64 get_tsc() {
        return static_cast<u64>(std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count());
    }
    void pause() { __asm__ volatile("pause" ::: "memory"); }
}
u64 get_system_time() { return utils::get_tsc() / 1000; }
struct logger {
    unsigned errors = 0;
    void error(const char*) { errors++; }
} rsx_log;
void die_with_error(VkResult) {}
enum { PS5_TUNE_VK_EVENT_SPIN_US = 2, PS5_TUNE_VK_EVENT_SLEEP_US = 3 };
std::atomic<s64> g_spin_us{-1}, g_sleep_us{100};
extern "C" s64 rpcs3ps5_tune(int key) {
    return key == 2 ? g_spin_us.load() : key == 3 ? g_sleep_us.load() : -1;
}
namespace vk {
struct event {
    std::atomic<VkResult> value{VK_EVENT_RESET};
    VkResult status() const { return value.load(std::memory_order_acquire); }
    void set(VkResult new_status) { value.store(new_status, std::memory_order_release); }
};
static std::atomic<u64> g_ps5_vk_event_waits{0};
static std::atomic<u64> g_ps5_vk_event_spin_tsc{0};
static std::atomic<u64> g_ps5_vk_event_sleeps{0};
extern "C" void ps5_vk_event_stats(uint64_t* waits, uint64_t* spin_tsc, uint64_t* sleeps)
{
    *waits = g_ps5_vk_event_waits.load(std::memory_order_relaxed);
    *spin_tsc = g_ps5_vk_event_spin_tsc.load(std::memory_order_relaxed);
    *sleeps = g_ps5_vk_event_sleeps.load(std::memory_order_relaxed);
}
EXTRACTED
}

void zero_stats() {
    vk::g_ps5_vk_event_waits.store(0);
    vk::g_ps5_vk_event_spin_tsc.store(0);
    vk::g_ps5_vk_event_sleeps.store(0);
}
struct sampled { u64 waits, spin_ticks, sleeps; };
sampled read_stats() {
    sampled x{};
    vk::ps5_vk_event_stats(&x.waits,&x.spin_ticks,&x.sleeps);
    return x;
}
int main() {
    using namespace std::chrono_literals;
    using vk::event;
    // A signaled event must return immediately; no sample may accrue.
    for (s64 spin : {-1,0,50,1000}) {
        zero_stats();
        g_spin_us=spin;
        event e; e.set(VK_EVENT_SET);
        assert(vk::wait_for_event(&e,500000)==VK_SUCCESS);
        auto stats=read_stats();
        assert(stats.waits==0 && stats.spin_ticks==0 && stats.sleeps==0);
    }
    // Default unbounded spin retains current semantics and never sleeps.
    {
        zero_stats();g_spin_us=-1;
        event e;
        std::thread producer([&]{ std::this_thread::sleep_for(2ms);e.set(VK_EVENT_SET); });
        assert(vk::wait_for_event(&e,500000)==VK_SUCCESS);
        producer.join();
        auto stats=read_stats();
        assert(stats.waits==1 && stats.spin_ticks>0 && stats.sleeps==0);
    }
    // Finite short spin reliably wakes after event changes.
    for (s64 spin : {0,50,200}) {
        zero_stats();g_spin_us=spin;g_sleep_us=100;
        event e;
        std::thread producer([&]{std::this_thread::sleep_for(5ms);e.set(VK_EVENT_SET);});
        assert(vk::wait_for_event(&e,500000)==VK_SUCCESS);
        producer.join();
        auto stats=read_stats();
        assert(stats.waits==1 && stats.sleeps>0);
        if(spin==0) assert(stats.spin_ticks==0);
    }
    // Timeouts need to terminate, account the wait and log exactly once.
    for (s64 spin : {-1,0,200}) {
        zero_stats();g_spin_us=spin;g_sleep_us=100;
        event never_set;
        auto initial_errors=rsx_log.errors;
        assert(vk::wait_for_event(&never_set,3000)==VK_TIMEOUT);
        auto stats=read_stats();
        assert(stats.waits==1 && rsx_log.errors==initial_errors+1);
        if(spin==0) assert(stats.sleeps>0 && stats.spin_ticks==0);
    }
    // Invalid status must return the same code and invoke the error hook.
    {
        zero_stats();g_spin_us=0;
        event e; e.set(VK_ERROR_DEVICE_LOST);
        assert(vk::wait_for_event(&e,500000)==VK_ERROR_DEVICE_LOST);
        assert(read_stats().waits==0);
    }
    std::puts("PASS: actual Vulkan event wait: immediate, unbounded spin, bounded sleep/wake, timeout, invalid/error status and counters");
}
"""


def real_source_function(text: str) -> str:
    needle = "\tVkResult wait_for_event(event* pEvent, u64 timeout)\n\t{"
    assert text.count(needle) == 1, "VK event implementation moved; inspect manually"
    start = text.index(needle)
    opening = text.index("{", start)
    depth = 0
    closing = None
    for i in range(opening, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                closing = i + 1
                break
    assert closing and depth == 0
    code = text[start:closing]
    assert "PS5_TUNE_VK_EVENT_SPIN_US" in code
    assert "VK_TIMEOUT" in code
    assert "std::this_thread::sleep_for" in code
    assert "g_ps5_vk_event_spin_tsc" in code
    assert "case VK_EVENT_SET:" in code
    return code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path.home() / "work/rpcs3-latest")
    a = parser.parse_args()
    text = (a.source / "rpcs3/Emu/RSX/VK/vkutils/sync.cpp").read_text(encoding="utf-8")
    fn = real_source_function(text)
    with tempfile.TemporaryDirectory(prefix="ps5-vk-event-wait-") as directory:
        d = Path(directory)
        source = d / "actual-wait.cpp"
        source.write_text(HOST.replace("EXTRACTED", fn), encoding="utf8")
        binary = d / "actual-wait"
        cmd = ["clang++-19", "-std=c++20", "-D__PROSPERO__",
               "-O2", "-Wall", "-Wextra", "-Werror", "-pthread",
               str(source), "-o", str(binary)]
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=45)
        process = subprocess.run([str(binary)], check=True, capture_output=True,
                                 text=True, timeout=15)
        print(process.stdout.strip())


if __name__ == "__main__":
    main()
