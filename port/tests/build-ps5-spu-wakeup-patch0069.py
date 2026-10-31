#!/usr/bin/env python3
"""Create patch0069 from existing WSL patch0068 worktree, no reset."""
from pathlib import Path
import difflib, hashlib, json
wsl=Path('/home/callum/work/rpcs3-latest')
repo=Path(__file__).resolve().parents[2]
archive=Path('/home/callum/work/ps5spu0069-original-20261031')
patch=repo/'port/rpcs3-latest-patches/0069-PS5-sample-SPU-reservation-page-wait-outcomes-and-producer.patch'
names=['rpcs3/Emu/Cell/SPUThread.cpp','rpcs3/Emu/Memory/vm.cpp','rpcs3/ps5/ps5_frontend.cpp','rpcs3/Emu/Cell/ps5_spu_wakeup.h']
assert not archive.exists() and not patch.exists() and not (wsl/names[-1]).exists()
baseline={n:(wsl/n).read_text() for n in names[:-1]}
header=r'''#pragma once
// Patch0069: diagnostic-only sampled guest reservation-page attribution.
// Fixed-size bounded open-address table, relaxed atomic counters only.
// Counts represent SAMPLED events (1/128 per host thread for each path),
// NOT exact wait/notification totals. No guest memory writes or behavior changes.
#ifdef __PROSPERO__
#include <array>
#include <atomic>
#include <cstdint>

namespace ps5_spu_wakeup
{
    constexpr unsigned sample_every = 128;
    constexpr unsigned slots = 256;
    constexpr unsigned probes = 8;
    struct slot
    {
        std::atomic<std::uint32_t> page_key{0}; // guest page index + 1; 0 = vacant
        std::atomic<std::uint64_t> waits{0};
        std::atomic<std::uint64_t> changed_flag{0};
        std::atomic<std::uint64_t> cleared_reservation{0};
        std::atomic<std::uint64_t> unchanged{0};
        std::atomic<std::uint64_t> notify_ppu{0};
        std::atomic<std::uint64_t> notify_spu{0};
        std::atomic<std::uint64_t> notify_other{0};
    };
    inline std::array<slot, slots> table{};
    inline std::atomic<std::uint64_t> overflow{0};
    inline std::atomic<std::uint64_t> wait_samples{0};
    inline std::atomic<std::uint64_t> producer_samples{0};
    // Consumer outcome order prioritises guest-reservation clear.
    enum class outcome : unsigned { changed, cleared, same };
    enum class producer : unsigned { ppu, spu, other };

    inline slot* get_slot(std::uint32_t addr) noexcept
    {
        // Use real full 4 KiB page index; no aliasing via a narrow band.
        const std::uint32_t key = (addr >> 12) + 1u;
        // Mix upper bits so guest regions land across the fixed array.
        const std::uint32_t h = ((key ^ (key >> 11)) * 2654435761u) & (slots - 1);
        for (unsigned j=0; j<probes; ++j)
        {
            slot& s=table[(h+j)&(slots-1)];
            std::uint32_t present=s.page_key.load(std::memory_order_acquire);
            if (present==key) return &s;
            if (present==0 && s.page_key.compare_exchange_strong(
                    present,key,std::memory_order_release,std::memory_order_relaxed))
                return &s;
        }
        overflow.fetch_add(1,std::memory_order_relaxed);
        return nullptr;
    }

    // Cheap on every wait: just one per-host-worker TLS counter, clocks
    // belong to patch0068 and are not sampled again.
    class wait_probe
    {
        const std::uint32_t addr;
        bool enabled=false;
    public:
        explicit wait_probe(std::uint32_t guest_addr) noexcept : addr(guest_addr)
        {
            static thread_local std::uint32_t phase=0;
            enabled=((phase++ & (sample_every-1))==0);
        }
        bool sampled() const noexcept { return enabled; }
        void finish(bool flag_changed,bool cleared) const noexcept
        {
            if (!enabled) return;
            wait_samples.fetch_add(1,std::memory_order_relaxed);
            if (auto* s=get_slot(addr))
            {
                s->waits.fetch_add(1,std::memory_order_relaxed);
                (cleared ? s->cleared_reservation : flag_changed
                    ? s->changed_flag : s->unchanged)
                    .fetch_add(1,std::memory_order_relaxed);
            }
        }
    };
    inline bool sample_notification() noexcept
    {
        static thread_local std::uint32_t phase=0;
        return ((phase++ & (sample_every-1))==0);
    }
    inline void note_notification(std::uint32_t addr,producer from) noexcept
    {
        producer_samples.fetch_add(1,std::memory_order_relaxed);
        if (auto* s=get_slot(addr))
        {
            (from==producer::ppu ? s->notify_ppu : from==producer::spu
                ? s->notify_spu : s->notify_other)
                .fetch_add(1,std::memory_order_relaxed);
        }
    }
    struct snap
    {
        std::uint32_t page;
        std::uint64_t waits, changed, cleared, unchanged, ppu, spu, other;
    };
    inline snap read(const slot& x) noexcept
    {
        const auto k=x.page_key.load(std::memory_order_acquire);
        return { k ? (k-1)<<12 : 0, x.waits.load(std::memory_order_relaxed),
            x.changed_flag.load(std::memory_order_relaxed),
            x.cleared_reservation.load(std::memory_order_relaxed),
            x.unchanged.load(std::memory_order_relaxed),
            x.notify_ppu.load(std::memory_order_relaxed),
            x.notify_spu.load(std::memory_order_relaxed),
            x.notify_other.load(std::memory_order_relaxed)};
    }
}
#endif
'''
spu=baseline[names[0]]
needle='''                                const ps5_spu_reswait::scope ps5_wait_meter(ps5_spu_reswait::event::atomic_wait);
                                utils::bless<atomic_t<u32>>(&wait_var->raw().wait_flag)->wait(flag_val, atomic_wait_timeout{100'000});'''
