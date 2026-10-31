# PS5 CPU optimisation plan

**Status:** Proposal only. This document creates a reviewable starting point for
`fix/cpu-optimization`; none of the five performance changes below is
implemented by this planning commit.

**Goal:** Improve real PS3 gameplay throughput and frame-time consistency on
PS5 without trading away emulation correctness. Lower reported CPU utilisation
is not itself a performance win: blocking instead of spinning can reduce CPU %
while increasing frame latency. A stable 60 FPS is a target, not an established
outcome.

The existing GTA IV NPUB30702 research in `game research/` is the starting
baseline. Previous measurements vary with run and scene. Retain 100% guest
clock scale, fixed VBlank, consistent patches, same outdoor scene/route and
warmed compilation caches for controlled A/B/A comparisons.

## 1. Optimise hot SPU LLVM JIT code (highest throughput priority)

- Profile the actual hottest guest SPU JIT functions and the host-side
  `spu_thread::cpu_task()`, channel, MFC and DMA paths. Separate productive
  guest execution from waiting/coordination before attributing frame time.
- Inspect LLVM IR and emitted Zen 2 x86-64 machine code for excessive vector
  spills/reloads, variable-index element insertion, redundant local-store
  loads/stores and dispatch overhead.
- Validate the existing optional `spu_insert_select` lowering with generated
  assembly and same-scene A/B/A runs before making any code generation change
  the default.
- Keep `spu_narrow_ls_store` experimental until the equivalence checker
  passes in real games; do not narrow stores if they can change guest-visible
  local-store behavior or ordering.

**Acceptance:** The same emulated SPU work takes less host CPU time and/or
produces measurably better FPS/frame times with correct gameplay. No
speculative bypass of SPU synchronisation.

## 2. Cut graphics busy-wait CPU waste without adding stalls

- Investigate RADV waits, Vulkan event polling, RSX FIFO idle paths,
  `rpcs3ps5_sched_yield()` and offload/DMA completion waits using existing
  instrumentation. Distinguish active rendering from spinning.
- Compare controlled short-spin + sleep/event-wake policies via
  `radv_spin_us`, `vk_event_spin_us`, and the experimental
  `rsx_dma_wait_us` setting, instead of relying on unbounded spinning.
- Prefer correct notification-based waits over blind sleeping when there is a
  reliable wake-up mechanism. Check for lost wake-ups, shutdown behavior and
  timeouts under stress.

**Acceptance:** Lower unproductive RSX/driver CPU time *and* unchanged or
improved p95/p99 frame latency and FPS, without deadlocks, flickering or
regressed audio/video synchronisation. A lower CPU percentage alone fails.

## 3. Validate PS5 SMT topology and SPU/PPU/RSX scheduling

- Verify the console's actual logical-CPU-to-physical-core sibling mapping;
  do not assume adjacent CPU IDs are SMT pairs.
- Compare OS scheduler and RPCS3 scheduler on identical warmed game runs.
  Investigate placing CPU-intensive SPU threads on separate physical cores
  and reducing competition with RSX, PPU and JIT compilation.
- Trial `spu_hot_cpu` and the sibling-free CPU candidate only with the
  supported RPCS3 scheduler and after verifying affinity really takes effect.
- Track migrations, per-thread load, FPS and frame-time tails; distinguish a
  stationary-scene gain from gains while driving.

**Acceptance:** Repeated improvement without starving rendering, audio,
host services or game threads. Keep opt-out/rollback paths.

## 4. Reduce compilation contention and unnecessary JIT work

- Measure cold-start versus warmed game sessions, PPU/SPU/shader compilation
  frequency, cache hits and mid-game stutter.
- Review the existing 10 LLVM compile-worker default. Test lower or adaptive
  compilation concurrency when SPU gameplay threads are saturated, while
  retaining parallel compilation for loading screens.
- Preserve safe PPU/SPU JIT cache reuse across matching games, settings and
  emulator revisions. Reject stale or mismatched caches instead of
  reusing them incorrectly.
- Keep diagnostic code dumps optional and avoid repeated recompilation of
  already validated blocks.

**Acceptance:** Less compilation-time CPU contention, fewer compilation-related
frame spikes and no increase in startup time disproportionate to the benefit.
Report cold and warm results separately.

## 5. Fix/verify native TLS and remove production profiling overhead

