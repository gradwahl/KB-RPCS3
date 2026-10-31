#!/usr/bin/env python3
"""Prepare patch0074: PS5 release-monitoring gate, preserve all dirty sources."""
from pathlib import Path
import hashlib,difflib,json
repo=Path("/mnt/c/Users/Callum/Documents/GitHub/PS5 RPCS3/KB-RPCS3")
src=Path("/home/callum/work/rpcs3-latest")
arch=Path("/home/callum/work/cpu-plan-release-profile0074-original-20261031")
patch=repo/"port/rpcs3-latest-patches/0074-PS5-default-off-production-CPU-profiling.patch"
files=[
"rpcs3/ps5/ps5_frontend.cpp",
"Utilities/Thread.cpp",
"rpcs3/Emu/RSX/ps5_rsx_words.h",
"rpcs3/Emu/RSX/ps5_worker_activity.h",
"rpcs3/Emu/Cell/ps5_spu_reswait.h",
"rpcs3/Emu/Cell/ps5_spu_wakeup.h",
"rpcs3/Emu/Cell/SPULLVMRecompiler.cpp",
"rpcs3/ps5/ps5_release_profile.h"]
assert not arch.exists() and not patch.exists() and not (src/files[-1]).exists()
old={f:(src/f).read_text() for f in files[:-1]}
new=dict(old)

header='''#pragma once
// CPU optimisation plan Section 5: DEFAULT-OFF production CPU diagnostics.
// 0 = no SIGUSR1 CPU monitoring, no per-frame RSX histograms, no
// reservation-wait/wakeup/worker-activity probes, no SPU JIT profiler
// registration, and no high-frequency diagnostic watchdog reporting.
// 1 = retain existing opt-in diagnostic facilities (including independent
// PS5_SPU_HOTJIT_ACTIVE and RSX profiler mode switches).
//
// This controls diagnostic code only: it MUST NOT change real host native
// TLS, PPU/SPU JIT execution, guest sync, application watchdog's SIGUSR2,
// heartbeat timeout, or PS5 tuning file refresh.
#ifndef PS5_RELEASE_PROFILE_ACTIVE
#define PS5_RELEASE_PROFILE_ACTIVE 0
#endif
#if PS5_RELEASE_PROFILE_ACTIVE != 0 && PS5_RELEASE_PROFILE_ACTIVE != 1
#error PS5_RELEASE_PROFILE_ACTIVE must be 0 or 1
#endif
'''
new[files[-1]]=header

def replace(path,needle,replacement,count=1):
 s=new[path]
 assert s.count(needle)==count,(path,needle[:140],s.count(needle))
 new[path]=s.replace(needle,replacement,count)

# Logging and CPU SIGUSR1 profiler remain linked but completely uncalled
# by normal builds, avoiding registration, signal snapshot and JIT map work.
f="Utilities/Thread.cpp"
replace(f,'#include "rpcs3/ps5/ps5_cpu_groups.h"', '#include "rpcs3/ps5/ps5_cpu_groups.h"\n#include "rpcs3/ps5/ps5_release_profile.h"')
replace(f,'#ifdef __PROSPERO__\n\tps5_cpu_register(this, &m_tname);\n#endif',
  '#if defined(__PROSPERO__) && PS5_RELEASE_PROFILE_ACTIVE\n\tps5_cpu_register(this, &m_tname);\n#endif')
replace(f,'u64 thread_base::finalize(thread_state result_state) noexcept\n{\n#ifdef __PROSPERO__',
  'u64 thread_base::finalize(thread_state result_state) noexcept\n{\n#if defined(__PROSPERO__) && PS5_RELEASE_PROFILE_ACTIVE')

# PS5 watchdog remains fully present; release branch keeps tuning
# reload (including hot RSX spin knobs), while detailed reports are gated.
f="rpcs3/ps5/ps5_frontend.cpp"
replace(f,'#include "ps5_cpu_topology.h"\n','#include "ps5_cpu_topology.h"\n#include "ps5_release_profile.h"\n#if !PS5_RELEASE_PROFILE_ACTIVE && PS5_SPU_HOTJIT_ACTIVE\n#error SPU hot JIT profiler needs PS5_RELEASE_PROFILE_ACTIVE=1\n#endif\n')
replace(f,"\t\tps5_thread_cpu_report(1, 0); // start the CPU monitor's window",
  "#if PS5_RELEASE_PROFILE_ACTIVE\n\t\tps5_thread_cpu_report(1, 0); // start the CPU monitor's window\n#endif")
replace(f,
  '\t\t\tif (now - last_cpu >= 4000)\n\t\t\t{\n',
  '\t\t\tif (now - last_cpu >= 4000)\n\t\t\t{\n#if PS5_RELEASE_PROFILE_ACTIVE\n')
