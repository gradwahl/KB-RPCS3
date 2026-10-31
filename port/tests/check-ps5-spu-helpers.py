#!/usr/bin/env python3
"""Compile actual LLVM native helper bodies; exercise normal and nonlocal exits."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

upstream = Path(sys.argv[1])
source = (upstream / 'rpcs3/Emu/Cell/SPULLVMRecompiler.cpp').read_text()
header = upstream / 'rpcs3/Emu/RSX/ps5_worker_activity.h'


def extract(signature, replacement=None, prefix=''):
    assert source.count(signature) == 1, signature
    first = source.index(signature)
    brace = source.index('{', first)
    end, depth = brace + 1, 1
    while depth:
        if source[end] == '{':
            depth += 1
        elif source[end] == '}':
            depth -= 1
        end += 1
    return prefix + (replacement or signature) + '\n' + source[brace:end]


bodies = '\n'.join((
    extract('static void exec_stop(spu_thread* _spu, u32 code)'),
    extract('static u32 exec_rdch(spu_thread* _spu, u32 ch)'),
    extract('static u32 exec_read_dec(spu_thread* _spu)'),
    extract('static u32 exec_rchcnt(spu_thread* _spu, u32 ch)'),
    extract('static u32 exec_get_events(spu_thread* _spu, u32 mask)'),
    extract('static void exec_wrch(spu_thread* _spu, u32 ch, u32 value)'),
    extract('static void exec_list_unstall(spu_thread* _spu, u32 tag)'),
    extract('static void exec_mfc_cmd(spu_thread* _spu)', prefix='template<bool Saveable>\n'),
    extract('auto wait_on_channel = [](spu_thread* _spu, spu_channel* ch, u32 is_read) -> u32',
            'static u32 wait_helper(spu_thread* _spu, spu_channel* ch, u32 is_read)'),
    extract('auto exec_mfc = [](spu_thread* _this)', 'static void queue_helper(spu_thread* _this)'),
))
program = r'''
#define __PROSPERO__
#include "HEADER"
#ifndef TEST_PS5
#undef __PROSPERO__
#endif
#include <cassert>
#include <csetjmp>
#include <cstdlib>
#include <iostream>
#include <thread>
using u32 = std::uint32_t;
using s64 = std::int64_t;
struct spu_thread;
std::jmp_buf escape_env;
namespace spu_runtime { [[noreturn]] void g_escape(spu_thread*); }
namespace cpu_flag { constexpr int again = 1, wait = 2; }
namespace fmt { [[noreturn]] void throw_exception(const char*) { std::abort(); } }
struct { struct { bool spu_loop_detection = true; } core; } g_cfg;
void (*rdch_hook)() = nullptr;
struct spu_thread {
    u32 lv2_id = 0x100, state = 0, pc = 8, mfc_size = 1;
    bool unsavable = false, stop_ok = true, stopped = false, escape_on_test = false;
    bool observed_unsavable = false;
    s64 channel_value = 7;
    int writes = 0, dma = 0, mfc = 0;
    struct { u32 tag = 0x83, cmd = 32; } ch_mfc_cmd, mfc_queue[16];
    bool stop_and_signal(u32) { return stop_ok; }
    bool test_stopped() { if (escape_on_test) spu_runtime::g_escape(this); return stopped; }
    s64 get_ch_value(u32) { if (rdch_hook) rdch_hook(); return channel_value; }
    u32 get_ch_count(u32) { return 3; }
    struct event { u32 count; };
    event get_events(u32 mask) { return {mask}; }
    std::pair<u32, bool> read_dec() { return {2001, false}; }
    bool set_ch_value(u32 ch, u32 value) { writes++; return ch == 28 && value == 123; }
    bool process_mfc_cmd() { mfc++; observed_unsavable = unsavable; return true; }
    void do_mfc(bool = true) { dma++; }
};
struct spu_channel {
    int reads = 0, writes = 0;
    void pop_wait(spu_thread&, bool) { reads++; }
    void push_wait(spu_thread&, int, bool) { writes++; }
    u32 get_count() { return 5; }
};
spu_thread cpu; // global so changes remain defined across setjmp/longjmp
namespace spu_runtime { [[noreturn]] void g_escape(spu_thread*) { std::longjmp(escape_env, 1); } }
BODIES
using namespace ps5_worker_activity;
void observe_rdch() {
    const auto live = observe_helper(*register_spu(cpu.lv2_id));
#if defined(TEST_PS5) && PS5_SPU_HELPER_ACTIVE
    assert(live.active && live.stable && live.kind == static_cast<unsigned>(helper_kind::rdch));
    assert(live.arg == 29 && live.age_tsc > 0);
#else
    assert(!live.active);
#endif
}
int main() {
    auto* slot = register_spu(cpu.lv2_id);
    const auto gateway = begin_gateway(slot);
    const auto before_helpers_tick = utils::tick.load();
    rdch_hook = observe_rdch;
    assert(exec_rdch(&cpu, 29) == 7);
    rdch_hook = nullptr;
    exec_wrch(&cpu, 28, 123);
    assert(cpu.writes == 1);
    exec_mfc_cmd<false>(&cpu);
    assert(cpu.mfc == 1 && cpu.observed_unsavable && !cpu.unsavable);
    exec_mfc_cmd<true>(&cpu);
    assert(cpu.mfc == 2 && !cpu.observed_unsavable);
    exec_list_unstall(&cpu, 3);
    assert(cpu.mfc_queue[0].tag == 3 && cpu.dma == 1);
    assert(exec_get_events(&cpu, 17) == 17);
    assert(exec_rchcnt(&cpu, 29) == 3);
    assert(exec_read_dec(&cpu) == 2001 && (cpu.state & cpu_flag::wait));
    exec_stop(&cpu, 1);
    spu_channel channel;
    assert(wait_helper(&cpu, &channel, 1) == 5 && channel.reads == 1);
    assert(wait_helper(&cpu, &channel, 0) == 5 && channel.writes == 1);
    queue_helper(&cpu);
    assert(cpu.dma == 2 && !observe_helper(*slot).active);
    end_gateway(slot, gateway);
#if defined(TEST_PS5) && PS5_SPU_HELPER_ACTIVE
    for (unsigned kind = 0; kind < helper_count; ++kind) {
        assert(slot->helpers[kind].entries > 0);
        assert(slot->helpers[kind].returns == slot->helpers[kind].entries);
        assert(slot->helpers[kind].escapes == 0);
        assert(slot->helpers[kind].normal_samples.sampled == 1);
    }
#else
    for (auto& helper : slot->helpers) assert(helper.entries == 0);
#endif
#if !PS5_SPU_HELPER_ACTIVE
    // end_gateway reads its own clock; account for that one existing read.
    assert(utils::tick.load() == before_helpers_tick + 5000);
#else
    static_cast<void>(before_helpers_tick);
#endif
    // Actual nonlocal escape bypasses end_helper; explicit gateway cleanup
    // records a separate escaped interval and clears the live helper state.
    cpu.lv2_id = 0x200;
    slot = register_spu(cpu.lv2_id);
    const auto escaping = begin_gateway(slot);
    cpu.channel_value = -1;
    if (setjmp(escape_env) == 0) {
        static_cast<void>(exec_rdch(&cpu, 29));
        assert(false);
    }
#if defined(TEST_PS5) && PS5_SPU_HELPER_ACTIVE
    assert(observe_helper(*slot).active);
#endif
    end_gateway(slot, escaping);
    assert(!observe_helper(*slot).active);
#if defined(TEST_PS5) && PS5_SPU_HELPER_ACTIVE
    auto& rdch = slot->helpers[static_cast<unsigned>(helper_kind::rdch)];
    assert(rdch.entries == 1 && rdch.returns == 0 && rdch.escapes == 1);
    assert(rdch.normal_samples.sampled == 0 && rdch.escaped_samples.sampled == 1);
#endif
    cpu.lv2_id = 0x300;
    slot = register_spu(cpu.lv2_id);
    const auto stop_gateway = begin_gateway(slot);
    cpu.stopped = true;
    if (setjmp(escape_env) == 0) {
        exec_stop(&cpu, 9);
        assert(false);
    }
    assert(cpu.pc == 12); // original stop/test behavior preserved
    end_gateway(slot, stop_gateway);
    cpu.stopped = false;
    cpu.lv2_id = 0x400;
    slot = register_spu(cpu.lv2_id);
    const auto mfc_gateway = begin_gateway(slot);
    cpu.escape_on_test = true;
    if (setjmp(escape_env) == 0) {
        exec_mfc_cmd<false>(&cpu);
        assert(false);
    }
    assert(cpu.unsavable); // escape still bypasses the original trailing reset
    end_gateway(slot, mfc_gateway);
    assert(!observe_helper(*slot).active);
    // Counter selection and nesting suppression, independent of wrappers.
#if PS5_SPU_HELPER_ACTIVE
    cpu.lv2_id = 0x500;
    slot = register_spu(cpu.lv2_id);
    auto probe = begin_helper(cpu.lv2_id, helper_kind::rdch, 29);
    assert(probe.sampled);
    auto nested = begin_helper(cpu.lv2_id, helper_kind::wrch, 28);
    assert(!nested.slot && slot->nested_helpers == 1);
    assert(observe_helper(*slot).kind == static_cast<unsigned>(helper_kind::rdch));
    end_helper(nested);
    end_helper(probe);
    for (int i = 0; i < 1023; ++i) {
        probe = begin_helper(cpu.lv2_id, helper_kind::rdch, 29);
        assert(!probe.sampled);
        end_helper(probe);
    }
    probe = begin_helper(cpu.lv2_id, helper_kind::rdch, 29);
    assert(probe.sampled);
    end_helper(probe);
    assert(slot->helpers[0].normal_samples.sampled == 2);
    assert(!begin_helper(0, helper_kind::rdch, 0).slot);
    assert(!begin_helper(cpu.lv2_id, helper_kind::count, 0).slot);
#else
    assert(!begin_helper(cpu.lv2_id, helper_kind::rdch, 29).slot);
#endif
    std::cout << "PASS: ten actual native helper bodies, preserved returns/state, live phase, first/1024 sampling, nesting, real nonlocal escape cleanup\n";
}
'''.replace('HEADER', str(header)).replace('BODIES', bodies)
compiler = shutil.which('clang++-19') or shutil.which('c++')
if not compiler:
    raise SystemExit('A host C++ compiler is required')
with tempfile.TemporaryDirectory(prefix='spu-helpers-') as temp:
    root = Path(temp)
    (root / 'util').mkdir()
    (root / 'util/tsc.hpp').write_text('''#pragma once
#include <atomic>
#include <cstdint>
namespace utils {
inline std::atomic<std::uint64_t> tick{1000000};
inline std::uint64_t get_tsc() { return tick.fetch_add(5000); }
}
''')
    cpp = root / 'test.cpp'
    cpp.write_text(program)
    for ps5, active in ((False, 1), (True, 1), (True, 0)):
        binary = root / f'test-{int(ps5)}-{active}'
        flags = ['-DTEST_PS5'] if ps5 else []
        flags += [f'-DPS5_SPU_HELPER_ACTIVE={active}']
        subprocess.run([compiler, '-std=c++20', '-O2', '-Wall', '-Wextra',
                        *flags, '-I', str(root), str(cpp), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=10)
