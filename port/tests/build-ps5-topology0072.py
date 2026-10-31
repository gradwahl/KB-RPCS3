#!/usr/bin/env python3
"""Prepare reversible patch0072: opt-in one-shot PS5 topology probe.

No change to scheduling masks; only the watchdog's own affinity is
temporarily changed in an explicit diagnostic build and restored.
"""
from pathlib import Path
import hashlib,difflib,json
repo=Path('/mnt/c/Users/Callum/Documents/GitHub/PS5 RPCS3/KB-RPCS3')
src=Path('/home/callum/work/rpcs3-latest')
arc=Path('/home/callum/work/cpu-plan-topology0072-original-20261031')
patch=repo/'port/rpcs3-latest-patches/0072-PS5-opt-in-CPU-topology-and-affinity-readback.patch'
names=['rpcs3/ps5/ps5_frontend.cpp','rpcs3/ps5/ps5_cpu_topology.h']
assert not arc.exists() and not patch.exists() and not (src/names[-1]).exists()
original=(src/names[0]).read_text()
header=r'''#pragma once
// CPU optimisation plan §3: one-shot explicit-ON physical SMT observation.
// Default OFF: no affinity calls, CPUID or logging in normal builds.
// Run on WATCHDOG's own host thread; NEVER change SPU/PPU/RSX workers.
#ifndef PS5_CPU_TOPOLOGY_PROBE
#define PS5_CPU_TOPOLOGY_PROBE 0
#endif
#if PS5_CPU_TOPOLOGY_PROBE != 0 && PS5_CPU_TOPOLOGY_PROBE != 1
#error PS5_CPU_TOPOLOGY_PROBE must be 0 or 1
#endif

#if PS5_CPU_TOPOLOGY_PROBE
#include <pthread.h>
#include <sched.h>
#include <cpuid.h>
#include <cstdint>

namespace ps5_cpu_topology
{
    struct sample
    {
        unsigned cpu;
        int set_rc, get_rc;
        std::uint64_t observed_mask;
        unsigned apic_id, core_id, node_id, advertised_threads;
        bool cpuid_valid;
    };
    struct result
    {
        std::uint64_t original_mask;
        bool has_amd_core_leaf;
        int initial_read_rc, restore_rc;
        unsigned attempts, succeeded;
        bool truncated_cpu_set;
    };
    template<class Sink>
    result probe(Sink&& sink)
    {
        result r{};
        cpu_set_t saved;
        CPU_ZERO(&saved);
        const pthread_t current = pthread_self();
        r.initial_read_rc = pthread_getaffinity_np(current, sizeof(cpu_set_t), &saved);
        if (r.initial_read_rc)
            return r;

        // Extended AMD topology CPUID leaf 0x8000001E: APIC ID in EAX;
        // core ID and threads-per-core in EBX; node ID in ECX.
        // On other CPUs/no leaf: report UNKNOWN, never infer pairs.
        unsigned a=0,b=0,c=0,d=0;
        __cpuid(0,a,b,c,d);
        const bool amd = b==0x68747541u && d==0x69746e65u && c==0x444d4163u;
        __cpuid(0x80000000u,a,b,c,d);
        r.has_amd_core_leaf = amd && a >= 0x8000001eu;

        for (unsigned i=0; i<64; ++i)
            if (CPU_ISSET(i, &saved))
                r.original_mask |= (std::uint64_t{1} << i);
        // If the OS exposes any CPU outside the 64-bit process affinity
        // mask, avoid trusting this partial sample as exhaustive.
        for (unsigned i=64; i<CPU_SETSIZE; ++i)
            if (CPU_ISSET(i, &saved))
                r.truncated_cpu_set = true;
        for (unsigned cpu=0; cpu<64; ++cpu)
        {
            if (!(r.original_mask & (std::uint64_t{1} << cpu)))
                continue;
            sample s{};
            s.cpu=cpu;
            cpu_set_t single;
            CPU_ZERO(&single);
            CPU_SET(cpu, &single);
            ++r.attempts;
            s.set_rc=pthread_setaffinity_np(current, sizeof(single), &single);
            if (!s.set_rc)
            {
                cpu_set_t observed;
                CPU_ZERO(&observed);
                s.get_rc=pthread_getaffinity_np(current, sizeof(observed), &observed);
                if (!s.get_rc)
                    for (unsigned i=0;i<64;++i)
                        if (CPU_ISSET(i,&observed))
                            s.observed_mask |= std::uint64_t{1}<<i;
                // CPUID applies to the CURRENT physical core only after
                // the kernel verifies we are pinned to precisely one CPU.
                if (!s.get_rc &&
                    s.observed_mask == (std::uint64_t{1} << cpu) &&
                    r.has_amd_core_leaf)
                {
                    __cpuid_count(0x8000001eu,0,a,b,c,d);
                    s.apic_id=a;
                    s.core_id=b&255u;
                    s.advertised_threads=((b>>8)&255u)+1u;
                    s.node_id=c&255u;
                    s.cpuid_valid=true;
                    ++r.succeeded;
                }
            }
            sink(s);
        }
        // Restore the full exact original mask, including high CPU IDs.
        // Caller logs any failed restoration; diagnostic must not claim
        // that requested pinning actually succeeded without OS readback.
        r.restore_rc=pthread_setaffinity_np(current, sizeof(saved), &saved);
        return r;
    }
}
#endif
'''
new=original
needle='#include "ps5_spu_hotjit.h"\n'
assert new.count(needle)==1
new=new.replace(needle,needle+'#include "ps5_cpu_topology.h"\n',1)
needle='''\tg_watchdog = std::thread([]
\t{
\t\tu64 last_dump = 0;'''
assert new.count(needle)==1
addition='''\tg_watchdog = std::thread([]
\t{
#if PS5_CPU_TOPOLOGY_PROBE
        // Opt-in, one-time diagnostic only. Pin and read back the
        // WATCHDOG thread, not guest execution, rendering or audio.
        const auto topo = ps5_cpu_topology::probe([](const ps5_cpu_topology::sample& s)
        {
            sys_log.notice("PS5 TOPO CPU: index %u set_rc %d get_rc %d mask 0x%llx x2apic %u core %u node %u tpc %u valid %u",
                s.cpu, s.set_rc, s.get_rc,
                static_cast<unsigned long long>(s.observed_mask),
                s.apic_id, s.core_id, s.node_id, s.advertised_threads,
                static_cast<unsigned>(s.cpuid_valid));
        });
        sys_log.notice("PS5 TOPO SUMMARY: allowed 0x%llx amd_leaf %u initial_rc %d restore_rc %d attempts %u succeeded %u truncated %u",
            static_cast<unsigned long long>(topo.original_mask),
            static_cast<unsigned>(topo.has_amd_core_leaf),
            topo.initial_read_rc, topo.restore_rc, topo.attempts,
            topo.succeeded, static_cast<unsigned>(topo.truncated_cpu_set));
#endif
\t\tu64 last_dump = 0;'''
new=new.replace(needle,addition,1)
arc.mkdir()
(arc/'ps5_frontend.cpp').write_text(original)
(src/names[0]).write_text(new)
(src/names[1]).write_text(header)
diff=[]
for path,a,b in ((names[0],original,new),(names[1],'',header)):
 diff.append(f'diff --git a/{path} b/{path}\n')
 if not a:diff.append('new file mode 100644\n')
 diff.extend(difflib.unified_diff(a.splitlines(True),b.splitlines(True),
 fromfile='a/'+path if a else '/dev/null',tofile='b/'+path,n=4))
patch.write_text('''From 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001
From: KB <kb@kb-rpcs3.example>
Date: Sat, 31 Oct 2026 04:02:52 +0000
Subject: [PATCH] PS5: opt-in readback-verified CPU topology probe

Default-OFF one-time diagnostic uses only watchdog thread affinity,
checks pthread set/get results, reads AMD CPUID 0x8000001E physical
core IDs per verified CPU. All guest execution/renderer affinities
unchanged; no topology assumptions made when vendor/leaf unavailable.
---
'''+''.join(diff))
(arc/'manifest.json').write_text(json.dumps({
'patch':72,'files':names,'before':{names[0]:hashlib.sha256(original.encode()).hexdigest()},
'after':{names[0]:hashlib.sha256(new.encode()).hexdigest(),names[1]:hashlib.sha256(header.encode()).hexdigest()}},indent=2)+'\n')
print('PASS patch0072 staged',patch,patch.stat().st_size)