needle='''#endif
\t\t\t\tlast_cpu = now_ms();
\t\t\t}
\t\t\tif (now - g_main_heartbeat > 20000'''
replacement='''#endif
#else
                // Preserve live tuning refresh without CPU signals,
                // sample snapshots, high-volume frame logging or any
                // guest JIT/RSX trace drains in normal gameplay.
                rpcs3ps5_tune_refresh();
                static std::string previous_tuning = rpcs3ps5_tune_describe();
                const std::string current_tuning = rpcs3ps5_tune_describe();
                if (previous_tuning != current_tuning)
                {
                    previous_tuning = current_tuning;
                    sys_log.notice("PS5 TUNING: %s", current_tuning);
                }
                // The experimental spu_hot_cpu scheduler relies on CPU
                // SIGUSR1 samples. Do not silently pretend it can run.
                static bool warned_hot_cpu = false;
                if (!warned_hot_cpu && rpcs3ps5_tune(7) >= 0)
                {
                    warned_hot_cpu = true;
                    sys_log.warning("PS5 HOTCPU requires an explicit diagnostics-enabled build; no CPU affinity changed");
                }
#endif
\t\t\t\tlast_cpu = now_ms();
\t\t\t}
\t\t\tif (now - g_main_heartbeat > 20000'''
replace(f,needle,replacement)

# Avoid maintaining a per-JIT function map on every SPU LLVM compile
# while normal release monitoring is OFF.
f="rpcs3/Emu/Cell/SPULLVMRecompiler.cpp"
replace(f,'#include "Emu/RSX/ps5_worker_activity.h"',
          '#include "Emu/RSX/ps5_worker_activity.h"\n#include "rpcs3/ps5/ps5_release_profile.h"')
replace(f,
  '''#ifdef __PROSPERO__
\t\t// The profiler names samples in this code after the SPU function (Utilities/Thread.cpp)
\t\tps5_jit_name(reinterpret_cast<u64>(fn), fmt::format("spu-%05x-%s", func.entry_point, m_hash));
#endif''',
  '''#if defined(__PROSPERO__) && PS5_RELEASE_PROFILE_ACTIVE
\t\t// Diagnostic JIT name registry only. Never lock/map/allocate
\t\t// here when normal release sampling is OFF.
\t\tps5_jit_name(reinterpret_cast<u64>(fn), fmt::format("spu-%05x-%s", func.entry_point, m_hash));
#endif''')

# Original patch0065/0066 toggles were ON; change to the common
# release diagnostics gate while preserving explicit overrides.
f="rpcs3/Emu/RSX/ps5_rsx_words.h"
replace(f,'#include <array>\n','#include <array>\n#include "rpcs3/ps5/ps5_release_profile.h"\n')
replace(f,'#define PS5_RSX_WORDS_ACTIVE 1','#define PS5_RSX_WORDS_ACTIVE PS5_RELEASE_PROFILE_ACTIVE')
replace(f,'#define PS5_RSX_CLASS_ACTIVE 1','#define PS5_RSX_CLASS_ACTIVE PS5_RELEASE_PROFILE_ACTIVE')

# SPU reservation scoped timer: no counters, TLS phase or clock calls
# when OFF. Scope object may still be constructed, but compiler
# optimises the empty constructor/destructor.
f="rpcs3/Emu/Cell/ps5_spu_reswait.h"
replace(f,'#include <ctime>\n','#include <ctime>\n#include "rpcs3/ps5/ps5_release_profile.h"\n')
replace(f,'''        {
            // Per-thread first call and every 128th call.''',
  '''        {
            if constexpr (!PS5_RELEASE_PROFILE_ACTIVE) return;
            // Per-thread first call and every 128th call.''')
replace(f,'''        ~scope() noexcept
        {
            if (!m_sampled)''',
  '''        ~scope() noexcept
        {
            if constexpr (!PS5_RELEASE_PROFILE_ACTIVE) return;
            if (!m_sampled)''')

# SPU reservation-page diagnostic: no TLS sampling increments in
# guests and no per-page atomic table accesses when release OFF.
f="rpcs3/Emu/Cell/ps5_spu_wakeup.h"
replace(f,'#include <cstdint>\n','#include <cstdint>\n#include "rpcs3/ps5/ps5_release_profile.h"\n')
replace(f,'''        {
            static thread_local std::uint32_t phase=0;
            enabled=((phase++ & (sample_every-1))==0);''',
  '''        {
            if constexpr (!PS5_RELEASE_PROFILE_ACTIVE) return;
            static thread_local std::uint32_t phase=0;
            enabled=((phase++ & (sample_every-1))==0);''')