assert spu.count(needle)==1
replacement='''                                const ps5_spu_reswait::scope ps5_wait_meter(ps5_spu_reswait::event::atomic_wait);
                                const ps5_spu_wakeup::wait_probe ps5_page_probe(_raddr);
                                utils::bless<atomic_t<u32>>(&wait_var->raw().wait_flag)->wait(flag_val, atomic_wait_timeout{100'000});
                                if (ps5_page_probe.sampled())
                                {
                                    // wait_var is still live until reservation_notifier_end_wait().
                                    // Observations only; do not change guest state / wait semantics.
                                    const u32 after_flag=utils::bless<atomic_t<u32>>(&wait_var->raw().wait_flag)->load();
                                    ps5_page_probe.finish(after_flag!=flag_val, this->raddr==0);
                                }'''
spu=spu.replace(needle,replacement,1)
incl='#include "ps5_spu_reswait.h"\n'
assert spu.count(incl)==1
spu=spu.replace(incl,incl+'#include "ps5_spu_wakeup.h"\n',1)

vm=baseline[names[1]]
incl='#include "Emu/CPU/CPUThread.h"\n'
assert vm.count(incl)==1
vm=vm.replace(incl,incl+'#ifdef __PROSPERO__\n#include "Emu/Cell/ps5_spu_wakeup.h"\n#endif\n',1)
needle='''\t\t\tif (postpone)
\t\t\t{
\t\t\t\treturn utils::bless<atomic_t<u32>>(&waiter->raw().wait_flag);
\t\t\t}

\t\t\tutils::bless<atomic_t<u32>>(&waiter->raw().wait_flag)->notify_all();'''
assert vm.count(needle)==1
vm=vm.replace(needle,'''#ifdef __PROSPERO__
            // A successful odd->even transition indicates an attempted
            // wake notification, not that a particular waiter resumed.
            // Classify the calling CPU guest thread only on 1/128 samples.
            if (ps5_spu_wakeup::sample_notification())
            {
                const auto* cpu=get_current_cpu_thread();
                const auto source=!cpu ? ps5_spu_wakeup::producer::other :
                    cpu->get_class()==thread_class::ppu ? ps5_spu_wakeup::producer::ppu :
                    cpu->get_class()==thread_class::spu ? ps5_spu_wakeup::producer::spu :
                    ps5_spu_wakeup::producer::other;
                ps5_spu_wakeup::note_notification(raddr,source);
            }
#endif
            if (postpone)
            {
                return utils::bless<atomic_t<u32>>(&waiter->raw().wait_flag);
            }
            utils::bless<atomic_t<u32>>(&waiter->raw().wait_flag)->notify_all();''',1)

