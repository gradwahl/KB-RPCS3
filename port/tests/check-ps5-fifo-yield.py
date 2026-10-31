#!/usr/bin/env python3
"""Exercise actual self-jump watch/empty-dispatch code with mocked OS yields.

Host proof of dispatch and recheck semantics; not a PS5 scheduling benchmark.
"""
from pathlib import Path
import ctypes
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile

upstream = Path(sys.argv[1])
source = (upstream / 'rpcs3/Emu/RSX/RSXFIFO.cpp').read_text()
header = (upstream / 'rpcs3/Emu/RSX/RSXFIFO.h').read_text()
watch = source.split('void FIFO_control::read(register_pair& data)\n\t\t{', 1)[1]
watch = watch.split('\n\t\t\tif (!g_cfg.core.rsx_fifo_accuracy)', 1)[0]
empty = source.split('\t\t\tcase FIFO::FIFO_EMPTY:\n', 1)[1]
empty = empty.split('\n\t\t\tcase FIFO::FIFO_BUSY:', 1)[0]
accessor = re.search(r'bool is_self_jump_wait\(\) const \{[^\n]+', header)[0]
key = re.search(r'static constexpr int PS5_TUNE_RSX_FIFO_YIELD = \d+;', source)[0]
program = r'''
#include <cassert>
#include <cstdint>
#include <functional>
#include <iostream>
using u32 = uint32_t;
using s64 = int64_t;
int wrapper_yields = 0, os_yields = 0;
std::function<void()> on_yield;
namespace std { namespace this_thread {
void yield() { wrapper_yields++; if (on_yield) on_yield(); }
} }
extern "C" int scePthreadYield() { os_yields++; if (on_yield) on_yield(); return 0; }
KEY
s64 mode = 0;
extern "C" s64 rpcs3ps5_tune(int key) { assert(key == 11); return mode; }
namespace vm { u32 word = 0x101; u32 read32(u32) { return word; } }
u32 get_system_time() { return 123; }
namespace FIFO {
enum { FIFO_EMPTY = 0xDEADF1F0u };
enum class state { running, spinning, empty, nop };
struct register_pair { u32 reg = 0; };
struct table { u32 address = 0x2000; u32 get_addr(u32) const { return address; } };
struct control {
    u32 m_remaining_commands = 0, m_memwatch_addr = 0x1000;
    u32 m_memwatch_cmp = 0x101, m_fifo_pos = 0x1000;
    table mapping;
    table* m_iotable = &mapping;
    bool read_unsafe(register_pair&) { return false; }
    ACCESSOR
    void read_watch(register_pair& data) {
        WATCH
        data.reg = 0; // remaining productive decoder is outside this test
        return;
    }
};
}
struct thread {
    FIFO::control* fifo_ctrl;
    struct { FIFO::state state; u32 FIFO_idle_timestamp = 0; } performance_counters;
    void dispatch_empty() EMPTY
};
int main() {
    FIFO::control control;
    thread reader{&control, {FIFO::state::spinning}};
    // Real watched word remains unchanged: zero preserves the historic call,
    // one gives up the OS timeslice, other values cannot activate the policy.
    for (s64 candidate : {0, 1, -1, 2}) {
        mode = candidate;
        wrapper_yields = os_yields = 0;
        FIFO::register_pair command;
        control.read_watch(command);
        assert(command.reg == FIFO::FIFO_EMPTY && control.is_self_jump_wait());
        reader.dispatch_empty();
#ifdef __PROSPERO__
        assert(os_yields == (candidate == 1));
        assert(wrapper_yields == (candidate != 1));
#else
        assert(os_yields == 0 && wrapper_yields == 1);
#endif
    }
    // Producer patches the command during the yield. No notification required:
    // return to the outer loop and the very next read observes the new word.
    mode = 1;
    on_yield = [] { vm::word = 0x202; };
    reader.dispatch_empty();
    on_yield = {};
    FIFO::register_pair next;
    control.read_watch(next);
    assert(next.reg == 0 && !control.is_self_jump_wait());
    assert(control.m_memwatch_addr == 0 && control.m_memwatch_cmp == 0);
    // Genuine empty queue, stale spinning state, NOP, aborted args, unmapped
    // watch, and changed channel must never select the experimental yield.
    for (int scenario = 0; scenario < 6; scenario++) {
        control.m_memwatch_addr = 0x1000;
        control.m_memwatch_cmp = vm::word;
        control.m_fifo_pos = 0x1000;
        control.m_remaining_commands = 0;
        control.mapping.address = 0x2000;
        reader.performance_counters.state = FIFO::state::spinning;
        if (scenario == 0) control.m_memwatch_addr = 0;
        if (scenario == 1) reader.performance_counters.state = FIFO::state::nop, control.m_memwatch_addr = 0;
        if (scenario == 2) control.m_remaining_commands = 1;
        if (scenario == 3) control.mapping.address = ~0u;
        if (scenario == 4) control.m_fifo_pos += 4;
        if (scenario == 5) vm::word++;
        control.read_watch(next);
        assert(!control.is_self_jump_wait());
        wrapper_yields = os_yields = 0;
        reader.dispatch_empty();
        assert(os_yields == 0 && wrapper_yields == 1);
    }
    // First empty transition retains the original timestamp/state behavior.
    reader.performance_counters.state = FIFO::state::running;
    wrapper_yields = os_yields = 0;
    reader.dispatch_empty();
    assert(reader.performance_counters.state == FIFO::state::empty);
    assert(reader.performance_counters.FIFO_idle_timestamp == 123);
    assert(wrapper_yields == 0 && os_yields == 0);
    std::cout << "PASS: self-jump dispatch, producer update during yield, true-empty fallback, channel/args/unmap guards, idle transition\n";
}
'''.replace('KEY', key).replace('ACCESSOR', accessor).replace('WATCH', watch)
# Substitute the block marker without touching FIFO_EMPTY constants.
program = program.replace('void dispatch_empty() EMPTY', 'void dispatch_empty() ' + empty)
compiler = shutil.which('clang++-19') or shutil.which('c++')
if not compiler:
    raise SystemExit('A host C++ compiler is required')