- Validate native `thread_local` initialisation, alignment, loader TLS
  templates and thread lifecycle against the actual PS5 target. Use the
  existing `check-native-tls.py` and native/emulated build separation.
  Do **not** assume removing emulated TLS is safe merely because a small
  probe passes; previous broken native TLS caused severe game regressions.
- Measure native-versus-emulated TLS overhead only after correctness is
  established. Maintain a known-working emulated-TLS fallback.
- Disable or substantially reduce SIGUSR1 sampling, high-frequency CPU
  monitoring, verbose frame logs and JIT binary dumps in normal gameplay,
  while retaining a separate opt-in diagnostic mode.
- Benchmark both the profiling-on and profiling-off builds so the profiler
  itself does not distort the optimiser's evidence.

**Acceptance:** Native TLS is correct before adoption; release builds retain
diagnostic access without paying unnecessary per-frame CPU cost.

## Measurement and safety gates

1. Record the exact executable/core patch revision, game serial, settings,
   firmware/build configuration and existing patches for every experiment.
2. Keep the console's guest clock at **100%**, use consistent VBlank/frame
   limits, allow caches to warm, and measure the same scene/drive route.
3. Compare baseline, candidate and rollback (**A/B/A**, repeated where
   possible). Report average FPS, 1% lows, p50/p95/p99 frame time, per-thread
   CPU time and compilation events. Confirm normal guest/host time ratio.
4. Check correctness (boot, saves, graphics, sound, collisions, input and
   sustained play) and keep the signed executable plus matching code mirror
   together for reliable rollback.
5. Treat changes independently, and only enable a default after results
   exceed run-to-run variance. Document failed experiments as well.

**Proposed sequence:** SPU JIT hot-path profiling/codegen; RSX wait policy;
verified core affinity; adaptive JIT compilation/cache tuning; native TLS and
release-mode profiling cleanup. Each optimisation should get its own
measured commit(s). No FPS uplift is claimed by this document.

## Execution progress — 2026-10-31

**General CPU plan work is active; GTA IV-specific benchmarking is paused.** The first Section 1 offline checkpoint is completed and documented in [CPU_OPTIMIZATION_WORKLOG.md](CPU_OPTIMIZATION_WORKLOG.md). The test script is port/tests/check-spu-insert-select-codegen.py; its machine-code/semantic results are saved in results/cpu-plan-spu-insert-select-codegen-20261031.json.

- **Section 1, partial validation:** four variable-index 128-bit SPU insertion lane widths passed 16,384 random/boundary semantic comparisons. Offline PS5/Zen2 LLVM19 codegen showed 3 stack-memory instructions for the default form versus 0 for the optional select form, but 6 versus 8–9 total instructions. The emulator's real SPU JIT uses LLVM22.1.8, so actual hot guest JIT output and gameplay benefits remain unverified. Keep spu_insert_select=0, spu_narrow_ls_store=0 and spu_narrow_ls_check=0 by default.
- **Sections 2–4:** not yet evaluated in this generic roadmap pass. Preserve all existing safe defaults and measurement gates.
- **Section 5:** prior native TLS correctness checks exist; production profiler-on/off overhead still needs explicit comparison. Do not infer performance from a reduced CPU utilisation percentage.

**Next Section 1 gate:** identify actual hot guest SPU JIT function hashes/PCs using opt-in runtime profiling, then compare their LLVM22 Zen2 machine code with the insertion option OFF and ON. Do not claim an optimisation or change the default until representative correctness and controlled A/B/A performance tests pass. No console deployment or game/settings changes occurred during this checkpoint.

## Execution progress checkpoint 2 — 2026-10-31

**Section 1 tooling implemented; real hot-function profiling and JIT-code comparison pending.** Reversible patch 0070 adds a default-OFF, SPU-only native PS5 JIT sampling mode, reusing the existing SIGUSR1 profiler and avoiding automatic executable JIT dumps. Both OFF and ON images passed full PS5 compilation, native TLS and nine package checks. The ON image is archived **offline only**, was not deployed or run against a game, and normal WSL source/build output is restored to OFF. The generic profiler parser and bounded cached LLVM-object symbol disassembler pass synthetic host regression tests. Actual guest function-hash rankings, LLVM22 guest JIT object disassembly and profiling-on/off performance overhead are **NOT yet measured**. The current nearest-SPU-entry attribution is heuristic, not an exact function boundary; verify against the matching cached LLVM22 ELF symbol before interpreting a hotspot.

