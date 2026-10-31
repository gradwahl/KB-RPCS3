# CPU optimisation plan — Section 2 RSX/Vulkan wait audit

**Date:** 31 October 2026  
**Status:** Source audit, host correctness tests and PS5-target default-off build completed; patch 0071 opt-in build and performance validation tracked separately. **No live game or console changes.** GTA IV-specific work remains paused.

## Current wait mechanisms (actual selected WSL source and app defaults)

| Path | Source | Normal behaviour | Existing controls | Risk/next measurement |
| --- | --- | --- | --- | --- |
| Vulkan event | `rpcs3/Emu/RSX/VK/vkutils/sync.cpp:wait_for_event` | Polls `VkEvent::status()` continuously when unset. Checks timeout, error state, then pauses. | `vk_event_spin_us=-1` **unbounded by default**; `vk_event_sleep_us=100` if finite budget selected, clamped by title's tuning parser. | Bounded sleep may reduce CPU time but increase signal-to-resume latency. Need signal/wait counts, wake latency and p95/p99 frame-time A/B/A. |
| Vulkan fence | `rpcs3/Emu/RSX/VK/vkutils/sync.cpp:wait_for_fence` | Nonzero timeout invokes blocking `vkWaitForFences` directly. **Zero timeout** invokes `vkGetFenceStatus` in a `VK_NOT_READY` / `utils::pause` spin loop until signalled; device loss errors propagate. | Previously no standalone zero-timeout sleep control. | Could tie up one host thread when delayed. Needs proof this is actually a hot frame-stalling path, rather than assuming polling frequency equals a GPU bottleneck. |
| RSX DMA completion | `rpcs3/Emu/RSX/RSXOffload.cpp:dma_manager::sync` | Polling by default; invokes `on_semaphore_acquire_wait` on renderer thread. | `rsx_dma_wait_us=0` by default; optional 1–2000 µs atomic wait after 64 polls. | Existing `check-ps5-rsx-wait.py` tests both renderer and non-renderer, progress callbacks, completion before wait, fault and shutdown sentinel. Do not skip callbacks. |
| RSX FIFO idle | `rpcs3/Emu/RSX/RSXThread.cpp` and PS5 `ps5_fastclock.c` | Configurable idle/yield behaviour and standard `rpcs3ps5_sched_yield` (short CPU pause ~2 µs, every-fourth OS yield, long idle ~0.5ms after which kernel sleep). | `rsx_fifo_yield=0` default, experimental opt-in; fastclock's RSX performance counters compiled OFF. | Separate FIFO self-jump spin vs other guest RSX work, avoid unconditional sleep/yield. |
| RADV queue/completion | Separate PS5 Vulkan driver and the title's weak symbols | App title declares `radv_spin_us=4000`, `radv_sleep_us=100` as tuning defaults; actual driver wait instrumentation is not established from those values. | Weak zero-valued `radv_ps5_stat_*` fallbacks in `app/ps5/src/ps5_tuning.c`. | A logged zero may mean an **unavailable counter** rather than no work. The current frontend check `&radv_ps5_stat_waits != nullptr` cannot prove instrumentation exists when the title itself supplies that weak definition. Need an explicit driver capability/version signal before trusting zero counters. |

## New exact-source offline gates

- `port/tests/check-ps5-vk-event-wait.py` extracts the **actual source body** of `vk::wait_for_event` and compiles it with host Vulkan status/timing stubs; tests already-set event, default unbounded spin, finite 0/50/200 µs budgets, delayed event signal, 3ms timeout, error propagation, spin/sleep/sample counter handling. **PASS**.
- `port/tests/check-ps5-vk-fence-wait.py` extracts the **actual source body** of `vk::wait_for_fence` and compiles both `PS5_VK_FENCE_TIMED_WAIT=0` and `=1` modes. Tests immediate fence completion, asynchronously delayed completion, explicit timed Vulkan wait conversion (microseconds → nanoseconds), a Vulkan wait returning timeout, error from `vkGetFenceStatus`, error from the bounded `vkWaitForFences` path, flush and frame-trace begin/end pairing. **PASS for both modes**.
- Existing `port/tests/check-ps5-rsx-wait.py` was rerun against selected WSL `RSXOffload.cpp` with title tuning parser and found correct original polling, opt-in bounded waits, renderer callback progress, completion-before-wait race, fault and sentinel shutdown paths, tuning clamp/file-deletion rollback. **PASS**.

These tests exercise real C++ wait **function bodies**, but run with **simulated Vulkan/OS/producer stubs on Linux**. They verify control-flow correctness under tested cases; they do **not** establish PS5 driver support, real device-loss/shutdown safety, GPU frame latency, or FPS. No full game/RSX submission is replayed.

## Patch 0071 — isolated speculative alternative, default OFF

Reversible patch `port/rpcs3-latest-patches/0071-PS5-opt-in-bounded-Vulkan-fence-wait.patch` adds `rpcs3/Emu/RSX/VK/vkutils/ps5_vk_fence_sleep.h` (default `PS5_VK_FENCE_TIMED_WAIT=0`). The normal fence wait is unchanged at compile time. Diagnostic `=1` mode changes only the **zero-timeout** Vulkan fence wait branch, as follows:

- After **64** consecutive `VK_NOT_READY` status checks, attempt `vkWaitForFences(..., timeout=100,000ns)` instead of continually polling.
- On `VK_SUCCESS`, finish the wait. On `VK_TIMEOUT`, continue polling; do not report completion. On driver errors, invoke the same fatal/error handler and return the status.
- A fence is a level-triggered completion state, so signal between the last poll and the bounded wait should cause the Vulkan API to return immediately. **Real PS5 driver behaviour still needs validation.**
- The feature is compile-time opt-in, does not modify guest sync state or the existing DMA/event paths, and has no runtime overhead while disabled.

`port/tests/check-ps5-vk-fence0071.py` confirms exact original-source archive, reversible forward/reverse patch application, and Clang C++20 compile gates for default OFF and explicit ON. `port/tests/check-ps5-vk-fence-wait.py` verifies both paths (including error from the bounded wait). Neither a CPU win nor a latency win is established.

## Next safety and performance gates

1. **Before any console installation**, verify the full PS5 process list shows both game and launcher stopped, save exact signed executable/paired mirror for rollback, and independently inspect every ELF PT_LOAD/PT_TLS region and the code mirror. This patch was intentionally **not** deployed.
2. Choose a **representative non-GTA-IV game** with sustained RSX/Vulkan fence waiting and warmed shaders/PPU/SPU caches. Measure actual zero-timeout fence calls and whether Vulkan driver wait is a meaningful contributor. Avoid over-optimizing a cold path.
3. Compare default OFF and diagnostic ON on the exact same scene/route and settings, preferably A/B/A. Measure average FPS, frame-time p50/p95/p99, thread-CPU usage and GPU completion/wakeup latency, and check renderer progress, shutdown, graphics/audio integrity and deadlocks.
4. If there is no performance evidence, keep the feature OFF. Independent Vulkan event tuning must also be measured, not bundled into the same A/B/A candidate. Do not interpret weak RADV zeros as a reliable benchmark.

**Current known console state from preceding test:** Original patch0064 gate0 paired title was last independently verified installed and both processes stopped; no new PS5 readback was requested or performed in this offline work. Source manifest patch count 71 reflects the WSL working source, not the installed title.
