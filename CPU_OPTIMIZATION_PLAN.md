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
