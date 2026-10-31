#!/usr/bin/env python3
"""Compile actual timer constructor blocks; prove guest function text unchanged."""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

upstream, before = Path(sys.argv[1]), Path(sys.argv[2])
source = (upstream / 'rpcs3/Emu/Cell/SPUThread.cpp').read_text()
baseline = (before / 'rpcs3/Emu/Cell/SPUThread.cpp').read_text()
blocks = []
restored = source.replace('#include "ps5_mfc_meter.h"\n', '', 1)
for name in ('PUTLLC-', 'PUTLLUC'):
    block = f'''#if defined(__PROSPERO__) && PS5_MFC_METER_GATE
\t// Reporting-only timer. Enable at entry; leave GETLLAR timers untouched.
\tperf_meter<"{name}"_u64> perf0(0);
\tif (g_cfg.core.perf_report)
\t\tperf0.restart();
#else
\tperf_meter<"{name}"_u64> perf0;
#endif'''
    assert source.count(block) == 1, name
    assert 'if (g_cfg.core.perf_report)\n\t\tperf0.restart();' in block
    assert f'#else\n\tperf_meter<"{name}"_u64> perf0;' in block
    blocks.append(block)
    restored = restored.replace(block, f'\tperf_meter<"{name}"_u64> perf0;', 1)
assert restored == baseline, 'Other SPUThread/guest protocol statements changed'

program = r'''
#include <atomic>
#include <cassert>
#include <cstring>
#include <iostream>
#include <string>
#include <utility>
#include <vector>
#include "perf_meter.hpp"
#include "ps5_mfc_meter.h"
constexpr u64 operator""_u64(const char* text, std::size_t count) {
    u64 value = 0;
    for (std::size_t i=0; i<count; ++i) value |= u64(static_cast<unsigned char>(text[i])) << (i*8);
    return value;
}
std::vector<std::pair<std::string,u64>> recorded;
void perf_stat_base::print(const char*) const noexcept {}
void perf_stat_base::push(u64*) noexcept {}
void perf_stat_base::push(u64*,u64 stamp,const char* name) noexcept { recorded.emplace_back(name,stamp); }
void perf_stat_base::add(u64*,const char*) noexcept {}
void perf_stat_base::remove(u64*,const char*) noexcept {}
void conditional(bool success) {
BLOCK_C
    perf_meter<"PUTLLC+"_u64> perf1 = perf0;
    { perf_meter<"PUTLLC."_u64> perf2 = perf0; }
    if (success) perf0.reset(); else perf1.reset();
}
void unconditional(bool nested,bool success) {
BLOCK_U
    if (nested) conditional(success);
}
int main() {
#if defined(__PROSPERO__) && PS5_MFC_METER_GATE
    constexpr bool gated = true;
#else
    constexpr bool gated = false;
#endif
    for (bool enabled : {false,true})
    for (bool success : {false,true})
    for (bool nested : {false,true}) {
        g_cfg.core.perf_report = enabled;
        utils::reads=0; recorded.clear();
        conditional(success);
        assert(utils::reads == (enabled || !gated ? 1 : 0));
        if (enabled) {
            assert(recorded.size()==2);
            assert(recorded[0].first=="PUTLLC." && recorded[0].second==100);
            assert(recorded[1].first==(success?"PUTLLC+":"PUTLLC-") && recorded[1].second==100);
        } else assert(recorded.empty());
        utils::reads=0; recorded.clear();
        unconditional(nested,success);
        assert(utils::reads == (enabled || !gated ? (nested?2:1) : 0));
        if (enabled) {
            assert(recorded.size()==(nested?3:1));
            if (nested) {
                assert(recorded[0].first=="PUTLLC." && recorded[0].second==200);
                assert(recorded[1].first==(success?"PUTLLC+":"PUTLLC-") && recorded[1].second==200);
            }
            assert(recorded.back().first=="PUTLLUC" && recorded.back().second==100);
        } else assert(recorded.empty());
    }
    std::cout << "PASS: actual constructor blocks, gate=" << gated << ", TSC counts, named report events, success/failure and nested PUTLLUC\n";
}
'''.replace('BLOCK_C', blocks[0]).replace('BLOCK_U', blocks[1])
compiler = shutil.which('clang++-19') or shutil.which('c++')
if not compiler:
    raise SystemExit('Host C++ compiler required')
with tempfile.TemporaryDirectory(prefix='mfc-meter-') as temp:
    root = Path(temp)
    (root / 'util').mkdir()
    (root / 'perf_meter.hpp').write_text((upstream/'rpcs3/Emu/perf_meter.hpp').read_text())
    (root / 'ps5_mfc_meter.h').write_text((upstream/'rpcs3/Emu/Cell/ps5_mfc_meter.h').read_text())
    (root / 'util/types.hpp').write_text('''#pragma once
#include <atomic>
#include <cstddef>
#include <cstdint>
using u64=std::uint64_t; using usz=std::size_t;
template<class T> using atomic_t=std::atomic<T>;
#define FORCE_INLINE inline
#define SAFE_BUFFERS(...) __VA_ARGS__
''')
    (root / 'util/logs.hpp').write_text('#pragma once\n#define LOG_CHANNEL(...)\n')
    (root / 'util/tsc.hpp').write_text('''#pragma once
#include <cstdint>
namespace utils { inline std::uint64_t reads=0;
inline std::uint64_t get_tsc() { return ++reads*100; } }
''')
    (root / 'system_config.h').write_text('''#pragma once
struct config { struct core_config { bool perf_report=false; } core; };
inline config g_cfg;
''')
    cpp=root/'test.cpp';cpp.write_text(program)
    for label, flags in (('control',['-D__PROSPERO__','-DPS5_MFC_METER_GATE=0']),
                         ('candidate',['-D__PROSPERO__','-DPS5_MFC_METER_GATE=1']),
                         ('nonps5',['-DPS5_MFC_METER_GATE=1'])):
        binary=root/label
        subprocess.run([compiler,'-std=c++20','-O2','-Wall','-Wextra',*flags,
                        '-I',str(root),str(cpp),'-o',str(binary)],check=True)
        subprocess.run([str(binary)],check=True)
print('PASS: complete SPUThread source matches pre-change after removing only include/two constructor gates; GETLLAR/protocol text unchanged')
