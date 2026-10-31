#!/usr/bin/env python3
"""Prepare isolated patch0070, anchored to existing dirty WSL source."""
from pathlib import Path
import difflib, json, hashlib
repo=Path('/mnt/c/Users/Callum/Documents/GitHub/PS5 RPCS3/KB-RPCS3')
src=Path('/home/callum/work/rpcs3-latest')
originals=Path('/home/callum/work/cpu-plan-hotjit0070-original-20261031')
patch=repo/'port/rpcs3-latest-patches/0070-PS5-opt-in-SPU-JIT-hot-function-sampler.patch'
files=('Utilities/Thread.cpp','rpcs3/ps5/ps5_frontend.cpp','rpcs3/ps5/ps5_spu_hotjit.h')
assert not originals.exists() and not patch.exists() and not (src/files[-1]).exists()
orig={p:(src/p).read_text() for p in files[:-1]}
header=r'''#pragma once
// KB general CPU optimization plan, Section 1.
// Opt-in per-worker SPU JIT address sampling; never enabled for a
// normal build.  Enable only for diagnostic images via compiler
// -DPS5_SPU_HOTJIT_ACTIVE=1, and keep PS5_RSX_PERF_ACTIVE=0.
// Uses existing SIGUSR1/ucontext sampler, no new signal handler,
// guest dispatch modifications, or guest memory reads.
#ifndef PS5_SPU_HOTJIT_ACTIVE
#define PS5_SPU_HOTJIT_ACTIVE 0
#endif
#if PS5_SPU_HOTJIT_ACTIVE != 0 && PS5_SPU_HOTJIT_ACTIVE != 1
#error PS5_SPU_HOTJIT_ACTIVE must be 0 or 1
#endif
'''
f=orig[files[1]]
needle='#include "Emu/Cell/ps5_spu_wakeup.h"\n'
assert f.count(needle)==1,("front include",f.count(needle))
f=f.replace(needle,needle+'#include "ps5_spu_hotjit.h"\n',1)
old='''                if (PS5_RSX_PERF_ACTIVE && ++cpu_reports % 2 == 0)
                {
                    // Every 5th slot is the RSX thread explicitly (affinity/contention experiment); the rest
                    // are the busiest threads.
                    const u64 slot = (cpu_reports / 2) % 5;
                    const std::string name = slot == 4 ? std::string("rsx::thread") : ps5_thread_top_name(slot);
                    if (!name.empty())
                        sys_log.notice("PS5 PROFILE %s: %s", name, ps5_thread_profile(name, 400));
                }'''
old=old.replace("    ","\t")
assert f.count(old)==1,("frontend profile",f.count(old))
new='''                // Normal release: profiling OFF. The existing RSX profiler is
                // unchanged; SPU hot-function sampling has an independent
                // compile-time gate (diagnostic builds only, never both).
                ++cpu_reports;
                if (PS5_RSX_PERF_ACTIVE && cpu_reports % 2 == 0)
                {
                    const u64 slot = (cpu_reports / 2) % 5;
                    const std::string name = slot == 4 ? std::string("rsx::thread") : ps5_thread_top_name(slot);
                    if (!name.empty())
                        sys_log.notice("PS5 PROFILE %s: %s", name, ps5_thread_profile(name, 400, true));
                }
#if PS5_SPU_HOTJIT_ACTIVE
                if (!PS5_RSX_PERF_ACTIVE && cpu_reports % 2 == 0)
                {
                    // Rotate among the busiest registered SPU execution
                    // workers; excludes "SPU Worker" compile pool and PPU/RSX.
                    // The legacy profiler is a *candidate range* lookup:
                    // names describe the nearest preceding registered JIT
                    // entry, not proven bounded symbol extents.
                    std::array<std::string, 6> choices{};
                    usz spu_count = 0;
                    for (usz j = 0; j < choices.size(); ++j)
                    {
                        auto name = ps5_thread_top_name(j);
                        if (name.rfind("SPU[", 0) == 0)
                            choices[spu_count++] = std::move(name);
                    }
                    static usz turn = 0;
                    if (spu_count)
                    {
                        const auto& target = choices[turn++ % spu_count];
                        // 200 samples spaced 5ms over ~1 second, every
                        // other watchdog window. No JIT dump is written;
                        // use the ranked hashes for separate, bounded
                        // *explicitly authorized* real LLVM22 code dumps.
                        sys_log.notice("PS5 SPU HOTJIT: %s %s", target,
                            ps5_thread_profile(target, 200, false));
                    }
                    else
                    {
                        sys_log.notice("PS5 SPU HOTJIT: no active SPU execution thread");
                    }
                }
#endif'''
new=new.replace("    ","\t")
f=f.replace(old,new,1)
assert f.count('std::string ps5_thread_profile(const std::string& name, usz count);')==1
f=f.replace('std::string ps5_thread_profile(const std::string& name, usz count);','std::string ps5_thread_profile(const std::string& name, usz count, bool dump_jit);',1)
t=orig[files[0]]
old='std::string ps5_thread_profile(const std::string& name, usz count)'
assert t.count(old)==1
t=t.replace(old,'std::string ps5_thread_profile(const std::string& name, usz count, bool dump_jit)',1)
old='''\t\t\t\t// Enough code to cover every sampled offset, plus a margin
\t\t\t\tps5_jit_save(funcs[i].second, func_start[funcs[i].second], std::min<u64>(furthest + 0x2000, 0x40000));'''
assert t.count(old)==1
t=t.replace(old,'''                // The old RSX diagnostic may still request dump files.
                // The general SPU HOTJIT sampler deliberately NEVER
                // writes unbounded readbacks from executable JIT memory.
                // A hash + PC sample is NOT an exact code-size bound.
                if (dump_jit)
                    ps5_jit_save(funcs[i].second, func_start[funcs[i].second], std::min<u64>(furthest + 0x2000, 0x40000));''',1)
upd={files[0]:t,files[1]:f,files[2]:header}
originals.mkdir()
for p,content in orig.items():
 (originals/Path(p).name).write_text(content)
 (src/p).write_text(upd[p])
(src/files[2]).write_text(header)
changes=[]
for p in files:
 a=orig.get(p,'')
 changes.append(f'diff --git a/{p} b/{p}\n')
 if not a:changes.append('new file mode 100644\n')
 changes.extend(difflib.unified_diff(a.splitlines(keepends=True),upd[p].splitlines(keepends=True),
 fromfile='a/'+p if a else '/dev/null',tofile='b/'+p,n=4))
patch.write_text('''From 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001
From: KB <kb@kb-rpcs3.example>
Date: Sat, 31 Oct 2026 03:12:00 +0000
Subject: [PATCH] PS5: opt-in SPU-only JIT function sampler, no auto code dumps

Separately gate general CPU plan profiling from the RSX performance mode.
Sample just registered SPU execution workers using existing SIGUSR1
sampler at controlled cadence, rotate workers, emit JIT hash/offset
candidate rankings, and prevent automatic unbounded JIT .bin dump.
Normal builds keep the feature completely disabled.
---
'''+''.join(changes))
(originals/'manifest.json').write_text(json.dumps({
'patch':70,'names':list(files),
'before':{p:hashlib.sha256(v.encode()).hexdigest() for p,v in orig.items()},
'after':{p:hashlib.sha256(v.encode()).hexdigest() for p,v in upd.items()}},indent=2)+'\n')
print('PASS created source patch0070:',patch,'bytes',patch.stat().st_size)