Details, reproducible commands and SHA256 evidence are in `CPU_OPTIMIZATION_WORKLOG.md` and `results/cpu-plan-hotjit0070-20261031/manifest.json`. Current source profile patch count 70, installed PS5 title not changed. **GTA IV-specific work remains paused.** Next Section 1 milestone requires a representative non-GTA-IV SPU workload, safe guarded diagnostic deployment if requested, enough warmed samples, and comparison of the exact same LLVM22 guest JIT functions OFF/ON with correctness and A/B/A measurement gates. No optimisation has been promoted.

## Execution progress checkpoint 3 — Section 2 Vulkan/RSX waits (2026-10-31)

**Source audit and correctness gates complete; FPS/latency improvement NOT measured.** Existing Vulkan event wait is unbounded-spin by default (`vk_event_spin_us=-1`); Vulkan fence zero-timeout wait busy-polls; RSX DMA polling default is `rsx_dma_wait_us=0` with separately tested opt-in bounded wait. The title's RADV wait metrics have weak zero-valued fallbacks, so zeros are not proof the driver does no waiting. See `CPU_OPTIMIZATION_SECTION2_WAIT_AUDIT_20261031.md`.

New source-extract host tests `port/tests/check-ps5-vk-event-wait.py` and `port/tests/check-ps5-vk-fence-wait.py` passed immediate, delayed signal, default unbounded/opt-in bounded mode, timeout, device-loss/error and counter/trace gates; existing `check-ps5-rsx-wait.py` passed DMA callback, completion race, fault/stop and tuning rollback. Reversible patch `0071-PS5-opt-in-bounded-Vulkan-fence-wait.patch` introduces a **DEFAULT-OFF** `PS5_VK_FENCE_TIMED_WAIT` diagnostic: after 64 fence polls, request a 100µs Vulkan timed wait; VK_TIMEOUT retries and errors propagate. Tests for exact patch rollback and ON/OFF C++ builds passed. **Do not turn it on by default until independent real PS5 device, performance and shutdown checks.**

Both default OFF and optional diagnostic ON full PS5 title images passed native TLS, code mirror and nine package checks. ON archived offline at `/home/callum/work/cpu-plan-vk-fence0071-diagnostic-20261031/`, **never installed on PS5**. The normal header and build were then restored OFF with matching first-OFF executable/mirror SHA256 values. Full evidence: `results/cpu-plan-rsx-waits0071-20261031/manifest.json`. Source profile patch count **71**; last console installation from the previous test remains original patch0064 gate0. User-requested GTA IV pause remains active.

**Next Section 2 gate:** choose another representative SPU/RSX workload, verify that zero-timeout Vulkan fence polling is actually hot, obtain accurate driver/wait telemetry, then run guarded A/B/A of OFF vs ON with FPS, frame p95/p99, per-thread CPU time, wake latency, shutdown and graphics/audio correctness. Otherwise keep the candidate OFF and continue offline Sections 3–5.

## Execution progress checkpoint 4 — Section 3 CPU topology and scheduling (2026-10-31)

**Offline topology/affinity audit and isolated diagnostic builds complete; console SMT topology and real guest worker pinning NOT YET VERIFIED.** The current PS5 scheduler assumes adjacent SMT siblings (`kPs5Sibling=1`), while historical logs only establish `0x1fff` allowed logical CPU mask and derived `0x555` SPU and `0x1aaa` PPU/RSX masks; they do **not** prove physical siblings or CPU12 being an isolated core. The opt-in `spu_hot_cpu` feature is still OFF (`-1`), and the rebalancer's `ps5_apply_mask` does not check `pthread_setaffinity_np` return codes. This acceptance gate cannot be met solely by an offline build.

Reversible **patch0072** adds a default-OFF, one-shot `PS5_CPU_TOPOLOGY_PROBE` observer, only on the watchdog host thread. When explicitly ON, it saves the thread's full affinity, temporarily pins it to each permitted logical CPU, checks OS affinity readback, queries AMD CPUID extended leaf 0x8000001E for APIC/core/node/threads-per-core when supported, and restores the full original watchdog mask. No SPU/PPU/RSX/audio worker is pinned by this probe. Parser `tools/ps5-cpu-topology.py` rejects incomplete or failed data; synthetic adjacent/nonadjacent 13-CPU mapping, CPU12 singleton, error and restore-failure cases passed, as did standalone hosted C++20 affinity set/get/restore and exact patch reversal. The initial native ON attempt exposed PS5 SDK FreeBSD `cpuset_t`/`pthread_np.h` requirements; fixed and rebuilt.

