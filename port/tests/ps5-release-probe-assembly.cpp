// Offline PS5 Zen2 codegen proof that diagnostic-only probes compile away.
#include "rpcs3/Emu/Cell/ps5_spu_reswait.h"
#include "rpcs3/Emu/Cell/ps5_spu_wakeup.h"
#include <cstdint>
extern "C" __attribute__((noinline))
std::uint32_t ps5_probe_guest_reservation(std::uint32_t guest_addr)
{
    // Real probe APIs injected by patch0068/0069 in reservation hotpaths.
    const ps5_spu_reswait::scope meter(ps5_spu_reswait::event::atomic_wait);
    const ps5_spu_wakeup::wait_probe probe(guest_addr);
    probe.finish(true, false);
    return probe.sampled() ? 1 : 0;
}