with tempfile.TemporaryDirectory(prefix='fifo-yield-') as temp:
    root = Path(temp)
    cpp = root / 'test.cpp'
    cpp.write_text(program)
    for ps5 in (False, True):
        binary = root / ('ps5' if ps5 else 'host')
        flags = ['-D__PROSPERO__'] if ps5 else []
        subprocess.run([compiler, '-std=c++20', '-O2', '-Wall', '-Wextra',
                        *flags, str(cpp), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=10)
    # Actual title parser: opt-in only, logging, unchanged other defaults,
    # invalid inputs and deletion restoring control mode.
    title = Path(__file__).resolve().parents[2] / 'app/ps5/src/ps5_tuning.c'
    library = root / 'tuning.so'
    subprocess.run([compiler, '-x', 'c', '-std=c11', '-shared', '-fPIC',
                    f'-DPS5_APP_ROOT="{root}"', str(title), '-o', str(library)], check=True)
    tuning = ctypes.CDLL(str(library))
    tuning.rpcs3ps5_tune.argtypes = [ctypes.c_int]
    tuning.rpcs3ps5_tune.restype = ctypes.c_int64
    tuning.rpcs3ps5_tune_describe.restype = ctypes.c_char_p
    assert tuning.rpcs3ps5_tune(11) == 0
    settings = root / 'rpcs3/ps5-tuning.txt'
    settings.parent.mkdir()
    for index, requested in enumerate((1, 0, -1, 2, 999, 1)):
        settings.write_text(f'rsx_fifo_yield {requested}\n')
        os.utime(settings, (1000 + index, 1000 + index))
        tuning.rpcs3ps5_tune_refresh()
        expected = int(requested == 1)
        assert tuning.rpcs3ps5_tune(11) == expected
        assert f'rsx_fifo_yield={expected}'.encode() in tuning.rpcs3ps5_tune_describe()
        assert tuning.rpcs3ps5_tune(0) == 4000
        assert tuning.rpcs3ps5_tune(5) == 0
        assert tuning.rpcs3ps5_tune(10) == 0
    settings.unlink()
    tuning.rpcs3ps5_tune_refresh()
    assert tuning.rpcs3ps5_tune(11) == 0
    print('PASS: actual tuning parser, key 11, opt-in/default, invalid values, logging and deletion rollback')

    script = Path(__file__).resolve().parents[2] / 'tools/gta4-fifo-yield.py'
    spec = importlib.util.spec_from_file_location('fifo_tuning', script)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    original = b'# keep this\nspu_insert_select 0\nrsx_dma_wait_us 0\n'
    assert helper.variant(original, (1,)) == original + b'rsx_fifo_yield 1\n'
    assert helper.variant(original, (0,)) == original + b'rsx_fifo_yield 0\n'
    assert helper.variant(b'rsx_fifo_yield 0 # comment\n', (1,)) == b'rsx_fifo_yield 1 # comment\n'
    try:
        helper.variant(b'rsx_fifo_yield 0\nrsx_fifo_yield 1\n', (1,))
    except ValueError:
        pass
    else:
        raise AssertionError('duplicate tuning key accepted')
    session = root / 'session'
    session.mkdir()
    for name, values in helper.MODES.items():
        (session / (name + '.txt')).write_bytes(helper.variant(None, values))
    assert helper.require_known(None, session)[0] is None
    try:
        helper.require_known(b'outside change\n', session)
    except RuntimeError:
        pass
    else:
        raise AssertionError('external tuning change accepted')
    print('PASS: reversible tuning variants preserve other keys, reject duplicates and external changes, retain absent original')