Both full native PS5 OFF and ON diagnostic builds passed nine package checks, native TLS and full code mirror verification. The ON image was archived only; **no PS5 deployment, game run or scheduling change was performed**. The normal source flag and full build are restored OFF with SHA256 matching the first OFF build. Source patch count **72**, distinct from live PS5 title. Full audit `CPU_OPTIMIZATION_SECTION3_TOPOLOGY_AUDIT_20261031.md`, build hashes/results `results/cpu-plan-topology0072-20261031/manifest.json`.

**Next:** Acquire reliable one-shot **on-console** CPUID + kernel affinity readback when a safe diagnostic execution is appropriate, then verify actual SPU/PPU/RSX worker masks and migrations. Only then compare the OS and RPCS3 schedulers, test `spu_hot_cpu` where physically appropriate and measure non-GTA-IV gameplay A/B/A with FPS, p95/p99, real host CPU and correctness. CPU12 is **not** a proven SMT-free performance target yet. GTA IV-specific work remains paused.

## Execution progress checkpoint 5 — Section 4 compilation contention and cache (2026-10-31)

**Section 4 offline work complete; no gameplay speedup proven.** Audit: PPU LLVM workers default 10, initial SPU cache precompilation uses a *separate* `SPU Worker ` pool, while the live runtime `SPUW.` pool is independently sized (4 at 13 logical CPUs). Vulkan shader compilation is also independent. Existing SPU cache uses per-title guest instruction programs, address/size validation, optional legacy CRC16 and duplicate reuse; optional CRC is not complete native code/revision validation. No cache files were erased or rewritten.

**Default-OFF patch0073:** `PS5_SPU_LIVE_JIT_WORKER_CAP=0` preserves live SPU runtime workers; an opt-in diagnostic value **2** restricts only runtime `SPUW.` from 4→2 at 13 CPUs. This does **not** change the PPU LLVM limit, initial SPU cache precompilation pool, shader compilation, guest execution, JIT codegen or cache formats. Reversible exact patch replay and C++20 worker cap 0/1/2/4/32 logic checks PASS, including nonzero worker floor. Native PS5 OFF/ON full builds, nine package checks, TLS and mirror PASS. ON artifact archived offline `/home/callum/work/cpu-plan-jit0073-cap2-diagnostic-20261031/` but **never installed on PS5**. The source header and title build were restored OFF, with both hashes matching the first OFF build. Selected source patch count now **73**. Full audit: `CPU_OPTIMIZATION_SECTION4_JIT_CONTENTION_AUDIT_20261031.md`; manifest `results/cpu-plan-jit-workers0073-20261031/manifest.json`.

**Acceptance still pending:** measure PPU/SPU/shader compilation activity, cache misses and cold-start versus warmed **non-GTA-IV** gameplay sessions; verify live SPUW compiler actually competes with SPU execution; compare cap0 vs cap2 using guarded matched A/B/A, mean FPS, 1% lows, p50/p95/p99, host worker CPU occupancy and startup duration, without deleting saves or caches. Slower compilation may worsen new-block stalls. The cap is **not adaptive**, and no throughput improvement is claimed. No console deployment or game testing was performed; last verified installed title remains original patch0064 gate0. Next offline priority Section 5 native TLS and release profiling cost.

## Execution progress checkpoint 6 — Section 5 native TLS and production profiling (2026-10-31)

**Offline implementation/review COMPLETE; actual on-console performance acceptance pending.** Reversible source patch `0074-PS5-default-off-production-CPU-profiling.patch` introduces **`PS5_RELEASE_PROFILE_ACTIVE=0` default**, removing regular SIGUSR1 CPU monitoring, verbose 4-second FPS/CPU/RSX logs, SPU wait/wakeup and worker activity counters, sampled RSX register/method histograms and per-JIT-function profiler map registration from release builds. Separate diagnostic `=1` retains these mechanisms, with SPU HOTJIT separately opt-in. Hang watchdog SIGUSR2, 20-second main-thread heartbeat checks, PS5 live tuning-file refresh, native TLS flags, guest code and JIT semantics remain unchanged. In the normal build older log-based FPS/CPU capture scripts no longer see `PS5 FPS`/`PS5 CPU`; use diagnostic build with observer-overhead control. Experimental `spu_hot_cpu` cannot use non-existent snapshots in release and emits a warning rather than silently pinning threads.

