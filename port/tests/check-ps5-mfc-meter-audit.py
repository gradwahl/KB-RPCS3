#!/usr/bin/env python3
"""Audit-only proof of a proposed PUTLLC/PUTLLUC reporting-timer gate.

Uses the actual perf_meter definition with a counted fake TSC. This does not
test the complete reservation protocol or alter emulator/build sources.
"""
from pathlib import Path
import json
import re
import shutil
import subprocess
import sys
import tempfile

upstream = Path(sys.argv[1])
source = (upstream / 'rpcs3/Emu/Cell/SPUThread.cpp').read_text()
meter = (upstream / 'rpcs3/Emu/perf_meter.hpp').read_text()


def body(signature):
    first = source.index(signature)
    brace = source.index('{', first)
    end, depth = brace + 1, 1
    while depth:
        if source[end] == '{':
            depth += 1
        elif source[end] == '}':
            depth -= 1
        end += 1
    return source[first:end]


putllc = body('bool spu_thread::do_putllc(const spu_mfc_cmd& args)')
putlluc = body('void spu_thread::do_putlluc(const spu_mfc_cmd& args)')
assert 'perf_meter<"PUTLLC-"_u64> perf0;' in putllc
assert 'perf_meter<"PUTLLUC"_u64> perf0;' in putlluc
uses = []
for name, function in (('do_putllc', putllc), ('do_putlluc', putlluc)):
    assert not re.search(r'perf[012]\.(get|restart|push)\s*\(', function), name
    uses.extend(f'{name}: {line.strip()}' for line in function.splitlines()
                if re.search(r'\bperf[012]\b', line))

program = r'''
#include <atomic>
#include <cassert>
#include <cstring>
#include <iostream>
#include <vector>
#include "perf_meter.hpp"
std::vector<u64> recorded;
void perf_stat_base::print(const char*) const noexcept {}
void perf_stat_base::push(u64*) noexcept {}
void perf_stat_base::push(u64*, u64 start, const char*) noexcept { recorded.push_back(start); }
void perf_stat_base::add(u64*, const char*) noexcept {}
void perf_stat_base::remove(u64*, const char*) noexcept {}

template<bool Proposed>
void putllc_meter_shape(bool success) {
    perf_meter<1> perf0(0);
    if constexpr (Proposed) {
        if (g_cfg.core.perf_report) perf0.restart();
    } else {
        perf0.restart(); // original default constructor's unconditional read
    }
    perf_meter<2> perf1 = perf0;
    { perf_meter<3> perf2 = perf0; }
    if (success) perf0.reset();
    else perf1.reset();
}
template<bool Proposed>
void putlluc_meter_shape(bool nested, bool success) {
    perf_meter<4> perf0(0);
    if constexpr (Proposed) {
        if (g_cfg.core.perf_report) perf0.restart();
    } else {
        perf0.restart();
    }
    if (nested) putllc_meter_shape<Proposed>(success);
}
int main() {
    for (bool enabled : {false, true})
    for (bool success : {false, true})
    for (bool nested : {false, true}) {
        g_cfg.core.perf_report = enabled;
        utils::reads = 0;
        recorded.clear();
        putllc_meter_shape<false>(success);
        assert(utils::reads == 1);
        const auto baseline = recorded;
        utils::reads = 0;
        recorded.clear();
        putllc_meter_shape<true>(success);
        assert(utils::reads == (enabled ? 1 : 0));
        assert(recorded == baseline);
        utils::reads = 0;
        recorded.clear();
        putlluc_meter_shape<false>(nested, success);
        assert(utils::reads == (nested ? 2 : 1));
        const auto unc_baseline = recorded;
        utils::reads = 0;
        recorded.clear();
        putlluc_meter_shape<true>(nested, success);
        assert(utils::reads == (enabled ? (nested ? 2 : 1) : 0));
        assert(recorded == unc_baseline);
    }
    // Reporting is a dynamic config option. Explicitly document the proposed
    // change: enabling mid-call starts measuring at the NEXT invocation.
    g_cfg.core.perf_report = false;
    recorded.clear();
    { perf_meter<5> original; g_cfg.core.perf_report = true; }
    assert(recorded.size() == 1);
    g_cfg.core.perf_report = false;
    recorded.clear();
    { perf_meter<5> proposed(0);
      if (g_cfg.core.perf_report) proposed.restart();
      g_cfg.core.perf_report = true; }
    assert(recorded.empty());
    std::cout << "PASS: actual perf_meter: disabled reporting eliminates entry TSC reads; fixed enabled reporting retains meter samples for success/failure and nested PUTLLUC shapes; documented mid-call enable skips the in-flight proposed meter\n";
}
'''
compiler = shutil.which('clang++-19') or shutil.which('c++')
if not compiler:
    raise SystemExit('A host C++ compiler is required')
with tempfile.TemporaryDirectory(prefix='mfc-meter-audit-') as temp:
    root = Path(temp)
    (root / 'util').mkdir()
    (root / 'perf_meter.hpp').write_text(meter)
    (root / 'util/types.hpp').write_text('''#pragma once
#include <atomic>
#include <cstddef>
#include <cstdint>
using u64 = std::uint64_t;
using usz = std::size_t;
template<class T> using atomic_t = std::atomic<T>;
#define FORCE_INLINE inline
#define SAFE_BUFFERS(...) __VA_ARGS__
''')
    (root / 'util/logs.hpp').write_text('#pragma once\n#define LOG_CHANNEL(...)\n')
    (root / 'util/tsc.hpp').write_text('''#pragma once
#include <cstdint>
namespace utils { inline std::uint64_t reads = 0;
inline std::uint64_t get_tsc() { return ++reads * 100; } }
''')
    (root / 'system_config.h').write_text('''#pragma once
struct config { struct core_config { bool perf_report = false; } core; };
inline config g_cfg;
''')
    cpp, binary = root / 'test.cpp', root / 'test'
    cpp.write_text(program)
    subprocess.run([compiler, '-std=c++20', '-O2', '-Wall', '-Wextra',
                    '-I', str(root), str(cpp), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print(json.dumps({'audit': 'reporting-only perf variable uses', 'source_uses': uses,
                  'production_sources_modified': False,
                  'limitation': 'Construction/reporting proof only; no PS5 FPS or full reservation equivalence result'}, indent=2))
