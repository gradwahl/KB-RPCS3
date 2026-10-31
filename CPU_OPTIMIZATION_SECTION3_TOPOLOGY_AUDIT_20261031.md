# CPU optimisation plan — Section 3 PS5 SMT topology and affinity audit

**Date:** 31 October 2026  
**Status:** Offline code audit, simulator checks and separate PS5-target OFF/ON builds complete. **Physical PS5 SMT pairing and applied guest-worker affinity are NOT yet verified.** GTA IV-specific work remains paused.

## What the existing code actually establishes

In `Utilities/Thread.cpp` the PS5 scheduler currently assumes **`kPs5Sibling=1`**: logical CPUs (0,1), (2,3), ... share physical cores. It constructs two scheduling masks from that assumption. Historical PS5 logs recorded **process affinity `0x1fff`**, i.e. allowed logical IDs 0–12, and the scheduler's derived masks **SPU `0x555`** and **PPU/RSX `0x1aaa`**. Those masks show what the existing policy *requested*, not that the OS used them as desired, and **do not prove physical SMT sibling relationships**. CPU 12 being a logical singleton is only a candidate; a real core ID / allowed-sibling check must come first.

Additional current-state findings:
- `ps5_apply_mask(pthread_t,u64)` builds a CPU set but **ignores the return value** from `pthread_setaffinity_np`. The optional hot-SPU rebalancer therefore cannot prove a requested pin was accepted. Its success messages describe requests, not verified readbacks.
- The `spu_hot_cpu` experiment is OFF by default (`-1`), and engages only if the RPCS3 rather than OS scheduler is selected, CPU is allowed and a busy eligible SPU execution worker exceeds the 85% activation threshold.
- Some hot-rebalance cases can exclude a CPU from an already small normal mask; verification needs to reject empty or invalid masks before changing behavior. This issue was recorded, **not silently modified**.
- `get_process_affinity_mask()` on Unix-like systems caches an initial **thread affinity mask** under a comment that the main-thread assumption is shaky. Compare it with the watchdog and actual worker masks before relying on it as a permanent process-wide value.
- The normal `thread_ctrl::set_thread_affinity_mask()` logs its own failures; the hot-SPU rebalancer's separate `ps5_apply_mask` does not. Keep those paths distinct when evaluating success.

## Patch 0072: one-shot default-OFF topology observer

`port/rpcs3-latest-patches/0072-PS5-opt-in-CPU-topology-and-affinity-readback.patch` adds `rpcs3/ps5/ps5_cpu_topology.h` and hooks it once into `rpcs3/ps5/ps5_frontend.cpp`'s watchdog creation. Compile-time **`PS5_CPU_TOPOLOGY_PROBE=0`** disables all diagnostic execution and leaves existing scheduling masks unchanged. Explicit ON mode:

1. Uses the **watchdog's own host thread**, not any SPU, PPU, RSX or audio thread. Saves its full OS affinity `cpuset_t` or `cpu_set_t`.
2. Iterates the OS-permitted logical CPUs. Temporarily requests a one-CPU mask on the watchdog, calls `pthread_getaffinity_np` and checks that the kernel readback equals the requested singleton. It logs every set/get return status.
3. Only when a singleton readback matches and AMD CPUID extended leaf **0x8000001E** is available: reads extended APIC ID, core ID, node ID and reported threads per core on that pinned logical CPU. When vendor/leaf is unavailable, the diagnostic explicitly reports unknown topology rather than guessing.
4. Restores the **complete original watchdog CPU mask**, including any CPUs outside the supported 64-bit reporting window, and reports the restoration return code.

Even a complete report indicates **AMD CPUID-reported sibling groups plus successful OS affinity readbacks**, not independently measured resource contention or the guest workers' actual scheduling. A failed mask restore, missing CPUID leaf, missing pinned readback, duplicated APIC ID or partial coverage means **no topology confirmation**.

The initial diagnostic native build exposed a PS5-specific SDK difference: the console's FreeBSD-derived headers require `pthread_np.h` and `cpuset_t`, not Linux `cpu_set_t` from `sched.h` alone. The header was corrected to use the same FreeBSD affinity declarations as existing `Utilities/Thread.cpp`, tests rerun, **native ON build PASS**. This was a build-time integration fix; no game was used.

## Parsing and host tests

- `tools/ps5-cpu-topology.py` parses the `PS5 TOPO CPU` and final `PS5 TOPO SUMMARY` messages, validates all allowed CPUs, full OS affinity readback and final restoration, CPUID capability, APIC uniqueness and reported threads per core. It reports whether observed core groups match the **adjacent-sibling hypothesis** only with complete evidence. Partial evidence explicitly remains UNVERIFIED.
- `port/tests/check-ps5-cpu-topology-parser.py`: synthetic 13-CPU adjacent pairs / CPU12 singleton, alternate **nonadjacent** pairing, failed pin, unsupported CPUID, failed restoration, missing and duplicate summary. All PASS. These synthetic layouts are test vectors, **not measured PS5 topology**.
- A Clang19 Linux C++20 harness compiled the real `ps5_cpu_topology::probe`, exercised host pthread affinity set/get on the test process and restored the original mask. PASS; host machine's physical topology must not be projected onto PS5.
- `port/tests/check-ps5-cpu-topology0072.py`: reversible exact patch forward/reverse replay, pristine source hash comparison, and Clang19 C++20 default-OFF and explicit-ON gates PASS.

## Native compilation and preservation

Two full native PS5 images built with the linked RPCS3 LLVM 22.1.8 and nine title/package checks:
- **Normal OFF** signed executable SHA256: `06ebbed51d8169cb832424c208dc438446468bc8449c74b88a8258a5837249bb`; paired code mirror `91a6e9a59a0426549dd37758d1ef818a75294d1b328d3b536ba4b344e2f599f2`. It was rebuilt after the ON diagnostic and **both SHA256 values match the initial OFF build**.
- **Optional ON** signed executable SHA256: `4ee7f498e5bd2a5e5c374df7a019d5671ae8037efe29ef52a56eb5f3ba188d93`; code mirror `888168c7ba10fbc008864b58e38d7fd18f464021df2a3dd08eedde44833ed877`. The independent archive `/home/callum/work/cpu-plan-topology0072-diagnostic-20261031/` contains signed executable, native ELF and full code mirror. Full ELF executable PT_LOAD matched mirror; native PT_TLS template **128**, allocation **15,136**, alignment **32** bytes PASS.

**No PS5 staging, installation, game run, or guest setting/save/cache change occurred.** The ON archive is offline-only. Final WSL source header and normal build are OFF. Source patch manifest count is **72**, distinct from the previously independently verified PS5 installed control patch0064 gate0. No fresh PS5 process/status check was needed for these offline steps.

Machine-readable evidence: `results/cpu-plan-topology0072-20261031/manifest.json`.

## Next acceptance gate

**No affinity policy can be promoted yet.** To conclude the topology phase, use a *guarded* diagnostic deployment and capture the one-shot CPU map on real PS5 hardware, even without a gameplay benchmark. Inspect the CPUID core ID/node groupings, complete OS pin/readback success and original watchdog affinity restoration. After that, separately verify actual guest SPU/PPU/RSX worker affinity masks, migrations and real SMT competition, compare OS and RPCS3 scheduler in an authorized representative non-GTA-IV game (A/B/A, frame-time tails and CPU occupancy), and maintain rollback. Do not presume CPU12 is a spare dedicated physical core.