Exact reverse/forward patch and C++20 profiling ON/OFF tests PASSED. Actual PS5-target Znver2 O3 sampled reservation microprobe emitted **2 instructions OFF vs 67 ON**; *this is not an FPS or CPU speedup benchmark*. Native and emulated TLS cross-target object and hosted initializer/alignment/thread isolation/destructor tests PASSED (actual PS5 TLS alignment maximum **32 bytes**, not 64); independent native guest-context TLS feasibility tests PASSED, confirming direct JIT guest-context parameters remain cheaper than TLS loads. Native converter's PT_TLS template and writable PT_LOAD checks PASSED for two complete PS5 builds; **actual PS5 TLS thread lifetime not yet verified**.

Complete title builds with nine package checks and full PT_LOAD/code-mirror checks: release OFF eboot SHA256 `755d783f6a30dd8df975df042ec612c7281fa64bb87c26d6bc5baa7ae9ec935f`, mirror `28090ff0915b5dc50e62acc17e808441f9ed667caff163f82870b0323e5e450b`, PT_TLS 128/15088/32; diagnostic ON eboot `98b483516ff4e1c3a64239502d92c3f989a8917f595ea415a3027b002a8300f2`, mirror `5ddd5722c548368c0d837caabd14bcc670b75f338f10604a10983c69d8510634`, PT_TLS 128/15136/32. Both archived **OFFLINE, NEVER DEPLOYED**; normal WSL header restored OFF and complete release title rebuilt with matching first-OFF checksums. Emulated-TLS fallback build path (`PS5_NATIVE_TLS=OFF`, no extra core native flags) is **preserved but not full-title rebuilt/run** here. Full audit `CPU_OPTIMIZATION_SECTION5_TLS_AND_PROFILING_AUDIT_20261031.md`; manifest `results/cpu-plan-profile0074-20261031/manifest.json`.

**CPU roadmap:** Sections 1–5 now each have an offline source/test checkpoint; none of the speculative optimisation candidates has been promoted on the console. Section 5 acceptance still requires separate native/emulated TLS on-PS5 thread lifecycle tests and representative non-GTA-IV release-profile OFF/ON matched FPS, CPU and frame-time p95/p99 checks. Source patch manifest count **74** does NOT mean the PS5 has patch0074 installed; last independently verified console title remained original patch0064 gate0. No PS5 connection, save, cache, game or config changes in this offline task. GTA IV-specific work remains paused.


## Latest console deployment � patch0074 release (2026-10-31)

User selected and authorised latest patch74 safe-default release. **Now installed and independently verified on PS5**, superseding prior patch0064-live/offline-only notes. Experimental CPU-plan options remain OFF, production profiling OFF, native TLS retained. Exact patch0064 gate0 backup pair retained at `.before-cpuplan0074-release-20261031`; both backup and live ELF load/TLS + mirrors independently read back PASS. Final complete process listing: game/launcher CLOSED. No game launched or settings/saves/caches altered; performance and TLS lifecycle acceptance pending user testing. Full state, hashes, logs and rollback: `game research/CPU-plan-patch0074-user-testing-20261031.md` and `results/cpu-plan-release0074-deployment-20261031/installed.json`. Fresh process checks required before any later swap.


## Latest console state - combined five-option patch74 experiment (2026-10-31)

User explicitly authorised all five experimental options. Combined native build is now LIVE: SPU insert/select1, Vulkan fence timed-wait1, topology observer1, live SPU compiler cap2 and hot-JIT profiler1 (requires production profiling ON). Fresh full independent installed/backup ELF load+TLS and mirror checks PASS; exact new tuning file readback PASS; final process listing title/launcher CLOSED. Prior safe-default patch74 pair preserved as `.before-cpuplan0074-combined-20261031`; original patch0064 backup remains. Source default gates restored OFF, current build output experimental. No game launched/performance measured; saves/per-game configs/caches untouched. See `game research/CPU-plan-patch0074-user-testing-20261031.md` latest section and `results/cpu-plan-combined0074-20261031/installed.json`. Rollback requires restoring prior tuning absence as well as the paired binaries, with fresh process checks. Next: user gameplay test; actual topology/JIT samples and performance acceptance pending.
