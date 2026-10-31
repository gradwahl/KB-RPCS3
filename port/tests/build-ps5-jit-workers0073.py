#!/usr/bin/env python3
"""Create isolated patch0073 in already-modified WSL source, preserving originals."""
from pathlib import Path
import difflib,hashlib,json
repo=Path('/mnt/c/Users/Callum/Documents/GitHub/PS5 RPCS3/KB-RPCS3')
src=Path('/home/callum/work/rpcs3-latest')
arc=Path('/home/callum/work/cpu-plan-jit-workers0073-original-20261031')
patch=repo/'port/rpcs3-latest-patches/0073-PS5-opt-in-cap-live-SPU-LLVM-compile-workers.patch'
cpp='rpcs3/Emu/Cell/SPUCommonRecompiler.cpp'
head='rpcs3/Emu/Cell/ps5_spu_live_compile_workers.h'
assert not arc.exists() and not patch.exists() and not (src/head).exists()
a=(src/cpp).read_text()
header='''#pragma once
// Section 4: isolated opt-in live SPU LLVM compilation contention A/B.
// 0 = unmodified runtime worker count, normal shipping default.
// 1..32 = cap ONLY the SPUW. runtime-recompiler worker pool.
// Initial SPU cache precompilation, PPU compilation, cache names and
// cache contents remain unchanged. A lower limit may delay live JIT!
// Do not enable by default without independent warm/cold frame-time
// and CPU-occupancy tests.  This cap is NOT an adaptive scheduler.
#ifndef PS5_SPU_LIVE_JIT_WORKER_CAP
#define PS5_SPU_LIVE_JIT_WORKER_CAP 0
#endif
#if PS5_SPU_LIVE_JIT_WORKER_CAP < 0 || PS5_SPU_LIVE_JIT_WORKER_CAP > 32
#error PS5_SPU_LIVE_JIT_WORKER_CAP must be in range 0..32
#endif

namespace ps5_spu_live_workers
{
    constexpr unsigned limit(unsigned normal)
    {
#if PS5_SPU_LIVE_JIT_WORKER_CAP
        return normal < PS5_SPU_LIVE_JIT_WORKER_CAP ?
            normal : PS5_SPU_LIVE_JIT_WORKER_CAP;
#else
        return normal;
#endif
    }
}
'''
include='#include "SPUDisAsm.h"\n'
assert a.count(include)==1
b=a.replace(include,include+'#ifdef __PROSPERO__\n#include "ps5_spu_live_compile_workers.h"\n#endif\n',1)
needle='''\t\telse if (hc >= 6)
\t\t{
\t\t\tworker_count = 2;
\t\t}

\t\tu32 worker_index = 0;'''
assert b.count(needle)==1
replacement='''\t\telse if (hc >= 6)
\t\t{
\t\t\tworker_count = 2;
\t\t}

#if defined(__PROSPERO__) && PS5_SPU_LIVE_JIT_WORKER_CAP
\t\t// This is the *live* SPUW. worker pool only. Don't conflate it
\t\t// with the boot-time SPU Worker precompiler or PPU LLVM threads.
\t\t// Preserve at least one worker, preventing queue stranding.
\t\tconst u32 original_worker_count = worker_count;
\t\tworker_count = ps5_spu_live_workers::limit(worker_count);
\t\tspu_log.notice("PS5 SPU LIVE JIT: workers %u (normal %u, diagnostic cap %u)",
\t\t\tworker_count, original_worker_count,
\t\t\tstatic_cast<unsigned>(PS5_SPU_LIVE_JIT_WORKER_CAP));
#endif

\t\tu32 worker_index = 0;'''
b=b.replace(needle,replacement,1)
arc.mkdir()
(arc/'SPUCommonRecompiler.cpp').write_text(a)
(src/cpp).write_text(b)
(src/head).write_text(header)
diff=[]
for path,old,new in [(cpp,a,b),(head,'',header)]:
 diff.append(f'diff --git a/{path} b/{path}\n')
 if not old:diff.append('new file mode 100644\n')
 diff.extend(difflib.unified_diff(old.splitlines(keepends=True),new.splitlines(keepends=True),
 fromfile='a/'+path if old else '/dev/null',tofile='b/'+path,n=4))
patch.write_text('''From 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001
From: KB <kb@kb-rpcs3.example>
Date: Sat, 31 Oct 2026 04:32:45 +0000
Subject: [PATCH] PS5: optional limit for live SPU LLVM JIT workers only

Keep PPU LLVM, shader and SPU boot-cache compilation unchanged.
Normal runtime worker calculation unchanged with default cap=0.
Diagnostic cap allows direct warm-gameplay 4 vs 2 comparison
without changing cache keys or guest semantics. This is not
automatic throttling and must remain off until real A/B/A gates.
---
'''+''.join(diff))
(arc/'manifest.json').write_text(json.dumps({
'patch':73,'before':{cpp:hashlib.sha256(a.encode()).hexdigest()},
'after':{cpp:hashlib.sha256(b.encode()).hexdigest(),head:hashlib.sha256(header.encode()).hexdigest()}},indent=2)+'\n')
print('PASS created patch0073',patch,patch.stat().st_size)
