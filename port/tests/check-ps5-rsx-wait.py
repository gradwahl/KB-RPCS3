#!/usr/bin/env python3
"""Compile the actual DMA sync routine and exercise its completion/wakeup paths."""
from pathlib import Path
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile

source = (Path(sys.argv[1]) / 'rpcs3/Emu/RSX/RSXOffload.cpp').read_text()
start = source.index('\tbool dma_manager::sync() const')
end = source.index('\n\tvoid dma_manager::join()', start)
routine = source[start:end]
program = r'''
#include <algorithm>
#include <atomic>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <functional>
#include <iostream>
#include <limits>
#include <memory>
#include <mutex>
#include <thread>
using s64 = int64_t;
using u64 = uint64_t;
using u32 = uint32_t;
enum { PS5_TUNE_RSX_DMA_WAIT_US = 10 };
std::atomic<s64> mode{0};
extern "C" s64 rpcs3ps5_tune(int) { return mode.load(); }
enum class atomic_wait_timeout : u64 {};
namespace utils { void pause() { std::this_thread::yield(); } }
struct counter
{
    std::atomic<u64> value{0};
    std::atomic<u64> waits{0};
    std::mutex mutex;
    std::condition_variable condition;
    std::function<void()> before_wait;
    u64 load() const { return value.load(); }
    void store(u64 next) { value.store(next); condition.notify_all(); }
    void wait(u64 old, atomic_wait_timeout timeout)
    {
        waits++;
        if (before_wait) before_wait();
        std::unique_lock lock(mutex);
        condition.wait_for(lock, std::chrono::nanoseconds(static_cast<u64>(timeout)),
                           [&] { return load() != old; });
    }
};
struct fake_renderer
{
    bool current = true;
    u64 calls = 0;
    std::function<void()> hook;
    bool is_current_thread() const { return current; }
    fake_renderer* renderer() { return this; }
    void on_semaphore_acquire_wait() { calls++; if (hook) hook(); }
};
namespace rsx
{
fake_renderer renderer_instance;
fake_renderer* get_current_renderer() { return &renderer_instance; }
struct offloader { counter m_enqueued_count, m_processed_count; };
class dma_manager
{
public:
    std::shared_ptr<offloader> m_thread = std::make_shared<offloader>();
    bool m_mem_fault_flag = false;
    bool sync() const;
};
ROUTINE
}
int main()
{
    using namespace rsx;
    for (bool renderer_thread : {true, false})
    for (s64 wait_us : {0, 100, 2000})
    for (int repeat = 0; repeat < 8; repeat++)
    {
        renderer_instance = {};
        renderer_instance.current = renderer_thread;
        mode = wait_us;
        dma_manager manager;
        manager.m_thread->m_enqueued_count.store(1);
        std::thread worker([&]
        {
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
            manager.m_thread->m_processed_count.store(1);
        });
        assert(manager.sync());
        worker.join();
        assert(manager.m_thread->m_processed_count.load() == 1);
        if (!wait_us) assert(manager.m_thread->m_processed_count.waits == 0);
        else assert(manager.m_thread->m_processed_count.waits > 0);
    }
    mode = 100;
    renderer_instance = {};
    dma_manager callback;
    callback.m_thread->m_enqueued_count.store(1);
    renderer_instance.hook = [&]
    {
        if (renderer_instance.calls == 256) callback.m_thread->m_processed_count.store(1);
    };
    assert(callback.sync()); // renderer callbacks must keep making progress
    assert(callback.m_thread->m_processed_count.waits > 0);
    renderer_instance = {};
    dma_manager race;
    race.m_thread->m_enqueued_count.store(1);
    race.m_thread->m_processed_count.before_wait = [&]
    { race.m_thread->m_processed_count.store(1); };
    assert(race.sync()); // completion between the snapshot and the wait
    dma_manager fault;
    fault.m_thread->m_enqueued_count.store(1);
    fault.m_mem_fault_flag = true;
    assert(!fault.sync());
    dma_manager stopped;
    stopped.m_thread->m_enqueued_count.store(1);
    stopped.m_thread->m_processed_count.store(std::numeric_limits<u64>::max());
    assert(stopped.sync()); // original offloader termination sentinel
    std::cout << "PASS: DMA completion, disabled mode, callback progress, wakeup race, fault and stop\n";
}
'''.replace('ROUTINE', routine)
compiler = shutil.which('clang++-19') or shutil.which('c++')
if not compiler:
    raise SystemExit('A host C++ compiler is required')
with tempfile.TemporaryDirectory() as temporary:
    directory = Path(temporary)
    test, binary = directory / 'dma-wait.cpp', directory / 'dma-wait'
    test.write_text(program)
    subprocess.run([compiler, '-std=c++20', '-D__PROSPERO__', '-pthread',
                    str(test), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=15)

    # Compile the real title-side parser and verify the new key's safe limits.
    title_source = Path(__file__).resolve().parents[2] / 'app/ps5/src/ps5_tuning.c'
    library = directory / 'tuning.so'
    subprocess.run([compiler, '-x', 'c', '-std=c11', '-shared', '-fPIC',
                    f'-DPS5_APP_ROOT="{directory}"', str(title_source),
                    '-o', str(library)], check=True)
    tuning = ctypes.CDLL(str(library))
    tuning.rpcs3ps5_tune.argtypes = [ctypes.c_int]
    tuning.rpcs3ps5_tune.restype = ctypes.c_int64
    tuning.rpcs3ps5_tune_describe.restype = ctypes.c_char_p
    assert tuning.rpcs3ps5_tune(10) == 0
    settings = directory / 'rpcs3/ps5-tuning.txt'
    settings.parent.mkdir()
    for index, (requested, expected) in enumerate(((-1, 0), (100, 100), (9000, 2000))):
        settings.write_text(f'rsx_dma_wait_us {requested}\n')
        os.utime(settings, (1000 + index, 1000 + index))
        tuning.rpcs3ps5_tune_refresh()
        assert tuning.rpcs3ps5_tune(10) == expected
        assert tuning.rpcs3ps5_tune(0) == 4000
        assert f'rsx_dma_wait_us={expected}'.encode() in tuning.rpcs3ps5_tune_describe()
    settings.unlink()
    tuning.rpcs3ps5_tune_refresh()
    assert tuning.rpcs3ps5_tune(10) == 0
    print('PASS: title tuning defaults, clamping, logging and deletion rollback')