replace(f,'''    inline bool sample_notification() noexcept
    {
        static thread_local std::uint32_t phase=0;''',
  '''    inline bool sample_notification() noexcept
    {
        if constexpr (!PS5_RELEASE_PROFILE_ACTIVE) return false;
        static thread_local std::uint32_t phase=0;''')
replace(f,'''    inline void note_notification(std::uint32_t addr,producer from) noexcept
    {
        producer_samples.fetch_add''',
  '''    inline void note_notification(std::uint32_t addr,producer from) noexcept
    {
        if constexpr (!PS5_RELEASE_PROFILE_ACTIVE) return;
        producer_samples.fetch_add''')
# No-op on OFF even if some code still calls a helper directly.
replace(f,'''    inline slot* get_slot(std::uint32_t addr) noexcept
    {
        // Use real full''',
  '''    inline slot* get_slot(std::uint32_t addr) noexcept
    {
        if constexpr (!PS5_RELEASE_PROFILE_ACTIVE) return nullptr;
        // Use real full''')

# Instrumentation-only worker slot must be nullptr in release, so
# existing callers' null guard skips gateway/CPU work probes. Some
# lower-level record_rsx is called without a null slot.
f="rpcs3/Emu/RSX/ps5_worker_activity.h"
replace(f,'#include "util/tsc.hpp"\n','#include "util/tsc.hpp"\n#include "rpcs3/ps5/ps5_release_profile.h"\n')
replace(f,'''    inline worker_slot* register_spu(std::uint32_t id) noexcept
    {
        if (!id)''',
  '''    inline worker_slot* register_spu(std::uint32_t id) noexcept
    {
        if constexpr (!PS5_RELEASE_PROFILE_ACTIVE) return nullptr;
        if (!id)''')
replace(f,'''    inline cpu_work_probe begin_cpu_work(std::uint32_t id) noexcept
    {
        if (!id)''',
  '''    inline cpu_work_probe begin_cpu_work(std::uint32_t id) noexcept
    {
        if constexpr (!PS5_RELEASE_PROFILE_ACTIVE) return {};
        if (!id)''')
replace(f,'''    inline void record_rsx(stage kind, std::uint64_t start) noexcept
    {
        auto end = utils::get_tsc();''',
  '''    inline void record_rsx(stage kind, std::uint64_t start) noexcept
    {
        if constexpr (!PS5_RELEASE_PROFILE_ACTIVE) return;
        auto end = utils::get_tsc();''')
replace(f,'''    inline helper_probe begin_helper(std::uint32_t id, helper_kind kind, unsigned arg) noexcept
    {
        if constexpr (!PS5_SPU_HELPER_ACTIVE) return {};''',
  '''    inline helper_probe begin_helper(std::uint32_t id, helper_kind kind, unsigned arg) noexcept
    {
        if constexpr (!PS5_RELEASE_PROFILE_ACTIVE || !PS5_SPU_HELPER_ACTIVE) return {};''')

arch.mkdir()
for path,s in old.items():
  dest=arch/path
  dest.parent.mkdir(parents=True,exist_ok=True)
  dest.write_text(s)
for path,s in new.items():
  dest=src/path
  dest.parent.mkdir(parents=True,exist_ok=True)
  dest.write_text(s)
diff=[]
for f in files:
 a=old.get(f,"")
 b=new[f]
 diff.append(f'diff --git a/{f} b/{f}\n')
 if not a:diff.append('new file mode 100644\n')
 diff.extend(difflib.unified_diff(a.splitlines(keepends=True),b.splitlines(keepends=True),
  fromfile='a/'+f if a else '/dev/null',tofile='b/'+f,n=4))
patch.write_text('''From 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001
From: KB <kb@kb-rpcs3.example>
Date: Sat, 31 Oct 2026 04:49:00 +0000
Subject: [PATCH] PS5: disable production CPU instrumentation by default

Keep watchdog SIGUSR2/heartbeats and tuning hot-reload active.
Default-off diagnostic mode disables per-thread SIGUSR1 CPU snapshots,
RSX histogram counters, SPU reservation/wakeup/worker samples, and
per-JIT function-name map allocations; opt-in retains all facilities.
No changes to native TLS flags, guest memory or JIT machine code.
---
'''+''.join(diff))
(arch/"manifest.json").write_text(json.dumps({
 "patch":74,"files":files,
 "before":{p:hashlib.sha256(s.encode()).hexdigest() for p,s in old.items()},
 "after":{p:hashlib.sha256(s.encode()).hexdigest() for p,s in new.items()}
},indent=2)+"\n")
print("PASS wrote patch0074",patch,patch.stat().st_size,"files",len(files))