front=baseline[names[2]]
incl='#include "Emu/Cell/ps5_spu_reswait.h"\n'
assert front.count(incl)==1
front=front.replace(incl,incl+'#include "Emu/Cell/ps5_spu_wakeup.h"\n',1)
needle='''#ifdef __PROSPERO__
                // Sparse cross-thread CPU timeline: drain the fixed ring on the'''
assert front.count(needle)==1
newlog='''#ifdef __PROSPERO__
                // Patch0069: sample-only guest 4KiB reservation pages and
                // successful producer notifications. Cumulative per-page
                // counters; compare per-window deltas. Ranking is watchdog
                // only. No per-event guest CPU logging or allocation.
                {
                    const auto waits=ps5_spu_wakeup::wait_samples.load(std::memory_order_relaxed);
                    const auto prod=ps5_spu_wakeup::producer_samples.load(std::memory_order_relaxed);
                    const auto lost=ps5_spu_wakeup::overflow.load(std::memory_order_relaxed);
                    sys_log.notice("PS5 SPUWAKE2: period 128 sample_waits %llu sample_producers %llu overflow %llu slots 256",
                        static_cast<unsigned long long>(waits),
                        static_cast<unsigned long long>(prod),
                        static_cast<unsigned long long>(lost));
                    std::array<ps5_spu_wakeup::snap,8> hottest{};
                    for (const auto& cell:ps5_spu_wakeup::table)
                    {
                        if (!cell.page_key.load(std::memory_order_acquire)) continue;
                        const auto s=ps5_spu_wakeup::read(cell);
                        const auto score=s.waits; // rank by cumulative wait samples
                        if (!score) continue;
                        for (unsigned i=0;i<hottest.size();++i)
                        {
                            if (score>hottest[i].waits)
                            {
                                for (unsigned j=hottest.size()-1;j>i;--j) hottest[j]=hottest[j-1];
                                hottest[i]=s;
                                break;
                            }
                        }
                    }
                    for (unsigned i=0;i<hottest.size() && hottest[i].waits;++i)
                    {
                        const auto& s=hottest[i];
                        sys_log.notice("PS5 SPUWAKEPAGE: rank %u page 0x%08x waits %llu changed %llu cleared %llu unchanged %llu producer_ppu %llu producer_spu %llu producer_other %llu",
                            i+1,s.page,
                            static_cast<unsigned long long>(s.waits),
                            static_cast<unsigned long long>(s.changed),
                            static_cast<unsigned long long>(s.cleared),
                            static_cast<unsigned long long>(s.unchanged),
                            static_cast<unsigned long long>(s.ppu),
                            static_cast<unsigned long long>(s.spu),
                            static_cast<unsigned long long>(s.other));
                    }
                }
                // Sparse cross-thread CPU timeline: drain the fixed ring on the'''
front=front.replace(needle,newlog,1)
updated={names[0]:spu,names[1]:vm,names[2]:front,names[3]:header}
archive.mkdir()
for n in names[:-1]:
 original=baseline[n]
 (archive/Path(n).name).write_text(original)
 (wsl/n).write_text(updated[n])
(wsl/names[3]).write_text(header)
diff=[]
for n in names:
 original=baseline.get(n,'')
 after=updated[n]
 diff.append(f'diff --git a/{n} b/{n}\n')
 if not original:diff.append('new file mode 100644\n')
 diff.extend(difflib.unified_diff(original.splitlines(True),after.splitlines(True),fromfile='a/'+n if original else '/dev/null',tofile='b/'+n,n=4))
patch.write_text('''From 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001
From: KB <kb@kb-rpcs3.example>
Date: Sat, 31 Oct 2026 02:30:00 +0000
Subject: [PATCH] PS5: sample SPU reservation pages and producer class

Capture one-in-128 consumer wait outcomes and successful producer
notifications per full 4KiB guest address page, via fixed 256-slot
bounded lock-free hash table. Existing wall/CPU wait sampler unchanged;
watchdog-only log/report. No guest state or synchronization changes.
---
'''+''.join(diff))
(archive/'manifest.json').write_text(json.dumps({'before':{n:hashlib.sha256(baseline[n].encode()).hexdigest() for n in names[:-1]},'after':{n:hashlib.sha256(updated[n].encode()).hexdigest() for n in names},'patch':str(patch),'patch_count':69},indent=2)+'\n')
print('PASS created patch0069',patch,'size',patch.stat().st_size)
