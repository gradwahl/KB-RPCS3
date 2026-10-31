# GTA IV NPUB30702 — PS5 RPCS3 critical-path performance audit

<!-- latest-state:start -->
**Latest GTA IV PS5 patch0069 SPU reservation-page and producer diagnostic (2026-10-31): COMPLETE and SAFELY ROLLED BACK.** Two valid stationary outdoor 45s GTA IV NPUB30702 runs, Chiaki ON, MFC gate0/helper probes0, 150%/scheduler B/Mega SPU/XFloat Approximate/tuning0; FPS **28.77 and 26.78**, mean **27.775**, zero new SPU compilations. Across 23 complete ~4s windows, sampled 1/128 per worker/path **2,449 SPU waits**, **2,279 successful notifier transitions**, no table overflows. Of waits, **2,429 = 99.18%** on guest page **0x017F7000** (2,421 changed flag, 8 cleared reservation); 256 PPU-thread and 1,689 SPU-thread successful notifier samples hit this page. Other 20 wait samples were 0x017F8000. Notifier source is not necessarily the guest data writer or the cause of a particular wake. Raw FPS/wait-count correlation +0.663 across 4s windows; normalized by estimated displayed frames only +0.115. This strongly supports a coordination hotspot, **NOT a demonstrated frame bottleneck or FPS improvement**.

**Console NOW:** original patch0064 **gate0 matched control RESTORED** after guarded rollback. Independent full ELF PT_LOAD/TLS and exact code mirror SHA256 **e48a5c75cc3357d7f51474d1ded457e4d27e221c15fde446023538d8f48eda7b** PASS. Complete independent PS5 process listing confirms both game and launcher **CLOSED**. Patch0069 preserved in .spuwake0069-stage (ELF117439088 bytes, mirror74612497 bytes), backup slot empty; older 0068/0067/0066/0065 and gate1 stage preserved. Patch manifest count69 refers to WSL source, **not installed PS5**. No game saves/config/caches changed. Full handoff: game research/GTA-IV-SPU-reservation-page-attribution-20261031.md and results/gta4-spu-wakeup-20261031/spuwake0069-outdoor-combined.json. Next: identify exact 128B reservation line and actual PPU/SPU data-writer callsites in 0x017F7000, not speculate on TLS or atomic timeouts.
<!-- latest-state:end -->

Date: 2026-10-30
Status: **initial cross-subsystem source audit; root cause not yet proved.**
No PS5 configuration, executable or game data changed by this audit.

## What is established experimentally

- Under scheduler B / MEGA / Approximate XFloat / 150% scaling, same outdoor
  stationary scene, original pre-0054 executable: 24.60 and 28.08 FPS on
  consecutive 45-second rollback windows, mean 26.34 FPS.
- SPU insert-select=1: 28.60, 26.23 and 28.76 FPS over three valid
  45-second windows, mean 27.86 FPS. The JIT machine-code transformation was
  verified on five generated SPU code dumps, but a **causal FPS gain remains
  unproven**, due to strong natural scene/run variation and missing fresh
  A/B/A crossover.
- Patch 0054 RSX memcpy/reservation fast path: the A/B comparison showed no
  repeatable performance gain (26.42 FPS patched mean vs 26.34 FPS fresh
  unpatched rollback mean). Do not claim a win.
- Reducing the rendering scale from 150% to 100% in one matched comparison
  did not improve FPS (25.29 vs 24.77 FPS). This is **suggestive of a
  CPU/front-end constraint**, but one run does not rule out GPU/driver waits.
- At ~26.34 FPS, representative frame time is ~38 ms. For truly stable
  60 FPS the critical-path time must fall to <=16.67 ms, about a **2.28x
  throughput increase** or ~21.3 ms less latency for that representative
  frame. Independent thread CPU-time savings cannot simply be added together.
- Multiple SPU threads ~96–99% of a host core; RSX ~90–95%; GTA
  RenderThread ~81–83%. These are host thread CPU-utilisation, **not** a
  serial per-frame bottleneck breakdown.
- In warmed sections, sampled VM mprotect calls are typically near zero or
  only low tens per second; the first startup report's ~8000 calls/s and
  huge KiB/s represent an initial burst and should not be called the
  steady-state source of ~38 ms frames.
- Sampled PS5 core clocks averaged ~3330–3380 MHz over recent reports:
  no evidence of a ~2x clock reduction (not a thermal-throttling test).

## Scope inspected (not a claim of a line-by-line review)

Reviewed the latest PS5 port's app/frontend, PS5 fast clock/scheduler, RPCS3
SPU JIT and MFC/DMA, RSX FIFO, RSX vertex/index upload, Vulkan command
submission and frame counting, plus existing telemetry and the 55-patch port
manifest. There are >1,500 tracked C++ headers/sources in the upstream
checkout; a literal exhaustive line-by-line audit is not a sensible substitute
for measuring the critical path.

The console is currently on the **original pre-0054 executable and default
SPU tuning** (no ps5-tuning.txt). The local linked symbol ELF used below
contains the experimental 0054 build, however: symbol matches for addresses
from the original installed console executable must be treated as
**provisional** until checked against its exact matching ELF.

## Findings, source-backed

### 1. RSX CPU activity includes deliberate spin/yield — HIGH measurement priority
Sources:
- `ps5/src/ps5_fastclock.c` in `ps5-rpcs3-app-latest`:
  `rpcs3ps5_sched_yield` can busy-spin for ~2 us, use the real
  `scePthreadYield` periodically, and sleep after a ~0.5 ms idle burst.
  `rpcs3ps5_clock_gettime` uses a TSC fast path for monotonic clocks.
- `rpcs3/Emu/RSX/RSXThread.cpp`: `performance_counters.state` and
  `thread::get_load()` account FIFO idle time (~30-frame average).
- `rpcs3/ps5/ps5_frontend.cpp`: `PS5 CPU` reports thread-core usage
  but does not log RSX FIFO load, per-thread runnable/waiting time,
  or time in yield/sleep.

Inference: an RSX thread at 93% CPU may be actively decoding/drawing,
polling for FIFO packets, or spinning in handshakes. Its percentage
alone does **not** prove a graphics CPU bottleneck. First diagnostic:
log FIFO state fractions and RSX productive processing vs wait time,
and instrument the PS5 fastclock yield/sleep counts with low-overhead
aggregated counters.

### 2. SPU host JIT execution and MFC/channel waits — HIGH candidate
Sources:
- `rpcs3/Emu/Cell/SPUThread.cpp`:
  `spu_thread::cpu_task()`, `get_ch_value()`,
  `process_mfc_cmd()`, `do_dma_transfer()`.
- `rpcs3/Emu/Cell/SPULLVMRecompiler.cpp`:
  JIT guest execution; existing disabled `spu_insert_select` and
  `spu_narrow_ls_store` optimisations.
- `Utilities/Thread.cpp`:
  400 SIGUSR1 samples per selected thread in a ~2-second profile, named
  guest SPU JIT functions and offset export.

Evidence: some profile windows attribute a substantial share of SPU
samples to guest JIT code, others to helper/MFC/channel addresses.
One SPU JIT codegen inefficiency (variable-index stack-vector insert)
was *demonstrably* eliminated by insert-select. This does not determine
which thread holds up the game’s frame or the maximum possible FPS.

Need: per-SPU busy/idle, channel/MFC command counts, completion/wait
duration, mailbox/reservation failure counts, DMA bytes and wait time.
Preserve semantic correctness, don't bypass synchronisation speculatively.

### 3. CPU-side RSX vertex/index staging on the serial path — HIGH candidate
Sources:
- `rpcs3/Emu/RSX/Core/RSXDrawCommands.cpp`:
  `draw_command_processor::write_vertex_data_to_memory` loops through
  draw attribute layouts and calls `dma_manager().copy` for each
  persistent block.
- `rpcs3/Emu/RSX/VK/VKVertexBuffers.cpp`:
  prepares/uploads index and vertex data to Vulkan ring buffers,
  with cache-miss tracking and map/unmap paths.
- `rpcs3/Emu/RSX/Common/BufferUtils.cpp`:
  `write_index_array_data_to_buffer` handles endian conversion,
  min/max indices, restart and primitive expansion.
- `rpcs3/Emu/RSX/RSXOffload.cpp`:
  synchronous copy path when `Multithreaded RSX: false`,
  which the captured GTA IV config reports.

Several repeat RSX sampled addresses map **provisionally** (linked
0054 ELF offset by 0x400000) into these paths:
`0x1392670` vertex upload,
`0x1378e8d` index conversion,
`0x13637c9` FIFO fetch. A matching unpatched ELF is required to
confirm precise symbol names/offsets. Patch 0054's no-op lock removal
did **not** establish any speedup; the bottleneck, if here, may be the
amount of per-draw work, driver-side mapping, draw counts or serial
dependencies—not that particular guard.

Need: per-frame draw counts, indexed/nonindexed counts, vertex/index
source bytes, per-stage CPU elapsed time and cache-hit/miss rates.
Use coarse aggregation or sampled timings rather than adding high-
overhead timestamps to every tiny operation in release builds.

### 4. Vulkan submit/present and GPU waits — UNRESOLVED
Source:
- `rpcs3/Emu/RSX/VK/VKGSRender.cpp`:
  `VKGSRender::close_and_submit_command_buffer` synchronises MM,
  calls `dma_manager::sync()`, manages render passes and submits
  Vulkan command buffers; `sync` failure can force a flush.
- `rpcs3/ps5/ps5_gs_frame.h`:
  the host frame `flip()` increments `g_ps5_flips` and records a
  timestamp; fixed client dimensions are 3840x2160.
- `rpcs3/ps5/ps5_frontend.cpp`:
  `PS5 FPS` counts host frame callbacks, **not a GPU timestamp** or
  proof of finished physical display presentation.
  RADV wait counters have weak linkage/fallback values; zeros cannot
  establish absence of GPU stalls.

Inference: reduced RSX render scale alone cannot discriminate among
CPU queue preparation, GPU work, 4K swapchain/present conversion or
sync/waits. Need GPU timestamp queries (when supported) and durations
for queue submit, fence waits, image acquisition and presentation.
Do not assume `dma_manager::sync` is hot: with multithreaded RSX
disabled there may be no queued offloader work.

### 5. Scheduler and profiler perturbation — MEASUREMENT RISK
Sources:
- `Utilities/Thread.cpp`: PS5 scheduling builds shared affinity
  masks assuming adjacent logical CPUs are SMT siblings
  (`kPs5Sibling=1`). Per-thread CPU percentages don't prove
  individual physical core ownership or absence of SMT interference.
- `Utilities/Thread.cpp` and `rpcs3/ps5/ps5_frontend.cpp`:
  the 400-sample thread profiler sends SIGUSR1 about every 5 ms,
  in rotating 2-second intervals during gameplay.

Need: actual PS5 allowed logical CPU topology, sibling utilisation,
core migrations and possible contention, and a **profiler disabled**
control so measurement overhead is quantified before drawing
conclusions from small FPS changes. FPS capture windows must validate
actual runtime settings and reject compilation-heavy periods.

### 6. Frame statistics measure only flip intervals — METRICS LIMIT
Source: `ps5_frontend.cpp` `ps5_frame_stats()` logs
p50/p95/p99 intervals between callbacks. Per-45-second JSON files
are **means of window percentiles**, not pooled all-frame percentiles
nor a critical-path breakdown. The callback timestamp ring has its
own separate publication and count; it does not measure guest PPU
frame work, SPU work, CPU RSX, queue wait, GPU execution or native
present latency individually.

Need: a frame-scoped asynchronous event timeline with monotonic IDs
from guest flip through RSX draw and Vulkan submit/present; record
all stages without stalling the GPU.

## Next actions in order

1. Build **diagnostic-only instrumentation**, with all candidate
   optimisations OFF and original behavior unchanged. Aggregate into
   one `PS5 PERF` report every ~5 s:
   * RSX FIFO nonempty/idle time, draw call counts and vertex/index
     upload CPU time/bytes/cache misses.
   * DMA queued/processed counts and sync-wait CPU time, including 0
     explicitly if no offloading is active.
   * SPU guest JIT vs channel/MFC/wait durations or samples with
     reliable attribution.
   * Vulkan command recording/queue-submit/fence/present durations,
     plus GPU timestamps if driver support permits.
   * PS5 yield/sleep counts and profiler-on/off marker.
2. Capture moving and stationary workload with a deterministic
   route/replay if feasible; collect per-frame distributions and
   multiple short trials of the same builds. First verify
   profiler-on/off measurement overhead.
3. Classify frame-bound type: guest SPU/PPU, RSX CPU preparation,
   CPU synchronization/wait, GPU driver work, or native presentation.
4. Pick and test **one** semantic-preserving optimisation in the
   dominant critical-path stage. Test A/B/A/B and visual/physics/audio
   correctness before claiming success.
5. Re-evaluate stable 60 FPS feasibility after measuring how the
   ~38-ms representative critical path divides into its actual
   components. No current evidence justifies claiming a 2.28x gain.

## Audit outcome

**No single root cause is proven.** The leading competing explanations
are guest SPU execution/synchronisation and serial CPU RSX processing;
the apparent RSX core saturation may include polling. GPU and
presentation back-pressure cannot yet be excluded. The most valuable
next change is *better measurement*, not another blind optimisation.

References: local captured benchmark JSON/log files in
`results/gta4-scheduler-20261030/`, existing snapshots in
`results/gta4-spu-jit-20261030/` and the tracked source paths
specified above.

## Diagnostic RSX performance build (patch 0056) — October 30, 2026

Prepared a **PS5-only, diagnostic-only** patch:
`port/rpcs3-latest-patches/0056-PS5-diagnostic-RSX-FIFO-upload-DMA-Vulkan-timings.patch`;
manifest `port/rpcs3-latest.json` has **56 patches**.

In the upstream WSL checkout, new header
`rpcs3/Emu/RSX/ps5_rsx_perf.h` aggregates relaxed-atomic CPU-wall
clock counts/durations. Instrumented paths:

| Counter logged under `PS5 PERF` | Source & interpretation |
| --- | --- |
| FIFO sampled running vs idle calls and microseconds | `RSXThread.cpp` samples **1 in 128** `run_FIFO()` iterations and classifies by state *after* the call. Not a precise productive/idle fraction or frame time |
| Vertex calls and microseconds | `Core/RSXDrawCommands.cpp` `write_vertex_data_to_memory` execution (guest copies, register data, etc.) |
| Index calls, KiB and microseconds | `VK/VKVertexBuffers.cpp` around `write_index_array_data_to_buffer`; KiB is **source-index input size**, not total DMA or GPU transfer |
| DMA sync calls and microseconds | `RSXOffload.cpp` `dma_manager::sync`; includes no-work checks and possible waiting |
| Vulkan close/submit calls and microseconds | `VKGSRender.cpp` `close_and_submit_command_buffer` CPU wall time |
| Vulkan queue submit calls and microseconds | Nested primary `m_current_command_buffer->submit` CPU wall time; **included in close/submit**, not additive |

The existing PS5 frontend watchdog consumes and reports these counters
once every ~4–6 seconds in `SYS: PS5 PERF:` lines, with the real window
duration; there is no logging per draw/command. The FIFO counter samples
only 1/128 iterations to limit overhead. **These are not GPU timestamps,
guest frame phase timings, or a causal breakdown of each completed
frame.** Stage intervals can overlap or nest and instrumentation can
perturb FPS, to be measured separately. No RPCS3 guest timing,
gameplay rules, GPU sync semantics, scheduler settings or patches are
changed by the instrumentation.

**Source validation:**
- All **six** targeted PS5 C++ translation units compiled successfully
  (RSXThread, RSXOffload, RSXDrawCommands, VKGSRender,
  VKVertexBuffers, ps5_frontend).
- `port/tests/check-ps5-rsx-perf.py`: compiled & executed a native
  two-translation-unit harness for shared atomic counters, duration,
  bytes, reset, and separate category tests: **PASS**.
- `tools/gta4-rsx-perf.py`: diagnostics log parser; synthetic
  log validation and corrected CPU milliseconds/second conversion:
  **PASS**. Treat sampled FIFO counts separately from total times.
- Isolated Git-index replay test: patch 0056 applies cleanly on top
  of patches 0054 and 0055 without modifying the developer's real
  index. Important: one upstream file (`RSXDrawCommands.cpp`) is
  CRLF; exact original newline convention was preserved in patch.
- Full `JOBS=3 bash tools/wsl-build-latest.sh` build **succeeded**:
  compiled core, native TLS, signed PS5 title, staged all title assets
  and all **nine** packaging checks passed. Converted ELF includes the
  literal `PS5 PERF` format string.

**Verified local diagnostic build files (NOT INSTALLED):**
```text
~/work/ps5-rpcs3-app-latest/dist/PPSA99303/eboot.bin
  114,103,342 bytes
  SHA256 676e9d774dc5c1d53c53e43ba19546f084155c7b558334df655f03b82d35e632
~/work/ps5-rpcs3-app-latest/dist/PPSA99303/rpcs3ps5-text.bin
  74,602,705 bytes
  SHA256 1fe323e3f665e7ee0130b8c8f7289ca9f1709a4cd90ad28ce87f4b77ba101494
~/work/ps5-rpcs3-app-latest/build/ps5/eboot.elf
  117,425,528 bytes
  SHA256 ca7e1a2acaaf2d8580f3814b382ccba8fdef408467f8dda4b52cc5a48af6e802
```

The diagnostic title was built from the **full 56-patch series**, so it
also contains patch 0054 (RSX memcpy fast path, not proven to improve
FPS) and patch 0055 (SPU narrow-store checker correctness fix;
the narrow-store optimisation still defaults OFF). Do not claim this
build is bit-identical to the pre-0054 console control except for
instrumentation. Its primary purpose is diagnostic stage timing, not
performance A/B against the old executable.

**Console safety / next action:**
The user has **not yet confirmed GTA IV and KB-RPCS3 closed** for
installing this build. No executable or mirror was uploaded/staged
or changed on the PS5. A read-only check using new helper
`tools/deploy-gta4-rsx0056.py status` reported original live mirror
size 74,601,553 bytes, and **no patch 0056 stage/backup**. Previous
patch 0054 stage files remain unaffected by this separate helper.
The new helper hardcodes both locally built hashes, checks the console
process list before any stage/activate/rollback, verifies the staged
downloads and decrypted ELF load/TLS segments, and manages matched
pair backup and rollback under `.rsx0056-stage` and
`.before-rsx0056-20261030` names.

**Only once the user explicitly confirms the game and launcher closed**,
stage the two files using:
```bash
python3 /mnt/c/Users/Callum/Documents/GitHub/KB-RPCS3/tools/deploy-gta4-rsx0056.py stage
```
Then independently verify stage status and run `activate` after the
same process-state check. Do not change game saves/patch configuration.
Fresh-launch GTA IV at default `spu_insert_select=0` and existing
B/MEGA/150% settings, allow compilation to finish, then collect
45-second logs with `tools/gta4-scheduler-ab.py` using a new
`--label` and `--expected-tuning spu_insert_select=0`.
Run `tools/gta4-rsx-perf.py` on captured logs for per-window
totals, and inspect FIFO sampled counts/calls, vertex/index ms,
DMA sync, Vulkan CPU submission and existing JIT snapshots.
For comparison, also quantify sampler-on/off overhead in a later
separate controlled build. When finished, **close the title** and use
`tools/deploy-gta4-rsx0056.py rollback` to restore the original
matching executable/mirror pair.

Snapshot and exact checksums saved in ignored
`results/gta4-rsx-perf-20261030/build.json`.

### Patch 0056 diagnostic pair INSTALLED on PS5 — October 30, 2026 ~03:41 UTC

The user explicitly confirmed GTA IV and KB-RPCS3 were **closed**.
`tools/deploy-gta4-rsx0056.py stage` then `activate` both completed
successfully, each process-state check confirmed no `eboot.bin` or
launcher was running. Both files were downloaded for verification
**before activation**, and both live files were independently verified
**after activation**. The executable downloaded over FTP is a decrypted
ELF; its load + TLS segment bytes were compared with the locally
converted ELF, not falsely SHA-compared against its signed SELF.
The code mirror's exact SHA-256 matched the local signed build.

Live console paths now contain the diagnostic patch 0056 pair:
```
/data/homebrew/PPSA99303/eboot.bin         (FTP decrypted ELF 117,425,528 bytes)
/data/homebrew/PPSA99303/rpcs3ps5-text.bin (74,602,705 bytes;
  SHA-256 1fe323e3f665e7ee0130b8c8f7289ca9f1709a4cd90ad28ce87f4b77ba101494)
```
The **original pre-0054** pair has NOT been deleted and can be
recovered via `tools/deploy-gta4-rsx0056.py rollback` *after
closing the game*:
```
eboot.bin.before-rsx0056-20261030         (FTP-decrypted ELF 117,425,144 bytes)
rpcs3ps5-text.bin.before-rsx0056-20261030 (74,601,553 bytes)
```
A separate post-installation `status` and FTP readback confirmed:
live/stage/backup pairs have correct sizes; stage paths no longer
exist; GTA IV custom settings still scheduler B / Mega SPU /
Approximate XFloat / resolution 150% / clocks 100% / frame limit 60 /
strict rendering false. `rpcs3/ps5-tuning.txt` is **absent**,
meaning insert-select and narrow-store experimental options default
OFF. No game files, saves or title patches altered.

**No in-game runtime/PS5 PERF values tested yet.** Next: user must
relaunch KB-RPCS3, boot GTA IV, go to the same outdoor save/camera,
wait until SPU compilation settles and reply `RSX diagnostic ready`.
Then run a new 45-second capture (new label, B scheduler, expected
resolution 150%, expected tuning all three SPU flags 0), check
that current launch log contains `PS5 PERF:`, and parse it using
`tools/gta4-rsx-perf.py`. Compare idle vs productive FIFO sampled
calls, vertex/index preparation, DMA sync and Vulkan CPU submission.
These counters do not report GPU execution and the full 0056
build includes 0054 and 0055 patches; do not assume that only
instrumentation changed compared with the original console build.
After experiment close the game and run `rollback`, then independently
verify restored pair.

## First real patch-0056 RSX diagnostic results — 2026-10-30 ~03:45–03:48 UTC

The user said "RSX diagnostic ready" with GTA IV already loaded at the
same stationary outdoor view. Captured two verified 45-second windows
with patch 0056 live, scheduler B, 150% resolution, 60 frame cap,
normal 100% clocks, MEGA SPU and all three SPU experiment flags OFF.
Both captures passed `tools/gta4-scheduler-ab.py` validation and
reported **zero new SPU block compilations**.

Files:
- `results/gta4-scheduler-20261030/B-B-rsx0056-diagnostic-run1.{json,log}`
  (the first filename has a repeated "B" because the label included B);
- `results/gta4-scheduler-20261030/B-rsx0056-diagnostic-run2.{json,log}`;
- `results/gta4-rsx-perf-20261030/run1-summary.json` and
  `run2-summary.json`;
- `results/gta4-rsx-perf-20261030/capture-analysis.json` with
  aggregated 44.5-second CPU stage rates, approximate CPU ms/frame and
  symbolized recent RSX sample hotspots.

`tools/gta4-rsx-perf.py` now supports `--capture-only` to read
exactly the `windows` count from the matching valid FPS capture JSON
and select the last N `PS5 PERF` windows. The captured logs otherwise
contain the entire GTA IV launch/warmup interval; interpreting all
38 or 64 windows would mix benchmark and non-benchmark activity.
The analyser's earlier unit conversion issue was fixed and synthetic
input validated before parsing real data.

| Observed metric | Diagnostic run 1 | Diagnostic run 2 |
| --- | ---: | ---: |
| Average window FPS | **24.71** | **22.94** |
| Window-mean 1% low FPS | 21.71 | 19.92 |
| Window-mean median frame interval (ms) | 40.40 | 43.48 |
| p95 frame interval (ms) | 44.14 | 47.78 |
| p99 frame interval (ms) | 46.08 | 50.30 |
| New SPU compilations during capture | 0 | 0 |
| Number of `PS5 PERF` windows used | 9 | 9 |
| Total PERF window duration (s) | 44.576 | 44.546 |

**Measured CPU wall time per second**, in milliseconds per second:
- Vertex staging `write_vertex_data_to_memory`: **68.11 / 62.08**
- Index conversion `write_index_array_data_to_buffer`: **23.11 / 21.12**
- DMA sync (including calls with no queued DMA): **2.09 / 1.89**
- Vulkan command buffer close + submit: **17.37 / 16.10**
- Vulkan primary queue submission **nested within close+submit**:
  **17.25 / 15.99**, **not additive**
- Sampled FIFO iterations labelled running: **7.02 / 6.37**,
  and labelled nonrunning/idle: **1.57 / 2.07**. These are the
  1/128 sampled iterations' *observed* durations only, not
  the complete FIFO wall time; don't divide by FPS or add them
  as a whole CPU/GPU frame breakdown. A sampled "running" FIFO
  state does not establish that a real guest command was processed.

**Approximate CPU ms per rendered frame** (normalised by mean FPS,
not a real time-correlated per-frame critical-path measurement):
- Vertex staging: **2.757 / 2.706 ms**
- Index conversion: **0.935 / 0.921 ms**
- DMA sync: **0.084 / 0.083 ms**
- Vulkan close+submit: **0.703 / 0.702 ms**
- Vulkan primary submission: **0.698 / 0.697 ms**, included above

Approximate distinct measured stage total excluding nested Vulkan
submission is ~**4.48 / 4.41 ms** in the two runs. Their frame
intervals remain ~40–44ms. So these **specific observed stages
cannot by themselves explain the entire low FPS**. The unmeasured
guest/SPU/PPU execution, RSX FIFO command dispatch / possible polling,
texture/query work, actual GPU execution and present/back-pressure
remain candidates. Stages may nest, overlap or run on different
threads; do not subtract this sum from a single frame to claim a
numerical "unaccounted 36ms" on a serial critical path.

The most useful cross-run finding is **stable work per frame despite
FPS variability**. The vertex staging path had ~1759.9 / 1759.5
calls per rendered frame; index conversions ~3062.3 / 3032.5;
Vulkan close/submits ~2.0 / 2.0. Vertex/index/Vulkan CPU cost
per frame likewise remained within ~2%. This suggests the FPS
change is not from more work in those particular sub-stages.

**Exact JIT/static code symbol mapping** is now possible using
`~/work/ps5-rpcs3-app-latest/build/ps5/link/llvm-pie.elf`,
the linked object that produced the installed patch-0056 pair;
the previous symbolisation using the patched linker ELF on the
original console build was provisional. Resolving the most frequent
RSX sampling IPs minus the ELF's 0x400000 image base gives:
- `tsc_now` in the PS5 fast-clock implementation,
  `ps5/src/ps5_fastclock.c`;
- `rsx::draw_command_processor::write_vertex_data_to_memory`,
  `RSXDrawCommands.cpp`;
- `write_index_array_data_to_buffer`, `BufferUtils.cpp`;
- `rsx::FIFO::FIFO_control::fetch_u32` and
  `rsx::thread::run_FIFO`, `RSXFIFO.cpp`;
- `vk::query_pool_manager::get_query_result`,
  `VKQueryPool.cpp`;
- `vk::viewable_image::get_view`, `image.cpp`;
- `rsx::rsx_state::decode`, `rsx_methods.cpp`;
- RADV query/descriptor/graphics dynamic state code.

Among the four most recent 400-sample RSX profiling windows per
log (not perfectly aligned to the 45-second capture boundaries),
addresses associated with `tsc_now` account for roughly
**255/1600 (~15.9%) and 265/1600 (~16.6%)** samples respectively.
**These are samples, not the share of frame latency.**
They support a next targeted audit of fast-clock calls and
spin/yield behavior, but do not prove clock conversion itself is
expensive. `PS5 CPU` still reports multiple SPU threads ~90–98%
and RSX ~89–94%; this is not a per-frame attribution.
`PS5 WAITS` RADV counters continue showing zeros but are weak
fallback counters; zero does not exclude actual driver stalls.
Warmed `PS5 mprotect` is typically 0 calls/s.

**Performance caveat**: diagnostic FPS 24.71/22.94 is below
some previous control runs (24.60/28.08 mean 26.34) but cannot
yet be attributed to profiler overhead: non-deterministic GTA IV
workload, elapsed runtime differences, and the diagnostic title
being rebuilt from patches 0054+0055 as well as 0056 confound
cross-build comparison. A profiler-disabled *same-code* build
comparison and/or reversions are needed.

**Next recommended engineering step**: separate actual executed
RSX guest commands/draws from busy/empty/spinning FIFO return codes
in `RSXFIFO.cpp`; aggregate PS5 fast-clock calls by
`clock_gettime` vs `sched_yield`, counts of actual sleeps and
spin duration; profile guest SPU/PPU stalls and RSX subroutine
time. Avoid rewriting hot code or asserting a reliable FPS gain
until these are measured. GPU timestamps/fence/present latency
remain unmeasured and worth investigating separately.
The console currently has diagnostic patch 0056 **running**:
**do not touch binary files** unless the user fully closes
GTA IV and KB-RPCS3 and `tools/deploy-gta4-rsx0056.py rollback`
passes its safety check. Saved old executable and code mirror
remain on the console under `.before-rsx0056-20261030`.

## RSX diagnostic iteration 2 — patch 0057 deployed, 2026-10-30 04:03 UTC

User confirmed GTA IV and KB-RPCS3 completely **closed**.
Checked console process list before staging **and before activating**:
no `eboot.bin` or launcher running.

**Source/build**: patch
`port/rpcs3-latest-patches/0057-PS5-count-sampled-FIFO-kinds-and-fastclock-branches.patch`
applies cleanly on top of 0054–0056 in an isolated Git index;
`port/rpcs3-latest.json` now declares 57 patches.
Modified RSXFIFO.cpp, RSXThread.cpp, ps5_rsx_perf.h and
ps5_frontend.cpp in upstream WSL source; the corresponding app
fastclock implementation is tracked directly at
`app/ps5/src/ps5_fastclock.c`.

**New diagnostic-only counters**:
- Every **128th** `run_FIFO` call, classify its **first** fetched
  word as method, NOP, EMPTY, BUSY, self-jump or other flow. Record
  that invocation's sampled CPU duration in
  `PS5 FIFO2: window ...`. This is neither the total number of
  guest RSX methods nor an exact percent of idle/productive time.
  A `run_FIFO` call may process multiple methods.
- PS5 fastclock increments a thread-local counter on
  `rpcs3ps5_clock_gettime` and batches each **1024** clock
  calls to a global relaxed atomic; similarly batches each
  **256** yield decisions as spin (2 µs), OS yield, or sleep.
  Logs `PS5 CLOCK2` once per PS5 frontend watchdog window.
  Totals cover **all threads**, not RSX alone, and can lag by
  1023 clock calls / 255 yields **per thread** at the report edge.
  The clock/yield control-flow decisions were not changed.
- Original patch 0056 `PS5 PERF` counters remain active.
  `tools/gta4-rsx-perf.py` now supports and validates matching
  FIFO2/CLOCK2 lines with `--capture-only`. Synthetic parsing
  and unit tests PASS.

**Testing/build**: 3 affected C++ translation units compiled;
app clock C implementation compiled; host native harness
`port/tests/check-ps5-fastclock-counters.py` confirms 2300
fast clock calls produce 2048 completed batches and 1024
categorized yields produce exactly 1024 reported outcomes.
Full `JOBS=3 bash tools/wsl-build-latest.sh` compiled,
linked, signed, checked native TLS and all nine package paths.
Both log strings `PS5 FIFO2` and `PS5 CLOCK2` exist in matching
linked ELF. Matching symbol ELF archived to
`/home/callum/work/rsx0057-link-20261030.elf`.

**Installation verified on PS5**:
`tools/deploy-gta4-rsx0057.py stage` and `activate`
both succeeded. Signed local files:
- `eboot.bin`: 114,105,726 bytes,
  SHA256 `376463b5a2a065c701c5f228d2fec0f8b8a7915864f0b2fc94c97194a284c7a7`
- `rpcs3ps5-text.bin`: 74,604,113 bytes,
  SHA256 `5c4a13b5a6489867ed7b31fe97c18b1b1807d37023cacaccd72be3878059fa90`
- locally converted ELF: 117,425,960 bytes,
  SHA256 `4605102041ff623470867a0c129d54c1cc9a7817ef4cc085b53f6033f158c5e7`.

Staged binaries were read back for exact text-mirror hash and
ELF load/TLS segment comparison, then the installed live files
were verified a second time after activation. PS5 FTP shows
live executable decrypted ELF 117,425,960 bytes and live mirror
74,604,113 bytes. **No patch 0057 stage files remain.**

**TWO FULL ROLLBACK LEVELS PRESERVED**:
1. Patch 0056 pair:
   `eboot.bin.before-rsx0057-20261030` (decrypted ELF
   117,425,528 bytes) and
   `rpcs3ps5-text.bin.before-rsx0057-20261030`
   (74,602,705 bytes). To restore, first close the game and
   use `python3 tools/deploy-gta4-rsx0057.py rollback`.
2. Original pre-0054 pair:
   `eboot.bin.before-rsx0056-20261030` (decrypted ELF
   117,425,144 bytes) and
   `rpcs3ps5-text.bin.before-rsx0056-20261030`
   (74,601,553 bytes). After safely restoring 0056 as live,
   run the 0056 helper's `rollback` with the title closed
   to restore the original build. **Do not directly skip
   restoration steps**.

Independent console FTP check confirms GTA IV custom config
still RPCS3 Scheduler, MEGA, Approximate, resolution scale **150%**,
100% clocks, frame limit 60, Strict Rendering false and
**no ps5-tuning.txt** (SPU insert-select/narrow experiments OFF).
No game saves or game data were edited.

**Next**: user launch KB-RPCS3 and GTA IV, stand stationary at same
outdoor scene/camera, let SPU compile settle and reply
`RSX FIFO ready`. Then run
`tools/gta4-scheduler-ab.py capture`, mode B,
expected-resolution 150, expected tuning
`spu_insert_select=0`, `spu_narrow_ls_store=0`,
`spu_narrow_ls_check=0`; new label `rsx0057-fifo-run1`,
at least 2 repeat 45-second captures. Require valid runtime
and zero new SPU compilations. Parse using
`tools/gta4-rsx-perf.py --capture-only`.
Also verify both new log marker types appear in capture before
trusting new metrics. None of 0057's new performance observations
have yet been measured in gameplay. Potential overhead of adding
counter checks is not isolated until a controlled profiler-off
A/B; cannot claim an FPS gain.

## Patch 0057 real GTA IV captures — 2026-10-30 04:08–04:10 UTC

User said `RSX FIFO ready`; the PS5 was running installed patch 0057, same
stationary GTA IV outdoor camera. Recorded **two valid, independent 45-second
captures** using `tools/gta4-scheduler-ab.py`, scheduler B, Mega SPU,
150% resolution and all three experimental SPU flags OFF; zero new SPU
compilations during either measurement.

Files:
- `results/gta4-scheduler-20261030/B-rsx0057-fifo-run1.{json,log}`
- `results/gta4-scheduler-20261030/B-rsx0057-fifo-run2.{json,log}`
- `results/gta4-rsx-perf-20261030/fifo-0057-run1-summary.json`
- `results/gta4-rsx-perf-20261030/fifo-0057-run2-summary.json`
- `results/gta4-rsx-perf-20261030/fifo-0057-combined.json`
The capture-only parser uses the last **9** aligned `PS5 PERF`,
`PS5 FIFO2` and `PS5 CLOCK2` windows from the full game log; each
log contains 38+ windows including warm-up, and 9 windows span ~45 s.
The sampled FIFO category total agrees with the existing running+idle
sample count to within **1** call in either capture.

| Metric | Run 1 | Run 2 |
|---|---:|---:|
| Valid capture, new SPU compilations | yes, 0 | yes, 0 |
| Average of FPS windows | **23.50** | **23.69** |
| Mean 1% low FPS | 20.32 | 21.13 |
| Median window frame interval (ms) | 42.81 | 42.26 |
| p95 window frame interval (ms) | 47.04 | 45.33 |
| p99 window frame interval (ms) | 49.58 | 47.41 |
| Sampled FIFO first reads | 1,168,063 | 1,223,371 |
| First-read method (%) | **71.47** | **71.27** |
| First-read NOP (%) | **26.58** | **26.74** |
| First-read EMPTY (%) | 0.86 | 0.91 |
| First-read BUSY (%) | 0 | 0 |
| First-read self-jump (%) | 0.18 | 0.17 |
| First-read other flow (%) | 0.91 | 0.90 |
| Global `rpcs3ps5_clock_gettime` calls/s | **1,360,204** | **1,361,077** |
| Global 2-us spin/yield decisions/s | 21,960 | 22,848 |
| Global OS yield decisions/s | 7,116 | 7,402 |
| Global sleep decisions/s | 732 | 774 |

**Interpretation:** 1-in-128 sampled **first reads** are predominantly
normal method command packets, then NOPs. The hypothesis that an
overwhelming number of those first FIFO reads return EMPTY or BUSY
is **not supported** under these stationary conditions. This
classification does **not** capture all later method words processed
by a single `run_FIFO` invocation, all guest FIFO packets, or
time spent in other RSX paths, nor does it prove the RSX execution
thread never waits. The reported sampled duration is entire
`run_FIFO` invocation and can include much more work than the
classified first packet.

**Critical instrumentation confound discovered and verified**:
`ps5_rsx_perf::timer` invokes `::clock_gettime(CLOCK_MONOTONIC)`
on entry and exit, and sampled FIFO iteration timing uses two more.
In the exact patch 0057 matching ELF
`/home/callum/work/rsx0057-link-20261030.elf`, `llvm-nm-19`
reports **both `clock_gettime` and `rpcs3ps5_clock_gettime`
at 0xEE560**, confirming the alias/rebinding and that every
instrumentation `now_ns` contributes to our fast-clock counters.

Using the observed counts per second from two capture windows:
- Run 1 timing probes necessarily introduce **~470,852 calls/s**,
  **34.6%** of the logged 1,360,204 calls/s.
- Run 2 probes introduce **~478,306 calls/s**, **35.1%** of the
  logged 1,361,077 calls/s.

Subtracting those specific known probes leaves **~889,352** and
**~882,771 calls/s** respectively from other call sites. Those
remaining calls may still include diagnostic, logging, or other
measurement overhead; they cannot all be attributed to unmodified
guest workloads. These are **call-count shares**, not demonstrated
percentages of CPU runtime or frame latency. The fastclock function
counts all RPCS3 host threads, not RSX alone. Its per-thread 1024
clock / 256 yield batching may introduce small lag at window
boundaries, negligible for broad rates but not exact per-frame values.

Timing stage CPU wall time per rendered frame (not a serial
critical-path breakdown) remains consistent:
- vertex 2.889 / 2.907 ms
- index 0.991 / 1.001 ms
- DMA sync 0.098 / 0.097 ms
- Vulkan close+submit 0.710 / 0.694 ms
- Vulkan queue submit nested in close+submit: 0.705 / 0.689 ms
These specific stages do not by themselves explain ~42 ms
frame intervals. Stage durations may nest and cannot simply
be subtracted from frame time.

Patch 0057 FPS average **23.60**, versus patch 0056 24.71/22.94
average **23.83**; different runs, scenario drift, plus
additional instrumentation mean **no causal FPS overhead conclusion**
can be drawn. The reporter's signal-interrupt sampler also has
unquantified effect.

**Next engineering recommendation:** use **per-thread batched
clock counts**, plus a profiler-on/off same-source A/B/A control,
before modifying PS5 fastclock conversion; focus on RSX CPU command
decode, guest SPU/PPU handshakes and GPU/driver waits in parallel.
Do **not** prioritise changing the FIFO EMPTY polling loop based on
these results. If pursuing a workload reduction in RSX, instrument
processed method words per `run_FIFO` and serial per-frame stages
rather than count method first reads as commands.

No additional PS5 files were changed during captures. Console
still has patch 0057 active; **DO NOT attempt a rollback until GTA IV
and KB-RPCS3 are fully closed.** The user can move the camera now.

## Patch 0058 — profiler-disabled overhead control installed, October 30 2026 ~04:21 UTC

User explicitly confirmed **KB-RPCS3 and GTA IV closed** at 04:14 UTC.
Process-list checks confirmed no live `eboot.bin` or launcher before
staging and activation.

**Purpose:** identify combined diagnostic/profiler overhead by comparing
two original patch-0057 ON captures (**23.50 and 23.69 FPS**, same
stationary outdoor GTA IV 150% scene, zero new SPU compilations) with
new patch-0058 OFF captures to be recorded. The OFF build is compiled
from the same upstream base and existing code patches, with only
extra diagnostic callsites and the rotating interrupt sampler disabled.
This is **not** a performance optimisation, and a two-build A/B
comparison still cannot prove causality without crossover controls.

**Source/build details:**
- New `port/rpcs3-latest-patches/0058-PS5-disable-RSX-diagnostics-for-overhead-control.patch`
  (isolated Git-index replay on top of patches 0054–0057 verified);
  manifest patch count 58.
- Shared `PS5_RSX_PERF_ACTIVE=0` compiled in
  `rpcs3/Emu/RSX/ps5_rsx_perf.h` (WSL latest checkout)
  and `app/ps5/src/ps5_fastclock.c` (tracked app source);
  preprocessor guards disable clock-taking RSX FIFO samples,
  vertex/index/DMA/Vulkan timers, FIFO first-read classification,
  all PS5 PERF/FIFO2/CLOCK2 lines, and global fastclock/yield
  counting. The original fastclock and yield decisions are
  **otherwise unchanged**.
- The frontend watchdog's rotating `ps5_thread_profile(name, 400)`
  SIGUSR1 sampler is disabled; basic periodic CPU utilisation
  reports and their lighter probes, FPS/frame intervals and other
  safety/timing logs remain active for comparability. This tests
  **combined extra diagnostic overhead**, not a complete removal
  of all CPU monitoring, nor each counter separately.
- All seven affected PS5 C++ translation units compiled.
  Full `JOBS=3 bash tools/wsl-build-latest.sh` passed including
  PS5 native TLS verification and all nine packaging checks.
  In the linked ELF the `PS5 PERF`, `PS5 FIFO2`,
  `PS5 CLOCK2`, `PS5 PROFILE %s` strings and the
  `rpcs3ps5_fastclock_stats_take` symbol are **absent**,
  while the `PS5 FPS` string is present.

**Local build hashes (saved in
`results/gta4-rsx-perf-20261030/diagnostic-0058-off.json`):**
- Signed `eboot.bin` 114,100,958 bytes;
  SHA256 `7149011ce8ef5396eb86a9a39a9cf0a44e629a4fd77a7ab3a0f7955c87c24a4f`
- `rpcs3ps5-text.bin` 74,601,041 bytes;
  SHA256 `73e9848c843da24053086e0585d25729ed376da5713d641aaef6b1b6ea1ef3b1`
- Converted ELF 117,425,144 bytes;
  SHA256 `654d70e2c3518b252e67b2f5242704203cd907af05b8cc0f34599375d779eaff`
- Exact matching symbol ELF archived:
  `/home/callum/work/rsx0058-off-link-20261030.elf`.

**PS5 deployment:** `tools/deploy-gta4-rsx0058.py stage` then
`activate` succeeded. Both files verified in stage then installed:
signed SELF compared via decrypted ELF load/TLS segments, code
mirror exact SHA-256. Independent FTP verification confirmed correct
installed live size and **all eight files for four pairs**:

| Build | ELF FTP size | Mirror size | Console name suffix |
| --- | ---: | ---: | --- |
| 0058 **live OFF** | 117,425,144 | 74,601,041 | no suffix |
| 0057 diagnostic ON | 117,425,960 | 74,604,113 | `.before-rsx0058-20261030` |
| 0056 diagnostic ON | 117,425,528 | 74,602,705 | `.before-rsx0057-20261030` |
| Original pre-0054 | 117,425,144 | 74,601,553 | `.before-rsx0056-20261030` |

**Restoring:** only with GTA IV and KB-RPCS3 CLOSED,
`python3 tools/deploy-gta4-rsx0058.py rollback` returns to
patch 0057. If needed, with console closed again restore older
generations using `deploy-gta4-rsx0057.py rollback` followed by
`deploy-gta4-rsx0056.py rollback`. Never overwrite stage/backup
names or skip safe checks.

**Game config unchanged:** scheduler RPCS3 Scheduler (B), MEGA SPU,
Approximate XFloat, resolution scale 150, clocks 100%, frame limit 60,
Strict Rendering false; `ps5-tuning.txt` absent and experimental
SPU flags off. No game saves or title data edited. No performance
measurements on patch 0058 have yet been taken.

**NEXT: user to launch KB-RPCS3 and GTA IV, hold same
stationary outdoor view after compilation settles, and reply
`profiler OFF ready`. Capture two sequential 45-second runs with
`tools/gta4-scheduler-ab.py capture --session
results/gta4-scheduler-20261030 --mode B --label
profiler-off-0058-run1` then `run2`, expected 150% and all
three SPU flags 0. Both should log `PS5 FPS` and NO
`PS5 PERF/FIFO2/CLOCK2/PROFILE`. Compare FPS frame intervals
against 0057 captures; recommend subsequent A/B/A switchback
to 0057 before attributing gains to instrumentation removal.

## Profiler overhead control captures — Patch 0058 OFF vs 0057 ON (2026-10-30 ~04:25–04:28 UTC)

User launched the **profiler-OFF** patch 0058 and explicitly said
`profiler OFF ready` with GTA IV stationary at the reference outdoor
camera. Captured two separate 45-second samples using
`tools/gta4-scheduler-ab.py capture` with:
- session `results/gta4-scheduler-20261030`;
- scheduler B / `RPCS3 Scheduler`, SPU block size Mega,
  resolution scale 150%, approximate XFloat, clocks 100%;
- tuning expectations `spu_insert_select=0`,
  `spu_narrow_ls_store=0`, `spu_narrow_ls_check=0`.
Both captures **VALID** and **zero new SPU compilations**.

**Capture files:**
- `results/gta4-scheduler-20261030/B-profiler-off-0058-run1.{json,log}`
- `results/gta4-scheduler-20261030/B-profiler-off-0058-run2.{json,log}`

Both OFF logs have `PS5 FPS:` and `PS5 CPU:` but **zero**
`PS5 PERF:`, `PS5 FIFO2:`, `PS5 CLOCK2:` and
`PS5 PROFILE ` entries. The ON logs have all expected diagnostics.
This runtime verification agrees with the compiled OFF ELF
symbol check, so the control build did disable the measured
instrumentation.

**Matched-scene pre-switchback results** (numbers are means of
watchdog-window summaries, **not pooled individual-frame percentiles**):

| Metric | 0057 ON run 1 | 0057 ON run 2 | 0058 OFF run 1 | 0058 OFF run 2 |
| --- | ---: | ---: | ---: | ---: |
| Average FPS | 23.50 | 23.69 | 25.21 | 24.44 |
| 1% low FPS | 20.32 | 21.13 | 21.98 | 21.74 |
| p50 frame interval (ms) | 42.81 | 42.26 | 39.70 | 41.04 |
| p95 frame interval (ms) | 47.04 | 45.33 | 43.37 | 43.82 |
| p99 frame interval (ms) | 49.58 | 47.41 | 45.87 | 46.42 |
| Reporting windows in 45-second capture | 9 | 9 | 12 | 11 |
| New SPU compilations | 0 | 0 | 0 | 0 |

Means across the **two entire captures in each condition**:
- ON 0057 FPS **23.595**, OFF 0058 FPS **24.825**,
  difference **+1.230 FPS** or **+5.21%** with profiler disabled.
- ON p95 average **46.185 ms**, OFF p95 average **43.595 ms**,
  difference **-2.590 ms** with profiler disabled.
- OFF 1% low average **21.86 FPS** versus ON **20.725 FPS**
  (approx +1.135 FPS). These are not pooled frame-level percentiles.

**Interpretation and caveats:**
- Direction of both FPS runs favors OFF, consistent with a
  **possible combined profiler overhead**. **Not proof of
  1.23 FPS causally attributable to the profiler**: GTA IV run
  variation, different elapsed game time, game-world events and
  uncontrolled frame interactions can influence results.
- ON runs themselves ranged from **19.3–26.3 FPS per reporting
  window**, while OFF windows ranged **21.6–26.8 FPS**.
  OFF run1 varied 23.1–26.8 FPS despite completely unchanged
  instrumentation. This reinforces that the FPS difference is
  within the kind of noise seen in prior A/B/A experiments.
- Reporting windows differ (ON nine vs OFF eleven/twelve)
  because the ON build's rotating 400-sample SIGUSR1 profiler
  blocks the frontend watchdog for part of every rotation.
  **Do not compare raw counts of windows**; frame interval
  and FPS summaries each refer to the same ~45-second capture
  interval but reporting cadence differs. For a finer analysis,
  correlate frame timestamp samples, not just unweighted means
  of windows.
- OFF disables **all** additional RSX/DMA/Vulkan timers and
  FIFO sampling, global fastclock/yield counting and rotating
  interrupt profiler. FPS/frame interval logging, normal guest
  execution, JIT, GPU, CPU scheduling and the PS5 fastclock
  conversion/yield decisions remain unchanged.
  Thus this trial cannot isolate overhead per diagnostic subsystem.
- In the ON run, ~35% of counted 1.36M fastclock calls/s were
  injected by the timing probes themselves. That is a count
  fraction, not time fraction or FPS reduction.

Combined source of truth:
`results/gta4-rsx-perf-20261030/profiler-overhead-0057-on-vs-0058-off.json`
including 4 validated capture summaries, marker checks,
per-watchdog-window FPS arrays, and first/second-half window
averages.

**Current PS5 state at end:** patch **0058 profiler OFF LIVE**;
patch 0057 ON preserved as
`eboot.bin.before-rsx0058-20261030` and
`rpcs3ps5-text.bin.before-rsx0058-20261030`.
Older patch 0056 and original pre-0054 backups are still
preserved. No executable changes made during these captures.
Do **not** modify/deploy title files while game/launcher running.

**Next required experiment:** user closes KB-RPCS3 and GTA IV,
then safely executes `tools/deploy-gta4-rsx0058.py rollback`
which restores **patch 0057 ON** with verified console
process-check and retains 0058 as staging candidate. Verify
restored 0057 live file sizes and log signatures, then ask
user to launch same save and camera for **two more 45s ON
switchback controls**. Evaluate A(ON) → B(OFF) → A(ON);
optional return OFF for A/B/A/B if equivocal. Do not
claim an optimisation or final overhead finding before
these repeat controls.

### Watchdog-report cadence check for profiler OFF/ON captures

The rotating 400-sample profiler in patch 0057 sometimes prolongs
logging windows to ~6.1 seconds, instead of the normal ~4.03-second
watchdog cadence retained in patch 0058. The 45-second acquisition
therefore selected ON logs of 9 reporting windows spanning 44.59
and 46.59 seconds, while OFF logs used 12 and 11 windows spanning
48.39 and 44.36 seconds. The capture script's wall-time trigger
is still 45 seconds; reported windows can cross its exact boundaries.

To avoid comparing unweighted means of differently spaced reports,
the four FPS sequences were recomputed as
`sum(FPS_window * reporting_interval) / sum(reporting_interval)`
using consecutive `PS5 FPS` log timestamp differences:

| Run | Window-mean FPS | Report-interval weighted FPS |
| --- | ---: | ---: |
| 0057 ON 1 | 23.50 | 23.531 |
| 0057 ON 2 | 23.69 | 23.722 |
| 0058 OFF 1 | 25.21 | 25.208 |
| 0058 OFF 2 | 24.44 | 24.436 |

ON weighted mean **23.6265 FPS**, OFF weighted mean **24.822 FPS**:
**+1.1955 FPS (+5.06%)** when the diagnostic instrumentation is
disabled. Direction is unchanged relative to window-mean +5.21%.
These are approximations from reporting intervals, not precise
frame-level pooled measurements. A switchback capture remains
mandatory before asserting causality.
All arrays and weighted calculations saved in
`results/gta4-rsx-perf-20261030/profiler-overhead-0057-on-vs-0058-off.json`.

## Top-down bottleneck strategy — 100%-resolution control prepared (2026-10-30)

User chose the **better top-down strategy** over more speculative
FIFO fast-clock optimisation:
1. Compare **100% versus 150% rendering scale** on the **same
   profiler-disabled patch 0058**, keeping scheduler B / Mega SPU /
   Approximate XFloat / 60 FPS cap / 100% clocks / game patches
   and SPU tuning unchanged.
2. Restore 150% and repeat to establish that any FPS difference
   reverses with resolution (150 → 100 → 150). Cross-run changes
   may be affected by world traffic/camera/time of day.
3. Only if resolution sensitivity suggests a GPU-bound component,
   investigate Vulkan GPU timestamps/queue completion; if little
   resolution sensitivity, investigate the PPU→SPU→RSX per-frame
   critical path with low-overhead counters and wait dependencies.
4. Run single-change controlled optimisations only after identifying
   the limiting resource; separate all instrumentation overhead.

**Console safety and configuration:**
Before changing anything, a read-only PS5 process list and
the deployment helper's explicit `check_closed` confirmed
no KB-RPCS3 `eboot.bin` or `rpcs3ps5-launch.elf` running.
Existing `results/gta4-resolution-20261030/150.yml` is
**byte-identical** to the verified
`results/gta4-scheduler-20261030/B.yml` and to the then-live
console GTA IV config; its SHA256 is
`9e6fbbe3a5b573525f2e991b1ca15df0d9ea1b80852183e363398436e4b36ba6`.
The existing `100.yml` variant is the same 8,453-byte config
**except one digit** in `Resolution Scale: 150` vs
`Resolution Scale: 100`. Only that one byte differs.

Ran `tools/gta4-resolution-test.py apply100`, then independently
downloaded the console file and verified it matches saved
`100.yml` **byte-for-byte**. The change takes effect on the **next**
GTA IV launch. The patch 0058 profiler-OFF executable/mirror are
unchanged; all rollback generations remain preserved. No save,
game file, other config or emulator binary edited. Original
150% settings remain available via
`tools/gta4-resolution-test.py restore150`.

The resolution helper now implements a **fail-closed PS5 process
guard** for `apply100` and `restore150`, refusing any change
while either title or launcher is running, or if the process
listing cannot be verified. Guard tested against actual closed
console and mocked running/truncated responses. Use helper
**from WSL** (requires the console's process-list network tool).

**Baselines already collected on same 0058 OFF build:**
`B-profiler-off-0058-run1` 25.21 FPS and
`B-profiler-off-0058-run2` 24.44 FPS (45 seconds, zero
new SPU compilations), time-weighted mean ~24.822 FPS.
`tools/gta4-resolution-compare.py --allow-partial` has
validated both OFF baseline logs, checked no PERF/FIFO2/CLOCK2/
PROFILE markers, saved
`results/gta4-resolution-20261030/resolution-compare.json`.
After two 100% captures, call it **without** --allow-partial
to compute the 100 vs 150 FPS and p95 differences. The optional
150%-return pair provides a third verification condition.
Frame-flip FPS does not directly establish actual GPU completion.
The 150% image has ~2.25× the pixel count of 100%, but GPU time
does not necessarily scale linearly with pixel count.

**NEXT ACTION REQUIRED FROM USER**: boot GTA IV on patch 0058
at now-configured **100%**, use **same outdoor save/camera**,
allow compilation to settle, and reply `100% resolution ready`.
Then run two 45-second captures using
`tools/gta4-scheduler-ab.py capture --session
results/gta4-scheduler-20261030 --mode B
--label resolution100-off-0058-run1` and matching run2,
with `--expected-resolution 100` and expected
`spu_insert_select=0`, `spu_narrow_ls_store=0`,
`spu_narrow_ls_check=0`.
Confirm both captures valid, no new SPU compilation,
and that patch 0058 diagnostic lines remain absent.
Then ask the user to close the game before restoring 150%,
repeat a baseline/return run after booting same scene.
Do NOT touch config or binaries while game is running.

The previous profiler A/B observed +1.2 FPS on OFF, but
switchback is **still unperformed**. Do not claim an
instrumentation-derived performance gain, causal overhead or
60 FPS feasibility from that comparison alone.

## Top-down resolution scaling experiment, 100% captures — 2026-10-30 04:40–04:44 UTC

User said `100% resolution ready` after launching same outdoor
save/camera on the unchanged profiler-disabled **patch 0058**.
The console's GTA IV custom config was previously changed **only**
from `Resolution Scale: 150` to `100`, verified by exact
FTP read-back; all other scheduler/renderer/clock/SPU config was
unchanged. Experimental SPU tuning remains OFF. Three separate
45-second samples were obtained with
`tools/gta4-scheduler-ab.py capture` using
`--expected-resolution 100` and all three expected SPU
tuning keys at 0.

| 100% resolution | Run 1 | Run 2 (DISCARDED) | Run 3 |
| --- | ---: | ---: | ---: |
| Mean FPS | **25.04** | 23.29 | **24.38** |
| Report-interval weighted FPS | **25.042** | NOT USED | **24.382** |
| p50 frame interval (ms) | 40.27 | 41.50 | 41.10 |
| p95 frame interval (ms) | 44.31 | 50.50 | 45.89 |
| p99 frame interval (ms) | 46.41 | 162.03 | 49.36 |
| New SPU block compilations | **0** | **180** | **0** |
| Tool config validation | valid | valid | valid |

Run 2 was correctly **excluded** from the steady-state
resolution comparison despite passing the script's basic
configuration/normal-speed validity check. Its 180 new SPU block
compilations and a 1,271.97ms single-window p99 spike are strong
compilation-contamination signals. The capture script does not
treat `new_spu_compilations > 0` as an automatic invalidity;
the resolution comparison script does reject it. These
compilations do not establish a 100% scale problem.

**150%-baseline vs 100%-scale, patch 0058 profiler OFF**
(both 2 captures, all with zero new SPU compilation):

| Resolution | Clean run FPS | Mean (window averages) | Report-interval weighted FPS |
| --- | --- | ---: | ---: |
| **150%** | 25.21, 24.44 | **24.825** | **24.822** |
| **100%** | 25.04, 24.38 | **24.710** | **24.712** |

**100% − 150% = -0.110 FPS (-0.44%)**. The means are
indistinguishable at the observed level of GTA IV performance
noise, despite 150% rendering scale demanding approximately
2.25x as many scaled pixels as 100%. The mean reported
p95 interval is **45.10ms at 100%** vs **43.595ms at 150%**,
a small fluctuation favoring the higher resolution, not
a credible graphics-performance reversal.

This is strong preliminary screening evidence against a
**pixel-count-dominated GPU fill-rate/shading bottleneck**
in this exact stationary scene. It is **not** proof that
GTA IV is wholly CPU-bound: GPU execution with fixed draw/
geometry/driver overhead and CPU/GPU synchronization could be
resolution-insensitive; report is based on FPS windows,
not Vulkan GPU timestamps or fence-completion measurements.
SPU cores continue near 90–99% utilization, RSX ~79–91%
and PPU RenderThread ~74–85% across logs. CPU usage
alone does not identify frame-critical dependencies.
`PS5 WAITS` RADV and event counters remain zero and do
not rule out driver waits.

**Saved artifacts**:
- `results/gta4-scheduler-20261030/B-resolution100-off-0058-run1.{json,log}`
- `results/gta4-scheduler-20261030/B-resolution100-off-0058-run2.{json,log}`
  **explicitly excluded** (180 new SPU blocks)
- `results/gta4-scheduler-20261030/B-resolution100-off-0058-run3.{json,log}`
- `results/gta4-resolution-20261030/resolution-compare.json`
  stores clean 150/100 comparisons, report-window timestamp-
  weighted FPS, compilation-exclusion reason and caveats
- `tools/gta4-resolution-compare.py` checks no
  PERF/FIFO2/CLOCK2/PROFILE markers, requires valid
  scheduler/resolution, rejects SPU compilations, and
  supports an optional return-to-150 condition

**Current PS5 state** at end of measurements: GTA IV is
still running patch **0058 profiler OFF** configured at
**100% resolution**. DO NOT alter the executable pair or
`config_NPUB30702.yml` until the user explicitly says
both GTA IV and KB-RPCS3 are **closed**, and a PS5
process check confirms. For 150% return control,
invoke in WSL:
`python3 tools/gta4-resolution-test.py restore150
--session results/gta4-resolution-20261030`.
This helper now refuses config edits while the title/launcher
runs or if process listing is incomplete. Verify the restored
file byte-for-byte matches `150.yml`. Reboot GTA IV and
repeat 1–2 stationary captures with labels
`resolution150-return-0058-run1`, `run2` and
`--expected-resolution 150` and the three SPU tuning
keys at zero. If the return FPS is still ~25 FPS, deprioritise
pixel-scaled GPU work and shift to low-overhead per-frame
**PPU/SPU/RSX dependency trace** and GPU query/fence
latency rather than microtiming every RSX operation.

## Top-down resolution reversal — 150% restored, 2026-10-30 ~04:47 UTC

User confirmed `closed for 150% restore` after two clean 100%-scale captures.
Ran actual PS5 process listing via the protective helper and verified that
neither `eboot.bin` nor `rpcs3ps5-launch.elf` was running.

Restored configuration with:
`python3 tools/gta4-resolution-test.py restore150 --session
results/gta4-resolution-20261030`.
The helper verified that the current 100% config matches the saved
known variant, safely installed the saved original and confirmed
`Resolution Scale 150%` through FTP read-back.

An **independent FTP read-back** then verified the full 8,453-byte
live custom config is byte-for-byte identical to saved
`results/gta4-resolution-20261030/150.yml` and
`results/gta4-scheduler-20261030/B.yml`; SHA256
`9e6fbbe3a5b573525f2e991b1ca15df0d9ea1b80852183e363398436e4b36ba6`.
All GTA IV scheduler, SPU, clock and FPS-cap settings were preserved.

Confirmed the unchanged live patch 0058 profiler-OFF executable pair:
decrypted `eboot.bin` 117,425,144 bytes; code mirror 74,601,041.
Patch 0057 immediate backup pair also intact:
`eboot.bin.before-rsx0058-20261030` 117,425,960 bytes;
`rpcs3ps5-text.bin.before-rsx0058-20261030` 74,604,113 bytes.
Older rollback generations were not modified.

**Next step:** user launches KB-RPCS3 + GTA IV at now-restored
150% resolution, selects same stationary outdoor scene/camera,
allows any new SPU compilation to finish, and replies
`150% return ready`. Then take two independent 45-second
FPS captures with:
`tools/gta4-scheduler-ab.py capture --session
results/gta4-scheduler-20261030 --mode B
--label resolution150-return-0058-run1 --expected-resolution 150`
and the repeated 3 `--expected-tuning` key/value flags at zero;
repeat with `run2` label. Verify 0 new SPU compilations
(**do not trust valid=true alone**, 100% run2 had 180 new blocks),
PS5 FPS markers exist, and diagnostic PERF/FIFO2/CLOCK2/PROFILE
markers remain absent. Run `tools/gta4-resolution-compare.py`
to compare all 3 conditions (initial 150%, 100%, return 150%).
If return matches initial ~24.8 FPS, shift emphasis to low-overhead
CPU/SPU/RSX thread dependency and optional GPU fence/timestamps.
No FPS claim is made at this point, because the return capture
has not yet been taken.

## Top-down resolution reversal: completed return-to-150% captures (~04:51–04:53 UTC 2026-10-30)

User said **`150% return ready`** after launching the
same GTA IV outdoor scene/camera with the restored 150% config
and unchanged **patch 0058 profiler-OFF**. We immediately
captured **two independent 45-second** intervals using
`tools/gta4-scheduler-ab.py capture`, B scheduler,
`--expected-resolution 150`, and all three SPU experimental
tuning flags expected at zero. Both are **valid**, **zero new
SPU blocks compiled**, and contain FPS logs while containing
**zero** `PS5 PERF:`, `PS5 FIFO2:`, `PS5 CLOCK2:` and
`PS5 PROFILE ` entries.

Files:
- `results/gta4-scheduler-20261030/B-resolution150-return-0058-run1.{json,log}`
- `results/gta4-scheduler-20261030/B-resolution150-return-0058-run2.{json,log}`
- Full validated comparison `results/gta4-resolution-20261030/resolution-compare.json`
  updated with six selected clean captures, reporting-interval
  weights, explicit **exclusion** of 100% run2 (180 SPU compilations),
  return-to-original FPS drift and methodological caveats.

Three-condition comparison (same 0058 profiler-OFF executable,
150/100/150 resolution scale, constant other config):

| Condition | Clean 45s FPS runs | Two-run mean of report-interval weighted FPS | Mean reported p95 ms |
| --- | --- | ---: | ---: |
| initial 150% | 25.21, 24.44 | **24.822** | 43.595 |
| 100% | 25.04, 24.38 | **24.712** | 45.100 |
| restored 150% | **25.41, 21.93** | **23.668** | 46.135 |

Return run1 p50 **39.38ms**, p95 **44.02ms**, p99 **46.67ms**,
1% low **21.55 FPS**, 0 new SPU compilations.
Return run2 p50 **45.64ms**, p95 **48.25ms**, p99 **49.72ms**,
1% low **20.14 FPS**, 0 new SPU compilations.
The two return runs varied **3.48 FPS** on the same build,
resolution and nominal stationary camera, materially more
than the initial 100%-vs-150% difference (-0.11 FPS).
The initial 150%-to-100% step yielded
**-0.110 FPS (-0.44%)** at 100% despite 2.25x fewer scaled
pixels. On return to 150%, FPS did not revert to the original
24.82 mean; it drifted to **23.67**. This A→B→A is
**not stable enough to estimate a causal small resolution effect**.
The main defensible inference is that **no repeatable improvement
from reducing pixel count has been observed** in this scene.
There is currently no reason to prioritise pixel-fill optimisation,
but **GPU geometry, driver submission, GPU frame completion,
buffer dependencies and other resolution-insensitive GPU costs
remain possible**. FPS logs report RSX frame flips, not
explicit GPU timestamps/fences.

Existing `PS5 CPU` per-capture reports show sustained
roughly 95–99% SPU secondary/primary worker utilisation,
roughly 80–93% RSX CPU thread use and ~74–87% GTA IV
RenderThread CPU use. High CPU use **does not prove** those
threads lie on the frame's serial critical path or that
the GPU is idle. The PS5 `PS5 WAITS` RADV/event counters
often report zero; this **does not** rule out other host
waits, guest synchronization or GPU backpressure.

**New recommended diagnostic**: keep profiler OFF as stable
control and collect infrequent, batched **per-frame dependency**
markers with a bounded ring buffer: PPU render requests,
SPU job/critical waits and completions, RSX FIFO/DRAW/flip
boundaries, Vulkan queue submit and GPU completion/fence
(if supported). Use timestamps only on chosen frame samples
rather than every FIFO method, and write the ring in batches
outside latency-sensitive paths. First inspect source
`rpcs3/Emu/RSX/VK/VKPresent.cpp` (frame flips),
`rpcs3/Emu/RSX/VK/VKCommandStream.cpp` (vkQueueSubmit)
and Vulkan query infrastructure
`rpcs3/Emu/RSX/VK/VKQueryPool.cpp`;
no current evidence of preexisting timestamp-query
instrumentation. Measure profiler ON/OFF against same build
to ensure overhead negligible, and use per-stage causal
dependencies rather than summing overlapping CPU stage times.

**Console state after this turn**: patch **0058 profiler OFF**
still installed, **150% original GTA IV resolution restored**,
and GTA IV/KB-RPCS3 **RUNNING** (user said ready, no close
message). Do **NOT** write executable/config or deploy a
new diagnostic until the user explicitly closes both the
game and launcher and the console process list confirms.
Existing 0057 ON and older backed-up binaries are untouched.
No console writes were made during capture/analysis.

**Next user action**: captures complete, may move character.
Ask user to close GTA IV and KB-RPCS3 and reply
`closed for frame-dependency diagnostic` to safely
start more targeted profiling, without repeating the
resolution tests unless the scene becomes better controlled.

## Patch 0059 — sparse frame dependency CPU timeline (PS5), 2026-10-30 ~04:56–05:08 UTC

User explicitly confirmed **GTA IV and KB-RPCS3 closed** with
`closed for frame-dependency diagnostic`. Before modifying the
console, `deploy-gta4-rsx0058.py.check_closed()` checked the
actual PS5 process list and verified **no `eboot.bin` or
`rpcs3ps5-launch.elf` process**.

**Intent:** after the completed 150→100→150 resolution test
(roughly 24.82 / 24.71 / 23.67 FPS but substantial uncontrolled
run variation), move away from the old high-frequency
`PS5 PERF/FIFO2/CLOCK2` counters towards an **infrequent
CPU-side wall-time timeline** of useful guest/RSX/Vulkan
boundaries and selected blocking waits. This is a diagnostic
experiment, not a speed patch, and does **not** directly
measure GPU runtime or establish a fully paired frame DAG.

**Patch/source:**
- Reproducible upstream patch:
  `port/rpcs3-latest-patches/0059-PS5-sparse-frame-dependency-CPU-timeline.patch`,
  16,136 bytes, generated as an isolated diff on top of
  patches 0054–0058 and verified using an independent Git
  index `git apply --cached --check`. Manifest
  `port/rpcs3-latest.json` patch_count **59**.
- New header in WSL latest upstream:
  `rpcs3/Emu/RSX/ps5_frame_trace.h`.
- Sample **one in every 32 PS3 guest display-queue epochs**;
  the sample begins at `sys_rsx_context_attribute` package
  0x103, until the next display queue. Sampled epoch is a
  **wall-time window**, not a guaranteed exact matching of
  async RSX and GPU work to that guest frame.
- CPU TSC markers: guest display queue start/end, guest
  display flip request, RSX `VKGSRender::present_frame`
  begin/end, Vulkan swapchain image acquire begin/end,
  `vkQueueSubmit` call begin/end, `vkQueuePresent`/
  present wrapper begin/end, and host fence waits
  (`vk::wait_for_fence`) begin/end. Queue submission
  durations are **CPU call duration**, not GPU execution.
- Guest PPU event queue/flag/semaphore syscalls:
  only mark the **blocking branch** and only log waits
  of **at least 500us**. PPU thread full ID retained
  in event payload; wait pairs retain original sampled epoch
  even if a wait spans a newer epoch. Does not directly
  track SPU job execution, SPURS signal causality or
  arbitrary PPU locks.
- Fixed 4,096-slot atomic ring; bounded enqueue uses
  no dynamic allocation, no locks, no sys_log, and reads
  `utils::get_tsc()` only for sampled markers.
  Watchdog drains at its existing ~4s cadence and writes
  `PS5 FRAMEDEP:` event records containing
  `seq/epoch/kind/arg/tsc` and
  `PS5 FRAMEDEP2:` report with TSC Hz, totals,
  skipped and missed counts. Caps log emission to 256
  event records per watchdog cycle. **If skipped/missed
  are nonzero, the trace was incomplete**; do not silently
  analyse missing events.
- Original high-frequency `PS5 PERF`, `PS5 FIFO2`,
  `PS5 CLOCK2` and rotating 400-SIGUSR1-sample profiler
  remain compiled OFF, while ordinary `PS5 FPS` and
  CPU utilisation reports remain ON. No guest logic,
  scheduler, rendering config, game data or save changed.

**Validation:**
- All **eight** changed translation units compiled using
  PS5 SDK under Ninja, after fixing header import for
  `utils::get_tsc_freq()`.
- Full `JOBS=3 bash tools/wsl-build-latest.sh` passed,
  including native TLS verification and all nine title
  asset packaging checks.
- Linked ELF contains `PS5 FRAMEDEP`,
  `PS5 FRAMEDEP2`, `PS5 FPS` strings and
  shared `ps5_frame_trace::ring, written, epoch, sampled`
  symbols; older heavy profiling strings are absent.
- `port/tests/check-ps5-frame-trace.py` host C++ test
  passes: sparse 1/32 epochs, inactive no-op, full PPU IDs,
  TSC wait pairs, atomic-ring reads, next-epoch behaviour.
- `tools/gta4-frame-dep.py` parses matched GTA IV FPS
  capture logs into sampled epoch counts, event counts,
  CPU wall-time pair durations and explicit ring loss
  counters; a synthetic 14-event test passed (TSC unit
  conversion, PPU wait, Vulkan submit pairing).
- `python -m py_compile` and `git diff --check` passed.

**Local build hashes**:
- Signed `eboot.bin`: **114,104,414 bytes**, sha256
  `2dae6a69c91a8f8c9b5d3da3e6c2c8ba262fee3d89675fcecf346f0130a99dff`
- `rpcs3ps5-text.bin`: **74,603,921 bytes**, sha256
  `767f327a49ba5d9871326151a7e006d7302cd17a83a52f4a9510c4d5afcd02ce`
- Converted ELF **117,425,408 bytes**, sha256
  `af0297e4e79299cc6061190e777396fff7ed25938935993a8a0754c77e79c862`
- Matching symbol ELF archived at
  `/home/callum/work/rsx0059-framecpu-link-20261030.elf`.
  JSON manifest in
  `results/gta4-rsx-perf-20261030/diagnostic-0059-framecpu.json`.

**Installed on PS5**:
`tools/deploy-gta4-rsx0059.py stage` then
`activate` succeeded, with process check before both,
independent SELF decrypted-ELF load/TLS comparison,
exact mirror read-back SHA256 and safe rollback procedure.
A separate FTP check confirmed **all five live/backed-up pairs**
and original 150% game config unchanged:

| Console build | FTP ELF bytes | Mirror bytes | Suffix |
| --- | ---: | ---: | --- |
| 0059 **LIVE** sparse CPU trace | 117,425,408 | 74,603,921 | live |
| 0058 profiler OFF control | 117,425,144 | 74,601,041 | `.before-rsx0059-20261030` |
| 0057 profiler ON | 117,425,960 | 74,604,113 | `.before-rsx0058-20261030` |
| 0056 older diagnostic | 117,425,528 | 74,602,705 | `.before-rsx0057-20261030` |
| pre-0056 older build | 117,425,144 | 74,601,553 | `.before-rsx0056-20261030` |

Original 150% GTA IV config matches
`results/gta4-resolution-20261030/150.yml` byte-for-byte;
sha256 `9e6fbbe3a5b573525f2e991b1ca15df0d9ea1b80852183e363398436e4b36ba6`,
scheduler RPCS3 Scheduler, SPU Mega, Approximate XFloat,
100% clocks, 60 FPS cap and SPU tuning flags OFF.

**Rollback only while GTA IV and KB-RPCS3 closed**:
`python3 tools/deploy-gta4-rsx0059.py rollback` with
process-list check; restores original profiler OFF 0058
as live executable/mirror pair and leaves 0059 candidate
as stage. Do not overwrite any backup suffix or hot-swap
the paired title files while running.

**NEXT USER ACTION**: launch GTA IV with patch 0059
at 150%, return to the same stationary outdoor camera,
allow compilation to settle, reply
`frame trace ready`. Capture two 45-second B-mode
windows, using
`tools/gta4-scheduler-ab.py capture --session
results/gta4-scheduler-20261030 --mode B
--label framedep0059-run1 --expected-resolution 150`
with three `--expected-tuning ...=0` flags as before,
then repeat `framedep0059-run2`.
Confirm each run has zero new SPU compilations
(the capture tool's `valid=true` alone does not exclude
compilation contamination), confirm `PS5 FRAMEDEP`
and `FRAMEDEP2` markers and absence of old PERF/FIFO2/
CLOCK2/PROFILE markers. Parse each with:
`python tools/gta4-frame-dep.py
results/gta4-scheduler-20261030/B-framedep0059-run1`
and repeat run2. Check `buffer_skips/misses` before
interpreting pair timings, plus a fresh FPS comparison
against OFF 0058 baseline **24.82 FPS** to bound new
sparse-trace overhead. If no FRAMEDEP markers, verify
0x103 guest queue frequency/actual runtime branch
rather than claiming success.

**Future work**: Use sampled overlap/wait pattern to
form a more specific PPU/SPU/RSX bottleneck hypothesis,
then investigate actual GPU timing with
VK timestamp queries/fences if API/runtime support permits.
Avoid treating host `vkQueueSubmit` or fence wait duration
as GPU execution time, and do not infer a true per-frame
dependency DAG solely from overlapping sampled epochs.

## Patch 0059 on-console sparse CPU frame timeline — Two GTA IV runs (2026-10-30 ~05:13–05:16 UTC)

User explicitly replied **`frame trace ready`** with KB-RPCS3/GTA IV
stationary at the same outdoor camera. Captured **two separate 45-second
runs** with the unchanged **patch0059 CPU trace** at 150% resolution,
scheduler B RPCS3 Scheduler, SPU Mega, XFloat Approximate, 100% clocks,
60 FPS cap and all three experimental SPU tuning flags OFF.

Files:
- `results/gta4-scheduler-20261030/B-framedep0059-run1.{json,log}`
- `results/gta4-scheduler-20261030/B-framedep0059-run2.{json,log}`
- Parsed `B-framedep0059-run1-framedep.json` and
  `B-framedep0059-run2-framedep.json` in the same folder.
- `results/gta4-rsx-perf-20261030/frame-dep-0059-combined.json`
  contains complete per-thread wait summaries, CPU occupancy, weighted
  FPS comparisons to patch0058, capture validation and limitations.
- Parser `tools/gta4-frame-dep.py` now includes
  `ppu_waits_by_thread_id` with per-wait-category counts/durations
  rather than only combined wait statistics. Python compilation passed.

All captured tests: **VALID**, **zero new SPU compilations**,
no `PS5 PERF`, `PS5 FIFO2`, `PS5 CLOCK2`, or
`PS5 PROFILE` markers. CPU timeline emitted successfully,
with **no skipped or missed events** reported by the watchdog.

| Patch 0059 150%, 45 s | Run 1 | Run 2 |
| --- | ---: | ---: |
| FPS, window mean | **22.14** | **23.45** |
| FPS, timestamp-weighted | **22.136** | **23.455** |
| Median reported frame interval (ms) | 45.19 | 42.78 |
| Mean reported p95 frame interval (ms) | 49.19 | 45.82 |
| SPU compilations | 0 | 0 |
| Sampled guest queue epochs | 34 | 35 |
| Timeline events within measurement | 1,422 | 1,485 |
| Skipped/missed timeline events | 0 | 0 |

The two-run patch0059 FPS mean is **22.795 FPS**. Compared
with the two *initial* patch0058 profiler-OFF 150%-resolution
captures (**24.822 FPS**), observed difference **-2.027 FPS**;
compared with the *returned* patch0058 OFF 150% controls
(**23.668 FPS**), **-0.873 FPS**; compared with all four
0058 150% captures (**24.245 FPS**), **-1.450 FPS (~-5.98%)**.
**DO NOT attribute this to trace overhead** without a
same-scene patch0058 switchback. The previously measured
unchanged 0058 return controls varied **3.482 FPS**
(25.409 and 21.927 FPS), exceeding the between-build
difference.

### Sparse CPU timestamp results

Across the 34/35 sampled wall-time epochs per run,
no `vk_fence_begin/end` events were captured.
A lack of recorded host fence waits is **not evidence of
zero GPU execution time or absence of GPU backpressure**.
All values below are CPU wall-clock calls, not GPU
timestamp queries or an additive frame critical path:

| Sampled stage, mean per invocation | Run 1 | Run 2 |
| --- | ---: | ---: |
| Guest display-queue 0x103 hook | 0.003 ms | 0.003 ms |
| RSX VKGSRender::present_frame | **0.392 ms** | **0.358 ms** |
| Vulkan image acquire host call | 0.019 ms | 0.018 ms |
| Vulkan `vkQueueSubmit` host call | **0.079 ms** | **0.079 ms** |
| Vulkan present host call | 0.010 ms | 0.011 ms |
| PPU event-queue syscall blocking branch | 10.429 ms | 9.445 ms |
| PPU semaphore syscall blocking branch | 34.080 ms | 25.282 ms |

PPU syscall waits are **a mix of different guest workers**.
The per-thread classification is essential: waiting in a
background or audio worker may be normal and does not by itself
limit rendered frame throughput. PPU thread IDs and names from
the `PS5 CPU` listing:

| PPU ID/name | Observed blocking path | Mean wait Run 1 / Run 2 |
| --- | --- | ---: |
| `0x0100000a` [GTA] RenderThread | Semaphore (11 / 8 instances) | **3.334 / 2.363 ms** |
| `0x01000000` main_thread | Semaphore (66 / 70) | **5.337 / 4.375 ms** |
| `0x01000000` main_thread | Event queue (129 / 155) | **1.537 / 1.417 ms** |
| `0x0100000c` [RAGE Audio] Multistream | Event queue (145 / 141) | 10.085 / 9.973 ms |
| `0x0100000e` GTA Audio Update | Semaphore (34 / 35) | 41.575 / 38.998 ms |
| `0x01000015` RMPTFX Update | Semaphore (33 / 34) | 42.287 / 39.329 ms |
| `0x01000010` [RAGE] crmtScheduler[0] | Semaphore (35 / 36) | 31.455 / 31.768 ms |
| `0x01000008` no CPU top-thread name in captured log | Event queue (34 / 35) | 45.63 / 42.87 ms |
| `0x01000005` [RAGE] pgStreamer::Worker | Semaphore (3 / 1) | 634.57 / 480.92 ms |

Long stream-worker waits are intermittent, and these
guest workers do not map directly to frame-critical
dependencies. RenderThread may still block in other syscall
families or RPCS3 host waits not instrumented here.
The FPS slowdown was **not explained by synchronous
vkAcquireNextImage/vkQueueSubmit/vkQueuePresent host CPU
call time** in this sampled portion. The main ~40–45 ms
frame-critical interval remains **unattributed**:
PPU active instruction execution/guest scheduling,
SPU guest jobs/JIT/waits, RSX FIFO method processing and
GPU asynchronous completion were not timed end-to-end.

In matching **last eleven capture-aligned CPU reports**
(exclude earlier startup windows), RSX CPU utilisation
was **88.6% / 89.6%**, GTA RenderThread **84.4% / 84.9%**,
SecondaryCellSpursKernel0 **97.5% / 97.0%**, and
PrimaryCellSpursKernel2 **97.1% / 97.7%**. This strong
parallel activity is useful for prioritising, but does
not prove which thread lies on the serial frame path.

### Interpretation and next experiment

- **No GPU execution timestamps have been captured**;
  (vkQueueSubmit) CPU call duration is not GPU runtime.
- All sampled wall-time epochs include potentially unrelated
  asynchronous work and cannot be treated as a fully
  correlated DAG of guest PPU → SPU → RSX → GPU.
- Sparse timeline itself may still perturb performance
  through per-blocking-syscall state probes and batched
  sys_log emission. The ~6% mean FPS difference from
  pooled patch0058 controls cannot establish overhead
  without switching back, because patch0058 FPS natural
  variation was already substantial.
- Next recommended safety-controlled step is a
  **patch 0058 profiler-OFF switchback** (same config,
  no new trace), using two fresh 45-second stationary
  captures once title is closed and user provides ready.
  Use `tools/deploy-gta4-rsx0059.py rollback` **only**
  after verifying GTA IV and KB-RPCS3 are stopped. Patch0059
  stays preserved as staged candidate.
- For deeper hotspot attribution, instrument **PPU RenderThread
  active/blocked state** and **SPU worker execution/guest sync**
  versus RSX FIFO method-processing time, plus optionally
  Vulkan GPU timestamp queries if supported. Maintain
  low overhead, no all-method clock probes, and a verified
  profiler-OFF matched control.

**Console state at conclusion**: GTA IV remains **RUNNING**
patch0059 sparse frame timeline at restored **150%**;
all backup pairs intact, no game/config/executable changes
during either capture. **DO NOT deploy or modify title
files until user closes both game and launcher**.

## 2026-10-30 — Started targeted SPU-worker / RSX-thread work; patch 0060 built OFFLINE

User explicitly requested: **"i think we should start working on SPU
workers and RSX threads"**, rather than continuing broad profiling.

**Safety / live PS5 state**: The user's last message about gameplay
was `frame trace ready` for patch0059; they have **not** confirmed
GTA IV and KB-RPCS3 closed. Therefore **NO console file changes**
were attempted. Patch0059 remains the installed diagnostic at the
restored 150% GTA IV configuration; 0058 and earlier rollback
pairs are unchanged. The new 0060 package is **LOCAL ONLY**.
Do not stage, activate or roll back anything until explicit user
closure **and** a PS5 process-list verification.

**Evidence driving this work**:
- Two clean patch0059 45s samples at 150% logged **22.14 and
  23.45 FPS**, zero new SPU compilations, zero frame-trace losses.
- Last capture-aligned CPU reports: secondary/primary SPU workers
  ~97–98% of a CPU core each; RSX thread ~89%, PPU GTA
  RenderThread ~84–85%. These are high utilisation, not proof of
  frame-serial critical path.
- Patch0059 CPU timing shows sampled `VKGSRender::present_frame`
  ~0.36–0.39 ms, host `vkQueueSubmit` call ~0.08 ms,
  RenderThread observed semaphore blocking waits 2–3 ms;
  long background audio/effects waits are **not** proven render
  stalls.
- RSX source `RSXFIFO.cpp::thread::run_FIFO` handles
  `FIFO_EMPTY`, `FIFO_NOP`, `FIFO_BUSY` and self-jump
  spinning as well as productive command dispatch. High
  RSX CPU utilisation alone can't distinguish useful work
  from polling.
- SPU source `SPUThread.cpp::cpu_task` runs compiled SPU
  code through `spu_runtime::g_gateway`; a lower-frequency
  `cpu_work` helper handles MFC progress/interrupts. CPU
  utilisation does not show whether time is guest execution,
  MFC/channel synchronization, or spin/wait.

**Patch 0060 prepared and built**:
- `port/rpcs3-latest-patches/0060-PS5-sample-SPU-RSX-worker-activity.patch`
  is a reproducible isolated diff **on top of 0059**. Manifest
  `port/rpcs3-latest.json` now has **60** patches; independent
  temporary Git index `git apply --cached --check` passed.
- New WSL upstream header `rpcs3/Emu/RSX/ps5_worker_activity.h`.
  Adds fixed 64-SPU-ID atomic slots and 5 RSX FIFO-state
  counter groups. It does not allocate or log on JIT/FIFO
  hot paths. Slots are registered on SPU task start; overflow
  is reported if more than 64 unique SPU IDs are encountered.
- **1/256** compiled SPU JIT `g_gateway` calls sampled,
  with inclusive CPU TSC wall-time duration per SPU LV2 ID.
  The sample includes helper waits/stalls and is not exclusive
  guest instruction execution time.
- **1/1024** `spu_thread::cpu_work` calls sampled,
  without interfering with JIT interrupt escape; represents
  sampled MFC/pending/interrupt helper path inclusive CPU
  time, possibly overlapping sampled gateway time. Sample
  duration is collected **before** `g_escape`.
- **1/512** `rsx::thread::run_FIFO` calls sampled with
  **post-call** state grouped into `running`, `nop`,
  `empty`, `spinning` and `other`. A single run_FIFO
  invocation may process multiple guest methods; the
  category is **not** a draw/command count and the sampling
  excludes RSX CPU work outside run_FIFO.
- Existing ~4s watchdog reports `PS5 WORKER: group ...
  id ... kind ... sample_n ... avg_us ... max_us ...
  sampled_sum_us ...`. Read/reset counters are atomic;
  no log output on hot worker threads. Do not sum inclusive
  overlapping SPU gateway+cpu_work durations as if additive.
- **The old patch0059 `PS5 FRAMEDEP` sampler is compiled
  into no-op mode** in `ps5_frame_trace.h` via
  `inline constexpr bool enabled = false`, to reduce
  overhead and isolate 0060 SPU/RSX worker timing.
  The earlier PERF/FIFO2/CLOCK2/rotating SIGUSR1 profiler
  also remain disabled.
- **No emulated scheduling, JIT code generation, DMA,
  RSX FIFO dispatch, synchronization, GPU or game
  configuration semantics were modified.** This is a
  narrow measurement step, not an FPS optimisation yet.

**Offline validation**:
- Three modified PS5 translation units (`SPUThread.cpp`,
  `RSXThread.cpp`, `ps5_frontend.cpp`) compiled.
- Full `JOBS=3 bash tools/wsl-build-latest.sh`
  completed: 165 core archives, final linked signed
  title, native TLS verified, all nine package assets passed.
- `port/tests/check-ps5-worker-activity.py` host C++ test
  passes 64 slot allocations, per-SPU and per-RSX stage
  counters, TSC conversion, atomic take and overflow.
- `port/tests/check-ps5-frame-trace.py` updated to
  validate disabled/no-op patch0059 frame-event mode as
  well as its original enabled branch.
- `tools/gta4-worker-activity.py` parses matching 45s
  FPS windows, per-SPU and per-RSX sample counts/time,
  estimated sampled FIFO time fraction, event-loss
  marker and caveats. Synthetic 6-FPS-window/3-watchdog
  parser test passed.
- Signed SELF hash, converted ELF hash, and exact mirrored
  code hash verified locally; expected `PS5 WORKER`
  strings and stage symbols exist, and old high-frequency
  PERF/FIFO2/CLOCK2/PROFILE string markers are absent.

**Local patch0060 artifacts** (NOT on console):
- Signed `eboot.bin`: **114,105,182 bytes**,
  SHA256 `e4589e7e692ec8e7125cc057da76f36e02b82ca0f9527e24e1a0cb6475a83feb`
- `rpcs3ps5-text.bin`: **74,604,305 bytes**,
  SHA256 `da0cd6d34e07bda23013001bead0900a7c9f18646b50c3983fac09e0f8e6bafc`
- Converted ELF: **117,429,696 bytes**,
  SHA256 `6abe54489d38121b7be8b293ca5ce589d51a114352dc072a35aaf9d994f9b466`
- Symbol linker ELF archived at
  `/home/callum/work/rsx0060-worker-link-20261030.elf`
- Hash-pinned build manifest:
  `results/gta4-rsx-perf-20261030/diagnostic-0060-spu-rsx-worker.json`
  explicitly sets `console_deployed=false`.
- Safe staged paired-file installer (prepared, NOT run):
  `tools/deploy-gta4-rsx0060.py`. It does not touch
  the console except on explicit stage/activate/rollback
  with actual PS5 process check; stage uploads both
  verified files, activation first backs up the live
  pair as `.before-rsx0060-20261030`. Rollback restores
  patch0059 as matching live pair, preserving 0060 candidate
  as stage. Existing 0058 backup chain survives.

**NEXT USER ACTION**: close GTA IV and KB-RPCS3, reply
`closed for SPU/RSX worker test`. Then run 0060
`stage` and `activate` with read-back verification,
without altering the saved 150% GTA IV configuration.
User boots the same stationary outdoor scene and replies
`SPU/RSX worker ready`. Take 2 separate 45-second
scheduler-B captures with `--expected-resolution 150`,
3 experimental SPU knobs `=0`, and labels
`spu-rsx0060-run1`, `run2`; reject any SPU compilation
during measurement. Parse with
`tools/gta4-worker-activity.py`, compare FPS to the
existing patch0059 (22.795 mean) and 0058 profiler-OFF
(24.245 four-run mean), mindful of GTA IV uncontrolled
run variation. Decide which **specific** SPU/RSX function
or polling case is worth optimising based on worker
sample distribution; do not infer from CPU % alone.


## 2026-10-30 05:33–05:36 UTC — Patch0060 installed after user closure

User confirmed **"closed for SPU/RSX worker test"**. Actual PS5
process listing verified neither \`eboot.bin\` nor
\`rpcs3ps5-launch.elf\` running before staging and again on activation.

Deployed local patch0060 signed PS5 executable and matching RSX code
mirror using \`tools/deploy-gta4-rsx0060.py stage\`, then
\`activate\`. Both staging and post-activation validated decrypted
ELF load/TLS segments against the locally converted PS5 ELF,
and exact SHA256 of the RSX mirror. Both actions exited 0.

Independent subsequent FTP verification:
- Live patch0060 decrypted ELF **117,429,696 bytes**
- Live \`rpcs3ps5-text.bin\` **74,604,305 bytes**, exact staged
  SHA256 \`da0cd6d34e07bda23013001bead0900a7c9f18646b50c3983fac09e0f8e6bafc\`
- Immediate backup patch0059
  \`*.before-rsx0060-20261030\` **117,425,408 / 74,603,921 bytes**
- Prior backup patch0058 \`*.before-rsx0059-20261030\`
  **117,425,144 / 74,601,041 bytes**
- Earlier backups patch0057/0056/pre-0056 all preserved, sizes
  **117,425,960/74,604,113**, **117,425,528/74,602,705**,
  **117,425,144/74,601,553**, respectively
- GTA IV custom config byte-identical to the saved **150%**
  scheduler-B reference, 8,453 bytes, SHA256
  \`9e6fbbe3a5b573525f2e991b1ca15df0d9ea1b80852183e363398436e4b36ba6\`.
  No game files, saves or other settings touched.

Updated
\`results/gta4-rsx-perf-20261030/diagnostic-0060-spu-rsx-worker.json\`
to **\`console_deployed: true\`** with installed sizes/rollback map.

Patch0060 retains old heavy profiler disabled and compiles patch0059
frame event probes into no-ops; adds only low-rate 1/256 SPU gateway,
1/1024 SPU cpu_work, 1/512 RSX run_FIFO sampled wall-time counters
and watchdog-only \`PS5 WORKER:\` reporting. This is an investigation
build, not a claimed FPS gain.

**NEXT USER ACTION:** launch KB-RPCS3 and GTA IV patch0060,
same outdoor stationary save and camera, let new SPU compilation
settle, reply \`SPU/RSX worker ready\`. Then capture *two*
separate 45-second runs with
\`python tools/gta4-scheduler-ab.py capture
--session results/gta4-scheduler-20261030 --mode B
--label spu-rsx0060-run1 --expected-resolution 150\`
and the same three \`--expected-tuning ...=0\` flags as
before; repeat with label \`spu-rsx0060-run2\`.
Reject any run with nonzero \`new_spu_compilations\`
even if \`valid: true\`.
Parse with \`python tools/gta4-worker-activity.py
results/gta4-scheduler-20261030/B-spu-rsx0060-run1\`
and matching run2. Check \`PS5 WORKER:\` emitted,
\`PS5 FRAMEDEP:\`, \`PS5 PERF:\`, \`PS5 FIFO2:\`,
\`PS5 CLOCK2:\`, and \`PS5 PROFILE \` absent.
Compare FPS to initial/return 0058 controls and 0059, but
do not infer profiling overhead or an FPS improvement from
cross-run differences alone. Distinguish sampled FIFO
empty/NOP/spinning vs running and per-SPU gateway vs cpu_work
before choosing the first optimisation.

**Safest rollback:** \`python3 tools/deploy-gta4-rsx0060.py rollback\`
only after user again confirms both GTA IV and KB-RPCS3 closed;
the helper independently checks the console process list.
No console write if title running.


## 2026-10-30 ~05:40–05:42 UTC — Patch 0060 SPU/RSX worker measurements

User replied **"SPU/RSX worker ready"** with GTA IV stationary
at the previous outdoor camera on installed patch0060,
150% rendering scale, B / RPCS3 Scheduler, Mega SPU,
Approximate XFloat, 100% clocks, all three experimental
SPU tuning flags OFF. No console file writes during measurement.

Two independent 45-second captures:
- \`results/gta4-scheduler-20261030/B-spu-rsx0060-run1.{json,log}\`
- \`results/gta4-scheduler-20261030/B-spu-rsx0060-run2.{json,log}\`
- Per-run parsed
  \`B-spu-rsx0060-run1-worker-activity.json\` and
  \`B-spu-rsx0060-run2-worker-activity.json\`
- Combined machine-readable result
  \`results/gta4-rsx-perf-20261030/spu-rsx-worker-0060-combined.json\`.

Both captures were tool-VALID, at 150%, zero new SPU
compilations, produced \`PS5 WORKER:\` reports, no
\`PS5 FRAMEDEP:\`, \`PS5 PERF:\`, \`PS5 FIFO2:\`,
\`PS5 CLOCK2:\` or \`PS5 PROFILE \` events, and
no worker-slot allocation overflow. Parser now emits
\`spu_measurement_valid\` and \`spu_measurement_warning\`
to explicitly flag unpopulated SPU measurements.

| Patch0060 measurement | Run 1 | Run 2 |
| --- | ---: | ---: |
| FPS reporting-window mean | 24.93 | 27.49 |
| Timestamp-weighted FPS | 24.927 | 27.492 |
| Mean p50 frame interval | 40.23 ms | 36.38 ms |
| Mean p95 frame interval | 44.15 ms | 39.83 ms |
| Mean p99 frame interval | 46.16 ms | 41.44 ms |
| New SPU compilations | 0 | 0 |
| SPU worker timing reports | **0** | **0** |
| RSX worker timing reports (whole log) | 109 | 182 |
| Secondary SPU host CPU utilisation (capture-aligned) | 98.45% | 98.58% |
| Primary SPU2 CPU utilisation | 96.73% | 96.58% |
| RSX host CPU utilisation | 92.27% | 93.42% |
| GTA PPU RenderThread host CPU utilisation | 83.18% | 81.75% |

**SPU probe failed to cover its target**: neither run produced
SPU JIT gateway nor SPU cpu_work timing, despite near-core-full
SPU host CPU occupancy. Do **not** interpret as idle SPUs.
Review \`SPUThread.cpp::cpu_task()\`: current 1-in-256
\`spu_runtime::g_gateway\` timing is recorded only AFTER
the gateway returns, which may occur too rarely for
long-running JIT execution. Likewise, 1-in-1024
\`spu_thread::cpu_work\` completion may be too sparse.
These are hypotheses to verify with entry/return counts
and safe event-boundary observation in a follow-on build.
Do not optimise SPU helper functions or claim guest
instruction time from these missing data.

**RSX FIFO sampler DID work**. Shares below are only of
sampled \`run_FIFO\` CPU wall-time and are NOT full
RSX-thread CPU percentages, summed per-frame time, or
proven per-command counts. Classification uses the
FIFO state at return and a deterministic 1/512 stride,
so sampling bias is possible:

| Sampled run_FIFO CPU time by post-state | Run 1 | Run 2 |
| --- | ---: | ---: |
| Running | **79.73%** | **83.02%** |
| Spinning/self-jump | **15.62%** | **12.32%** |
| NOP | **4.61%** | **4.64%** |
| Empty | **0.04%** | **0.01%** |

Sample counts/time:
- Running: **232,261 / 262,202** sampled calls,
  mean **0.323 / 0.344 microseconds**, max up to ~3.5 ms.
- Spinning: **3,675 / 2,981** sampled calls,
  mean **3.996 / 4.495 microseconds**.
- NOP: **86,407 / 97,612** sampled calls,
  mean **0.050 / 0.052 microseconds**.
- Empty: only 12 / 7 sampled calls.

Next RSX optimisation candidate is the
**FIFO self-jump/spinning idle policy**, but it has
important producer-consumer and wake-latency semantics.
Measure/report time versus scheduler wake delay and
verify progress/graphics correctness; do not blindly
suppress, skip or sleep FIFO polling. A different
possible productive-path candidate is RSX vertex/index
staging and decoder, which has earlier preliminary
symbol evidence; distinguish it from polling first.

Two-run patch0060 mean of timestamp-weighted FPS is
**26.2095 FPS**. Previously collected four patch0058
OFF 150% controls had mean **24.245 FPS**; patch0059
trace mean **22.795 FPS**. The observed +1.964 FPS
over pooled patch0058 controls is **NOT a causal speedup**:
patch0060 changes diagnostic sampling rather than
emulation algorithm, and scene variation was already
large (patch0058 two 150% return controls at ~25.409
and ~21.927). Do not infer an optimisation effect.

**Current PS5 state**: GTA IV and KB-RPCS3 **RUNNING**
patch0060 at 150%; user may move character after the
two completed samples. Do not overwrite title or config
until user explicitly says both closed, and the live
PS5 process listing confirms. Patch0059 is preserved
as immediate backup with
\`*.before-rsx0060-20261030\`; patch0058 profiler-OFF
control is also preserved one generation earlier.

**Next focus**: correct SPU gateway/helper probe coverage,
then test an isolated RSX FIFO polling/wake policy against
the unmodified 0060 diagnostic as control, with matched
FPS and correctness checks. Any code changes should
preserve guest state and not infer GPU completion time.


## 2026-10-30 - Patch0061 watched self-jump OS-yield experiment READY LOCALLY

User selected the FIFO self-jump/wake-policy experiment. Implemented an
opt-in `rsx_fifo_yield` key (ABI key 11): 0/default keeps the shared
PS5 yield wrapper, 1 directly calls `scePthreadYield` only for an active
unchanged self-jump watch with no pending arguments. True-empty queues,
FIFO ordering, guest state and existing outer-loop handling are preserved.
Potential producer progress benefit versus RSX wake-latency cost remains
unmeasured. This is not a claimed FPS gain.

Durable core patch: `port/rpcs3-latest-patches/0061-PS5-opt-in-self-jump-OS-yield.patch`;
selected manifest now 61 patches. Actual source is Ubuntu-24.04
`/home/callum/work/rpcs3-latest`; Windows emulator checkout untouched.

Host dispatch/watch/parser/rollback checks, existing DMA wait and worker
counter checks, and exact 0060-to-0061 patch replay PASS. Full latest-profile
build PASS, native TLS verified and all nine package gates PASS.

Full experiment design, artifact hashes and validation are in
`game research/GTA-IV-FIFO-yield-experiment-20261030.md`; local machine-readable
build record is `results/gta4-fifo-yield-20261030/build.json`.
Signed title and mirror are local only. Installer
`tools/deploy-gta4-rsx0061.py` verifies hashes and console process state,
uses isolated stage/backup names and preserves the 0060 rollback pair.
`tools/gta4-fifo-yield.py` prepares reversible mode variants and restores
the exact original tuning file/absence. Original console tuning was absent.

Latest read-only console status: live file sizes still match patch0060;
no 0061 stage or backup. User closure confirmation is pending. Do not
modify console executables or tuning while GTA IV/KB-RPCS3 are running.
After closure: install 0061 in mode 0, capture warmed same-scene controls,
then mode 1 and return mode 0 with two 45-second captures each (A/B/A).
Keep B scheduler / Mega / Approximate / 150% / 100% clocks and SPU flags
OFF. Reject compilation-heavy windows, validate gameplay and do not
attribute cross-scene variation or lower CPU occupancy to an FPS win.


### Patch0061 installed and verified after user closure confirmation

User replied **Both are closed**. Stage and activation process checks
confirmed no title/launcher. Both staged and installed pairs passed
decrypted-ELF load/TLS verification and exact mirror SHA256 readback.
Live 0061 ELF/mirror: 117429696 / 74604561 bytes; previous 0060 pair
is retained as `*.before-rsx0061-20261030` (117429696 / 74604305).
No game config, saves, caches or other backups changed. Initial mode
is 0/control; original tuning file was absent. Build record now marks
console_deployed=true. No 0061 gameplay/FPS captures yet.

NEXT USER ACTION: launch same warmed outdoor scene/camera and say
`FIFO control ready`. Capture two 45s controls with rsx_fifo_yield=0
and the unchanged B/Mega/150%/SPU-flags-off expectations, then close
title before applying mode1 via `tools/gta4-fifo-yield.py os-yield`.
See dedicated experiment document for A/B/A and rollback instructions.


## Patch0061 initial control captures and candidate enabled - 2026-10-30

User said `FIFO control ready`. Captured two independent 45-second
windows at the stationary outdoor scene, runtime-confirmed scheduler B /
Mega / Approximate / 150% / 100% clocks / 60 FPS cap, SPU experiments OFF
and `rsx_fifo_yield=0`. Both valid, 11 FPS windows each, no new SPU compilation.

| Metric | Control run 1 | Control run 2 |
| --- | ---: | ---: |
| Window mean FPS | 26.69 | 25.83 |
| Timestamp-weighted FPS | 26.691 | 25.827 |
| Mean window p50 interval ms | 37.45 | 38.77 |
| Mean window p95 interval ms | 41.91 | 42.36 |
| Mean window p99 interval ms | 44.47 | 43.86 |
| Mean window 1% low FPS | 22.75 | 22.85 |
| Sampled FIFO wall time classified spinning | 11.20% | 12.44% |

Two-run mean: **26.26 FPS** (timestamp-weighted run-mean 26.259).
Window percentiles are not pooled frame percentiles. FIFO fractions are
sampled run_FIFO CPU wall time, not frame latency or full RSX duty cycle.
RSX worker measurements valid, no slot overflow, old heavy diagnostic and
frame-event markers absent. SPU measurements remain uncovered (zero samples);
do not interpret as idle SPUs. No candidate FPS measurement yet.

Raw captures and parsed worker reports:
`results/gta4-fifo-yield-20261030/B-fifo0061-control-run{1,2}.{json,log}`
and corresponding `-worker-activity.json`; combined result:
`results/gta4-fifo-yield-20261030/control-0061-combined.json`.

After captures, user explicitly confirmed **Both are closed**. The tuning
helper independently verified no title/launcher process, applied
`rsx_fifo_yield 1`, and verified exact readback. Independent status confirmed
17 bytes, SHA256
`b3679ae800aa0e1555aec2cc0cc65e65e855316d0b25ee71b0157e3b8a9737c2`.
Only the tuning file changed; same patch0061 executable/mirror. Existing
other settings and backups untouched. Original absent tuning state is
saved locally for restore.

**NEXT USER ACTION:** launch the same save/stationary outdoor camera, let
compilation settle, reply `FIFO candidate ready`. Capture two 45-second
runs named `fifo0061-os-yield-run1`, `run2` with the same settings checks
and `--expected-tuning rsx_fifo_yield=1`; reject any SPU compilations.
Compare to the above control, then close game/title before switching back
with `tools/gta4-fifo-yield.py control` for two return controls. Do not
claim an improvement or discard a possible regression before the switchback.


## Patch0061 direct OS-yield candidate measured; original tuning restored - 2026-10-30

User said `FIFO candidate ready`. Two separate 45-second candidate captures
passed all runtime checks (B scheduler, Mega, Approximate, 150%, 100% clocks,
60 FPS cap, SPU experiments OFF, rsx_fifo_yield=1). Both recorded zero new
SPU compilations and 12 FPS windows. No console writes during capture.

| Metric | Initial control 1 | Initial control 2 | Candidate 1 | Candidate 2 |
| --- | ---: | ---: | ---: | ---: |
| Mean window FPS | 26.69 | 25.83 | 26.69 | 25.11 |
| Timestamp-weighted FPS | 26.691 | 25.827 | 26.692 | 25.108 |
| Mean window p50 ms | 37.45 | 38.77 | 37.45 | 39.93 |
| Mean window p95 ms | 41.91 | 42.36 | 41.40 | 43.60 |
| Mean window p99 ms | 44.47 | 43.86 | 43.32 | 45.98 |
| Mean window 1% low FPS | 22.75 | 22.85 | 23.18 | 21.86 |

Initial control timestamp-weighted run mean **26.259 FPS**, candidate
**25.900 FPS**: observed **-0.359 FPS (-1.37%)**. Candidate mean p95
42.500 vs 42.135 ms, p99 44.650 vs 44.165 ms, 1% low 22.52 vs 22.80 FPS.
These are means of watchdog-window summaries, not pooled frame percentiles.
**No demonstrated performance improvement.** The small observed slowdown is
within the prior scene/run variation; return controls are needed to separate
policy effect from scene drift. Do not promote mode 1 based on these results.

Candidate sampled FIFO post-state shares (run1/run2): running 83.10/79.95%,
spinning 12.18/15.64%, NOP 4.60/4.39%, empty 0.13/0.02%. Sampled spinning
invocation means 3.397/3.635 us vs control 3.610/3.962 us. These are sampled
run_FIFO CPU wall times, not full thread duty cycle, frame latency or direct
OS wake latency. There is no per-policy yield call counter. Both candidate
worker parses have valid RSX coverage, zero allocation overflow, old heavy
profiler absent and frame tracer disabled. SPU samples remain absent; do not
infer idle SPUs or optimise uncovered helper paths from this result.

Raw candidate captures/worker parses:
`results/gta4-fifo-yield-20261030/B-fifo0061-os-yield-run{1,2}.{json,log}`
and corresponding `-worker-activity.json`. Combined verified result:
`results/gta4-fifo-yield-20261030/candidate-0061-combined.json`.

User then explicitly confirmed **Both are closed** for restoring the
original policy. `tools/gta4-fifo-yield.py restore` independently checked
no title/launcher process and restored the exact original **absence** of
ps5-tuning.txt. Independent status confirmed absent/all defaults, hence
rsx_fifo_yield=0. Patch0061 executable/mirror and all backups unchanged.
No game configs, saves, game data or caches modified.

The workspace `AGENTS.md` now requires reading the latest game research
before new work, recording each meaningful investigation/benchmark/failed
experiment before handoff, keeping current state and the exact next action,
and justifying repeats using changed conditions or required controls.
This return-control phase is the planned A/B/A crossover, not a rerun of
an abandoned optimisation.

**NEXT USER ACTION:** launch the same warmed stationary outdoor scene/camera
and reply `FIFO return control ready`. Capture two 45s runs named
`fifo0061-return-control-run1`, `run2`, expecting rsx_fifo_yield=0 and all
other original settings. Reject SPU compilation, compare A/B/A, and record
the conclusion before proposing another optimisation. Original tuning is
already restored; no further tuning cleanup needed after those captures.


## Patch0061 A/B/A complete - direct OS yielding shows no useful FPS gain (2026-10-30)

User said `FIFO return control ready`. Captured two more independent 45s
stationary outdoor windows with original absent tuning file (mode 0).
Both passed scheduler B / Mega / Approximate / 150% / 100% clocks / 60 cap /
SPU-experiments-OFF checks, 11 FPS windows each, zero new SPU compilations.
No console file writes during these measurements.

| Metric | Initial A1 | Initial A2 | Candidate B1 | Candidate B2 | Return A1 | Return A2 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Mean window FPS | 26.69 | 25.83 | 26.69 | 25.11 | 26.03 | 25.35 |
| Timestamp-weighted FPS | 26.691 | 25.827 | 26.692 | 25.108 | 26.027 | 25.345 |
| Mean window p95 ms | 41.91 | 42.36 | 41.40 | 43.60 | 42.35 | 44.02 |
| Mean window p99 ms | 44.47 | 43.86 | 43.32 | 45.98 | 44.80 | 48.07 |
| Mean window 1% low FPS | 22.75 | 22.85 | 23.18 | 21.86 | 22.50 | 21.29 |

Timestamp-weighted phase means: initial A **26.259**, candidate B **25.900**,
return A **25.686 FPS**. The candidate falls between the two controls.
All four A runs average **25.9725 FPS**, candidate difference **-0.0725 FPS
(-0.28%)**. This descriptive difference does not establish a causal slowdown.
Initial-to-return drift (0.573 FPS) and within-phase variation are larger.
Window percentiles above are means of summaries, not pooled frame percentiles.

**Decision: no demonstrated useful framerate gain; retain the original
policy and stop this direct-OS-yield candidate.** No more repeats of the same
policy/scene/build are justified without new evidence or a materially changed
hypothesis. Do not claim a speedup from lower sampled spin duration, CPU load,
or a better tail in one run. No comprehensive candidate gameplay correctness
assessment was supplied; there is no reason to adopt it from these FPS data.

Return sampled FIFO spinning shares: 13.68% / 15.44% (initial 11.20/12.44%,
candidate 12.18/15.64%). These are sampled run_FIFO CPU wall time only.
All six worker parses have valid RSX samples, zero slot-allocation overflow,
old heavy profiler absent and old frame-event tracer disabled. SPU coverage
is still missing; this is not evidence of idle SPUs or a measured helper cost.

New raw files:
`results/gta4-fifo-yield-20261030/B-fifo0061-return-control-run{1,2}.{json,log}`
and matching `-worker-activity.json`. Full six-run validated comparison:
`results/gta4-fifo-yield-20261030/fifo0061-aba-comparison.json`.
The build record now marks experiment_complete=true.

**Current console:** patch0061 installed, `rsx_fifo_yield=0`, original tuning
file absence already restored. Game/title running at the end of capture;
user may move the camera now. No further cleanup or console changes needed.
Exact patch0060 executable/mirror rollback remains preserved as
`*.before-rsx0061-20261030`; rollback only with game/title stopped. Do not
replace executables or change tuning while the title is running.

**Next engineering focus:** repair the missing SPU gateway/helper timing
coverage with low-overhead entry/return or safe event-boundary observation,
then select a measured hot path. Do not blindly change helper semantics or
repeat this FIFO direct-yield experiment. This is a proposed next investigation,
not work performed or an FPS gain promised by the completed experiment.


## Patch0062 SPU coverage repair built locally - 2026-10-30

User requested fixing missing SPU timing coverage. Confirmed source defect:
old gateway probe skips first 255 calls, records only after return, and
watchdog hides registered slots with no completed samples. This can miss a
long-lived first gateway entirely; exact console explanation remains to be
verified with new entry/return/live data. cpu_work is a specific pending-work
path, not all SPU execution. No idle-SPU conclusion follows from missing data.

Implemented patch0062 with cumulative task/JIT/gateway/cpu_work counts,
active gateway/helper sample age, first/all-gateway timing, first/1024th
cpu_work samples independent of the emulator iteration counter, registration
failure reporting and explicit abandonment cleanup at gateway return.
g_escape restores the stack without C++ unwinding: no destructor timer is
relied on across that boundary. RSX sampling, guest execution, JIT codegen,
synchronisation, scheduling and default FIFO policy unchanged.

Host two-translation-unit live/first/completion/escape tests PASS; parser
synthetic tests PASS; regression parsing of all six 0061 FIFO captures retains
exact FPS and worker timing data. Isolated patch replay reproduces the three
actual WSL build source files; full PS5 build, native TLS and all nine package
gates PASS. Single linked shared SPU slot array verified. Diagnostic overhead
and live console coverage still need testing; no FPS gain claimed.

Research: `game research/GTA-IV-SPU-coverage-20261030.md`.
Core patch: `port/rpcs3-latest-patches/0062-PS5-report-live-SPU-gateway-coverage.patch`.
Parser: `tools/gta4-worker-activity.py`. Selected manifest now 62 patches.
Exact build hashes/local artifacts and validation:
`results/gta4-spu-coverage-20261030/build.json`.
Actual build source: Ubuntu-24.04 `/home/callum/work/rpcs3-latest` as callum;
Windows emulator checkout untouched. Earlier edits preserved.

Console read-only status still matches 0061 (117429696/74604561 bytes),
no 0062 stage or backup. Hash-pinned paired installer
`tools/deploy-gta4-rsx0062.py` is ready. Exact local 0061 signed/converted/mirror
control archived before rebuild. All older console backups preserved.
User closure confirmation pending for installing this new pair. Do not stage
or replace while title running. After closure and process checks: install,
then user boots same warmed 150%/B/Mega scene; capture two 45-second
spu-cover0062 runs with original tuning defaults and zero SPU compilation.
Distinguish live coverage from completed intervals and record findings before
selecting a SPU optimisation. Do not repeat failed FIFO direct-yield candidate.


## Patch0062 installed and verified after user closure confirmation - 2026-10-30

User explicitly replied **Both are closed** for GTA IV and KB-RPCS3.
`tools/deploy-gta4-rsx0062.py stage`, independent status, then `activate`
completed successfully. Process checks passed before staging, on activation
entry and immediately before renames. Both staged and installed readbacks
matched the local converted ELF load/TLS segment bytes and exact code-mirror
SHA256. Signed SELF was not incorrectly hash-compared to FTP's decrypted ELF.

Independent post-activation status:
- Live patch0062 decrypted ELF: **117434056 bytes**.
- Live mirror: **74605073 bytes**, SHA256
  `5430f413e0574d082fa71add8e6b40dcf2a1a6bf714212f77469e5883d8a0d60`.
- Stage empty; exact prior 0061 pair retained as
  `*.before-rsx0062-20261030` (**117429696 / 74604561 bytes**).
- Original tuning file remains **absent**, independently verified: FIFO
  mode 0, SPU experiments OFF. No game configs, saves, caches or game data
  modified. Older backup chains preserved.

Machine-readable build record now marks console_deployed=true with
verification and rollback state. Runtime coverage remains **unverified**:
no patch0062 game launch/capture has yet been recorded. No FPS gain claimed.

**NEXT USER ACTION:** launch GTA IV, same stationary outdoor camera/save,
allow compilation to settle, and reply `SPU coverage ready`. Capture two
45s runs with unique labels `spu-cover0062-run1`, `run2`, using scheduler B,
150% and expected tuning rsx_fifo_yield=0, spu_insert_select=0,
spu_narrow_ls_store=0, spu_narrow_ls_check=0. Reject new SPU compilations.
Parse via `tools/gta4-worker-activity.py`; distinguish completed intervals
from SPUCOVER live entry/age snapshots, inspect entry/return counts,
cpu_work visits, abandoned samples, zero IDs, allocation overflow and FPS.
Record whether actual live data supports the long-lived gateway hypothesis
before selecting any SPU optimisation. Do not interpret inclusive age as
productive CPU time or repeat the completed FIFO direct-yield experiment.

Rollback only after closing game/title and passing process checks:
`python3 tools/deploy-gta4-rsx0062.py rollback` restores the paired 0061
backup and retains 0062 as stage. No rollback is requested now.


## Patch0062 on-console SPU coverage VERIFIED - two GTA IV captures (2026-10-30)

User said `SPU coverage ready`. Two independent 45-second captures passed
all expected runtime checks: B scheduler / Mega / Approximate / 150% /
100% clocks / 60 cap, rsx_fifo_yield=0 and all three SPU experiments OFF.
Zero new SPU compilations in both, no console writes during measurement.

| Metric | Run 1 | Run 2 |
| --- | ---: | ---: |
| Mean FPS reporting windows | 25.86 | 26.55 |
| Timestamp-weighted FPS | 25.858 | 26.555 |
| Mean window p50 interval ms | 38.52 | 37.56 |
| Mean window p95 interval ms | 43.44 | 41.45 |
| Mean window p99 interval ms | 45.08 | 43.07 |
| Mean window 1% low FPS | 22.24 | 23.27 |
| New SPU compilations | 0 | 0 |
| Registered SPUs with live gateway coverage | **6** | **6** |
| Accepted cpu_work entries, all six | **0** | **0** |
| Zero-ID registration / allocation overflow | 0 / 0 | 0 / 0 |

Weighted run-mean **26.2065 FPS**. These are means of watchdog-window
summaries, not pooled frame percentiles. This measurement-only build is
not a demonstrated speedup; the run differences do not quantify its overhead.
Old heavy diagnostics and frame tracer are absent; RSX samples remain valid.

**Coverage fix is verified on console.** All six SPUs report one active
native gateway at each observed watchdog report. At the end of run2:

| Guest ID | Gateway entries / returns since task start | Current live gateway age s | Accepted cpu_work entries |
| --- | ---: | ---: | ---: |
| 0x00000100 | 51 / 50 | 40.301 | 0 |
| 0x00000200 | 5 / 4 | 181.277 | 0 |
| 0x01000100 | 46 / 45 | 43.295 | 0 |
| 0x02000100 | 12 / 11 | 110.907 | 0 |
| 0x03000100 | 9 / 8 | 126.899 | 0 |
| 0x04000100 | 4 / 3 | 147.155 | 0 |

Every total is below the old first sample at call 256. The live calls span
many frames/capture boundaries. This supports the diagnosed gateway
sampling blind spot; the earlier missing data did not mean idle SPUs.
`cpu_work()` has zero accepted visits for this session, so repeatedly
sampling that pending-work path cannot explain this workload's guest work.
This is evidence about the instrumented path, not a claim that no SPU
DMA/channel helper executes elsewhere inside the gateway.

Completed gateway samples also appear: run1 emits one ~1.594540 s interval
for ID 0x00000100; run2 emits ~64.530915 s for 0x00000100 and ~65.148844 s
for 0x01000100. **These durations span time before the capture in which
completion is reported.** Do not sum/divide them as the capture's CPU duty
cycle or per-frame cost. Per-ID entry/return deltas cover report-to-report
boundaries, not the exact start/end of the 45-second capture; this explains
why a completed counter drain and first snapshot need not share that delta.
Live ages are inclusive wall time: guest JIT, nested helpers, waits and
OS descheduling remain unresolved. Active gateway snapshots are not proof
of continuous useful CPU execution or the frame-critical bottleneck.

Raw evidence:
- `results/gta4-spu-coverage-20261030/B-spu-cover0062-run{1,2}.{json,log}`.
- Corresponding `-worker-activity.json` and `run{1,2}-parser.txt`.
- Full validated aggregate:
  `results/gta4-spu-coverage-20261030/spu-coverage-0062-combined.json`.
- Build record now marks console_runtime_verified=true and coverage_fix_verified=true.

**Current state:** patch0062 running, exact original absent tuning file
unchanged, FIFO mode0/SPU experiments OFF, 0061 paired rollback retained as
`*.before-rsx0062-20261030`. Older backups preserved. User may move the camera
now; no cleanup or extra capture is required for this coverage-fix task.
Do not modify binaries/tuning while the title is running.

**Next measured investigation, not yet implemented:** observe actual LLVM
JIT-to-channel/MFC helper boundaries (for example exec_rdch and exec_mfc_cmd)
to distinguish nested helper/wait occupancy from guest JIT execution before
selecting an optimisation. Use low-overhead explicit boundaries compatible
with g_escape, not per-instruction timing or another blind cpu_work probe.
Do not repeat the completed FIFO direct-yield candidate or this coverage
validation without new evidence. No FPS improvement is claimed here.


## Patch0063 native SPU helper boundary diagnostics ready locally - 2026-10-30

Following verified six-gateway coverage/zero cpu_work visits, source review
located ten actual native LLVM channel/MFC/event/STOP helpers, including
wait_on_spu_channel that bypasses exec_rdch. Added entry/return/escape counts,
sparse live kind/argument/age snapshots, and first/1024 normal versus escaped
duration samples. Explicit gateway cleanup handles g_escape without relying
on C++ unwinding; nested measured helpers are suppressed/counted.
Outside measured helpers is unresolved, not a pure guest JIT classification.
No guest IR, channel/MFC semantics, scheduler or default FIFO changes.

Actual ten helper bodies tested with probes ON/OFF, original state/returns,
real longjmp cleanup, sampling and nesting PASS. Helper/coverage parsers,
eight legacy captures, isolated patch replay and full PS5 build/TLS/all nine
package checks PASS. Diagnostic overhead and on-console helper activity
remain unmeasured. Selected manifest now 63 patches; previous work preserved.

Research: `game research/GTA-IV-SPU-helper-boundaries-20261030.md`.
Core patch: `port/rpcs3-latest-patches/0063-PS5-observe-SPU-LLVM-helper-boundaries.patch`.
Tools: `tools/gta4-spu-helpers.py`, `tools/deploy-gta4-rsx0063.py`.
Hashes/control archive/validation: `results/gta4-spu-helpers-20261030/build.json`.
Console read-only sizes remain0062; no0063 stage/backup. User closure pending.
Next: after closure/process checks install, launch same scene, reply
SPU helper ready, then capture two 45s runs expecting tuning0. Parse helper
and worker records; document observations before optimising. No speedup claim.


## Patch0063 installed and readback-verified - 2026-10-30

User explicitly confirmed **Both are closed** for GTA IV and KB-RPCS3.
Paired installer stage and activate completed with independent status between
them. Process checks passed before staging, at activation entry and immediately
before renames. Both staged and installed pairs verified decrypted-ELF load/TLS
segment bytes against the local converted ELF plus exact code-mirror SHA256.

Independent final status: live ELF **117434488 bytes**, mirror **74611793
bytes** (SHA256 `8ef00a6f9a4cece63e4de693c667b7921ac2fa5325b46758307f09ade63b8fca`),
stage empty, previous 0062 pair preserved as `*.before-rsx0063-20261030`
(**117434056 / 74605073 bytes**). Older backup chains intact. Original tuning
file still **absent**, independently verified: FIFO0/SPU experiments OFF.
No game configs, saves, caches or game files changed.

Machine build record now marks console_deployed=true with verification and
rollback state. **No gameplay/runtime helper capture yet; no FPS gain claim.**

**NEXT USER ACTION:** launch GTA IV, return to same stationary outdoor save/
camera, allow compilation to settle and reply `SPU helper ready`. Capture two
45s runs named `spu-helpers0063-run1`, `run2` in
`results/gta4-spu-helpers-20261030`, scheduler B, resolution150, expecting
rsx_fifo_yield=0, spu_insert_select=0, spu_narrow_ls_store=0,
spu_narrow_ls_check=0. Reject new SPU compilations. Run both
`tools/gta4-worker-activity.py` and `tools/gta4-spu-helpers.py` on each stem.
Check helper reporting presence, actual entry deltas, active kind/argument,
normal versus escaped sampled durations, nested suppression, unstable
observations, registration errors and FPS. Outside measured helpers is
unresolved, not proof of pure guest JIT; point counts are not time fractions.
Record results before choosing an optimisation or another diagnostic change.

Rollback after closing title/process checks only:
`python3 tools/deploy-gta4-rsx0063.py rollback` restores the exact 0062 pair
and retains 0063 as stage. No rollback requested now.


## Patch0063 helper findings captured; lighter0062 restored - 2026-10-30

User said `SPU helper ready`. Two independent 45s captures passed B/Mega/
Approximate/150%/100%-clocks/60-cap checks with FIFO0 and SPU experiments OFF.
Zero new SPU compilations, six live SPUs/helper reports, no registration errors,
no nested suppression or unstable snapshots. Older heavy profiler and frame
tracer absent. No console writes during either measurement.

| Metric | Run1 | Run2 |
| --- | ---: | ---: |
| Mean window FPS | 23.40 | 23.18 |
| Timestamp-weighted FPS | 23.400 | 23.182 |
| Mean window p95 ms | 48.24 | 47.56 |
| Mean window p99 ms | 51.34 | 50.26 |
| Mean window 1% low FPS | 19.51 | 19.93 |
| Direct native mfc_cmd entry delta, all six SPUs | 97459370 | 98180880 |
| wrch entry delta, all six SPUs | 38633290 | 38526586 |
| rdch entry delta, all six SPUs | 734631 | 783033 |

Helper report-to-report spans are ~44.362s (not exactly the nominal45s).
These direct native MFC entries amount to ~2.20/2.21 million per second,
plus ~0.87 million wrch calls/s. wrch can itself invoke process_mfc_cmd;
these counts do not represent a complete per-command histogram of all MFC
work. Only rdch/wrch/mfc_cmd had counter rows; do not infer other host paths
are absent from the gateway or classify outside-helper work as pure JIT.

Sampled normal MFC duration means (microseconds, includes probe/wait/descheduling):

| Guest ID | Run1 | Run2 |
| --- | ---: | ---: |
| 0x00000100 | 0.287 | 0.279 |
| 0x00000200 | 0.211 | 0.205 |
| 0x01000100 | 0.280 | 0.282 |
| 0x02000100 | 0.251 | 0.246 |
| 0x03000100 | 0.225 | 0.227 |
| **0x04000100** | **1.683** | **1.536** |

This consistent outlier makes MFC command handling on 0x04000100 the next
specific source-audit target. It is not proof that this SPU is the serial
frame bottleneck: command mix, memory contention and scheduling may differ.
No helper escape intervals occurred in these windows; escape cleanup is
host-tested, not exercised by these gameplay samples.

Stable live observations: run1 outside=56, rdch=6, mfc_cmd=10; run2
outside=57, rdch=4, wrch=3, mfc_cmd=8, out of72 observations each.
These are sparse point counts, **not CPU time fractions**. All active rdch
snapshots had ch0 = SPU_RdEventStat. Sampled rdch means ranged ~14-322us,
consistent with potential waits but not productive CPU cost attribution.
Active MFC arguments were 0xD0 GETLLAR (7/5 observations), 0xB4 PUTLLC
(2/2), 0xB0 PUTLLUC (0/1), and 0x20 PUT (1/0). Active wrch snapshots were
channel21 MFC_Cmd (0/3). Constants checked in Cell/MFC.h and SPUThread.h.
This is **not** a command-frequency histogram; do not assume those atomic
commands dominate all entries from a handful of watchdog observations.

**Diagnostic overhead concern / decision:** 0063 weighted run mean
**23.291 FPS**, earlier0062 mean **26.2065 FPS**, observed -2.9155 FPS
(~-11.13%). Different launches, game-world/scene drift and no controlled
switchback mean this is not a proven causal overhead percentage. However,
millions of entry atomics/TSC reads per second are a concrete instrumentation
cost. Do not leave these probes in ordinary performance builds or claim that
sub-microsecond sample means are uninstrumented helper costs. Cumulative
counter rows and sampled wall intervals must not be summed as frame time.

User explicitly confirmed **Both are closed** after captures to restore
lighter0062. Installer checked actual processes and rollback succeeded.
Both live files were independently downloaded and verified against archived
0062 hashes/load/TLS segments (not SELF-vs-decrypted-ELF hash confusion).
Final status: live0062 ELF117434056/mirror74605073; 0063 pair preserved under
`*.rsx0063-stage` (117434488/74611793), backup suffix now empty. Original
ps5-tuning.txt remains absent, independently verified. Older backups/configs/
saves/caches/game files preserved. No further user action needed for this
measurement task; normal gameplay can use the restored lighter build.

Evidence:
- `results/gta4-spu-helpers-20261030/B-spu-helpers0063-run{1,2}.{json,log}`.
- Matching `-worker-activity.json`, `-spu-helpers.json` and parser text files.
- Full combined/validated counts and rates:
  `results/gta4-spu-helpers-20261030/spu-helpers-0063-combined.json`.
- Independent rollback proof:
  `results/gta4-spu-helpers-20261030/rollback-verification/verified.json`.

**Next specific work:** audit SPUThread.cpp process_mfc_cmd, especially
GETLLAR/PUTLLC/PUTLLUC reservation handling and its scheduler watchdog, using
0x04000100's outlier as the lead. Preserve guest synchronization and ordering;
command mix is unresolved. Prefer a source-backed, semantic-preserving
candidate over another broad instrumentation pass. Any performance candidate
must compile out/remove0063 helper probes and compare to exact0062 control.
Local source/manifest still includes patch0063; console is restored0062.
Do not accidentally rebuild/deploy the full helper probes as a release
optimisation. Do not repeat completed FIFO, gateway-coverage or broad helper
captures without changed evidence or a justified control. No FPS gain claimed.


## MFC reservation source audit complete - 2026-10-30

User requested a correctness-preserving optimisation audit. No production
emulator/config/build/console changes made in this task. Source tracing ruled
out scheduler acquire/release work under measured Preferred SPU Threads=0
and RSX reservation locking under Accurate RSX reservation access=false.
Both options are dynamic: do not hardcode/cross-call-cache the measured values.

Recommended narrow candidate is PS5-only gating of reporting-only perf_meter
entry construction in do_putllc and do_putlluc when perf_report is off.
Exact0062 ELF has unconditional entry RDTSC in both functions; their timer
uses are reporting-only. Actual perf_meter host harness verifies disabled
reads eliminated and fixed-enabled sample behavior retained. Dynamic mid-call
enable skips the in-flight candidate meter event; tested/documented rather
than claiming exact diagnostic equivalence. Isolated diff applies cleanly;
no guest statements outside constructor blocks differ in proposed fixture.
No candidate PS5 build/performance result or full reservation equivalence proof.

GETLLAR timestamps drive functional retry/spin policy and remain untouched.
Repeated data/version checks, accurate locks, faults, LR events and notifier
wakes must remain. Moving scan16_rdata is deferred pending local-store race/
lock-order proof. Complete decisions, caveats and next step:
`game research/GTA-IV-MFC-reservation-audit-20261030.md`.
Host test: `port/tests/check-ps5-mfc-meter-audit.py`.
Audit/candidate/disassembly/proof:
`results/gta4-mfc-audit-20261030/` (audit-summary.json,
candidate-reporting-meter-gate.diff, baseline-putll-disassembly.txt,
meter-host-proof.txt). Do not treat the fixture diff as an applied port patch.

Next if proceeding: implement the two-site PS5 gate, compile out0063 helper
probes in matched baseline/candidate, focused correctness/build/assembly checks,
then controlled PS5 A/B/A. No FPS prediction: per-command frequencies remain
unknown and a single timestamp saving does not explain the0x04000100 outlier.
Console remains last verified lighter0062; no new process-state check or
console writes were needed for this audit. Local manifest still63. Record
and stop a failed candidate instead of repeating broad instrumentation.


## Patch0064 MFC meter gate implemented; two matched builds ready - 2026-10-30

User authorised implementation/testing. Two-site PS5 reporting-only meter gate
implemented with compile-time control0/candidate1. GETLLAR and guest protocol
text unchanged. Full-rate0063 helper probes/logs default compiled OFF in both;
existing0062 worker/RSX measurements shared. No runtime knob lookup added.
Actual constructor blocks tested across control/candidate/nonPS5 with named
report events; native helper semantics and OFF no-probe-cost proof PASS.
Capture tool verifies boot mode, reportingOFF and absence of helper output.

Both full PS5 builds/TLS/all9 package checks/mirror-segment hashes PASS.
Control unconditionally executes entry RDTSC; actual candidate assembly branches
past it when reportingOFF in BOTH functions. Patch replay reproduces sources.
Immutable variant archives and exact hashes: results/gta4-mfc-meter-20261030/builds.json.
Installer tools/deploy-gta4-mfc0064.py has separate control/candidate backup names.
Research/test plan: game research/GTA-IV-MFC-meter-experiment-20261030.md.

No console deployment/performance result yet. Read-only sizes still0062;
original settings/tuning/saves/caches unchanged. Fresh closure pending, then
install CONTROL, user boots reference scene and says MFC control ready.
Take2x45s A, then candidate B and return A after safe swaps. No FPS gain claimed.


## Matched0064 CONTROL installed and verified - 2026-10-30

User confirmed **Both are closed**. Stage/activation process checks found no
GTA IV/launcher. Full staged/preactivation and installed readbacks verified
control ELF load/TLS segment bytes and exact mirror SHA256. Final independent
status: liveELF117434056/mirror74605201, stage empty; exact prior0062 pair
retained as `*.before-mfc0064-control-20261030` (117434056/74605073).
Original tuning file absence independently verified. No CPU/game settings,
saves, caches or game files changed. Older backups/0063 stage preserved.

One staging anomaly was handled without activating a partial pair: the first
control executable stage disappeared after a successful readback, while live
0062 remained intact. LIST and repeated SIZE confirmed it missing. After a
fresh process check, reuploaded only that missing hash-pinned file, verified
load/TLS bytes, confirmed it present before/after readback and in independent
status. All later pre/postactivation pair checks passed. Cause unproven;
do not claim a filesystem/FTP fix or bypass incomplete-stage guards.
Repair script/evidence is in ignored results/gta4-mfc-meter-20261030.

**Current state:** CONTROL64 gate0/helper_probes0 installed. Candidate gate1
is built locally but not installed. This is the original meter behavior with
heavy helper probes compiled out, ready for matched baseline captures.
No runtime/FPS result yet. Build record reflects verified control deployment.

**NEXT USER ACTION:** launch same GTA IV save/stationary outdoor camera,
allow compilation to settle, reply `MFC control ready`. Capture2x45s labels
`mfc0064-control-run1`, `run2`, schedulerB/resolution150, all four tuning
flags0, `--expected-mfc-meter-gate 0`. The tool must see boot marker gate0/
helper_probes0, Performance Report false, no SPUHELP logs, no new SPU compilation.
After controls, close title before candidate install and later A-return swap.
Do not overwrite executables while running. No FPS benefit is established.


## Matched0064 CONTROL captures complete - 2026-10-30

User confirmed in-game readiness at the stationary outdoor reference.
Recorded two independent 45-second patch0064 control captures with
gta4-scheduler-ab.py; each validated compiled gate0/helper probes0,
Performance Report OFF, scheduler B, SPU Mega, XFloat Approximate,
resolution150, clock100, FPS cap60, required game patches applied,
rsx_fifo_yield0, spu_insert_select0, spu_narrow_ls_store0, and
spu_narrow_ls_check0. Both valid, no new SPU compilation.

| Metric | Control1 | Control2 | Mean |
| --- | ---: | ---: | ---: |
| Window mean FPS | 23.48 | 23.36 | **23.42** |
| Timestamp-weighted FPS | 23.483 | 23.364 | 23.424 |
| Mean window 1% low FPS | 20.47 | 20.18 | 20.33 |
| Mean window p50 interval ms | 42.62 | 42.88 | 42.75 |
| Mean window p95 interval ms | 47.04 | 47.16 | 47.10 |
| Mean window p99 interval ms | 48.99 | 49.72 | 49.36 |
| Sampled RSX FIFO spinning CPU fraction | 20.31% | 19.63% | 19.97% |

RSX worker measurements valid in both, zero worker slot overflow;
old heavy diagnostics absent and frame tracer disabled. SPU worker
sampling valid only in run1 (single unusual sampled gateway call);
run2 had no valid SPU worker samples, not evidence that SPUs were idle.
FIFO percentages reflect sampled RSX FIFO CPU wall time, not frame time
or a predicted FPS opportunity. These are per-window summary averages,
not pooled frame percentiles. Controls alone cannot prove a speedup.

Raw data: results/gta4-mfc-meter-20261030/B-mfc0064-control-run1.json
and B-mfc0064-control-run2.json, matching .log and
-worker-activity.json files and control-run1-parser.txt and
control-run2-parser.txt. Combined: results/gta4-mfc-meter-20261030/
control-0064-combined.json. Builds record updated; installed build unchanged.

**NEXT REQUIRED USER ACTION:** close GTA IV and KB-RPCS3 completely,
and confirm both stopped. Do not swap executable pairs while running.
After independent console process checks, run the hash-pinned 0064
candidate installer (tools/deploy-gta4-mfc0064.py --variant candidate)
and verify staged and installed ELF/mirror readbacks. Keep exact matched
control for rollback, then capture two gate1 candidate runs in the same
stationary warmed scene, and later two return-control runs after rollback.
No candidate FPS improvement has been measured.


## Matched0064 CANDIDATE installed, awaiting FPS captures - 2026-10-30

User confirmed GTA IV and KB-RPCS3 fully closed after two validated
control runs (23.48 and 23.36 FPS, two-run mean23.42). Installed matched
patch0064 candidate with PS5_MFC_METER_GATE=1, helper_probes0 using
tools/deploy-gta4-mfc0064.py --variant candidate. Initial candidate
stage/backup absent, control live sizes verified. Installer process
checks confirmed no eboot.bin or launcher before staging, at activation
entry, and immediately before renames. Staged and preactivation
decrypted ELF load/TLS matched the candidate converted build, while
mirror SHA256 matched pinned
67932ee98595f873c381e61cb7e4409ffc17c0bf61f7a4e0ebe261019241ed8a.
Both previous control files backed up before stage files activated.
Post-activation load/TLS and mirror SHA256 readback PASS, installer
exited0 with SUCCESS. First independent full status query timed out;
follow-up read-only FTP size check succeeded: live ELF117434056 and
mirror74605329, preserved control backup 117434056 / 74605201
under .before-mfc0064-candidate-20261030. Original patch0062
control-install backup retained. No game configuration, data, saves,
caches or tuning altered. Candidate in-game FPS and correctness
not yet tested.

**NEXT USER ACTION:** launch GTA IV same warmed stationary outdoor
scene and reply MFC candidate ready. Capture two45s candidate runs
mfc0064-candidate-run1 / run2 in results/gta4-mfc-meter-20261030.
Require scheduler B, resolution150, gate1 helper_probes0,
Performance Report false, four tuning flags all0, zero new SPU
compilation, and all previous game checks. Compare against control
mean23.42 FPS, then close GTA IV and KB-RPCS3 before guarded rollback
for two final return controls. No FPS gain is established.


## 2026-10-30: Chiaki-ng screenshot MCP companion built (host-only)

User requested read-only visual inspection of PS5 Remote Play while working on GTA IV.
Implemented standalone stdio MCP screenshot server inside sibling checkout
`chiaki-ng/mcp-bridge/` (NOT an RPCS3 or Chiaki Qt binary change). Windows build:
`chiaki-ng/mcp-bridge/dist/chiaki-screen-mcp.exe` (~8.4MB), source
`mcp-bridge/chiaki_screen_mcp.py`, setup and safety details in the sibling
`mcp-bridge/README.md`. Exposes `chiaki_screen_status` and
`chiaki_capture_frame`, only for a fully visible foreground Chiaki process,
read-only, max1920x1080, no game inputs, sessions, credentials or network server.
Windows Python source tests 9/9 PASS; PyInstaller package PASS;
packaged MCP initialize/list/status stdio smoke PASS; native Win32 GDI PNG
capture PASS on a synthetic window with foreground simulated in the test
harness (tool process could not claim actual desktop focus).
**Actual live Chiaki/PS5 video capture not yet tested**: the Chiaki window
was not running, and the bridge has NOT been registered as a tool in this
ChatGPT conversation. GPU/HDR/occlusion effects remain unknown. It does not
rebuild or replace the Chiaki-ng Qt app; standalone bridge is intentional
to avoid modifying decoder/controller behavior, since Qt/CMake dependencies
were unavailable locally. For GTA IV benchmarks, do not directly compare FPS
with earlier no-Remote-Play baselines without measuring Remote Play overhead.
Patch0064 candidate gate1 remained installed and its gameplay FPS capture
remained outstanding when this visual helper was built; return to the
stationary outdoor scene and the prior candidate test instructions.


### 2026-10-30 23:18 UTC: Chiaki background screen bridge LIVE validation PASS

User reported Chiaki streaming GTA IV. Verified the visible chiaki-ng
Windows client window existed, 1920x1080, while it was not foreground.
An initial foreground-only screenshot attempt was correctly refused and
Windows disallowed SetForegroundWindow from the tool process. A
**window-specific Win32 PrintWindow(PW_CLIENTONLY|PW_RENDERFULLCONTENT)**
capture returned a genuine GTA IV game frame (Niko standing outdoors
near a lamppost, map/performance overlay visible) at 640x360, with no
console or controller changes. Revised companion
`chiaki-ng/mcp-bridge/chiaki_screen_mcp.py` to version0.2.0 with
background capture restricted to allowlisted visible Chiaki windows;
other desktop applications are not targeted. Successfully rebuilt
`chiaki-ng/mcp-bridge/dist/chiaki-screen-mcp.exe`. All nine tests PASS,
Windows self-test PASS, packaged stdio MCP handshake PASS, and
**packaged binary live MCP initialize + tools/call returned a real
PNG of GTA IV while Chiaki was in the background** (640x360;
reproducible via `python chiaki-ng/mcp-bridge/tests/live_mcp_smoke.py`).
Updated sibling bridge README with build/privacy/usage details.
ChatGPT sees frame on explicit request through the connected Local File
Editor command path; not a native persistent MCP connector or continuous
video. This is *visual* evidence only, NOT a comparable FPS measure.
Still collect GTA IV gate1 candidate performance using prior recorded
scheduler B / 150% / no-Remote-Play control conditions, or quantify the
Remote Play effect with matched controls before claiming an improvement.


### 2026-10-30 23:25 UTC: PS5 dashboard control via Chiaki MCP v0.3.0 — LIVE PASS

User explicitly approved extending the screenshot-only bridge to PS5
controller inputs. Added opt-in controller tool to the sibling
chiaki-ng/mcp-bridge/chiaki_screen_mcp.py version 0.3.0. No modification
to Chiaki-ng GUI, decoder, PS5 executable, game files, or saves.
The server defaults to screenshot-only; input requires --enable-control.
chiaki_press_button accepts only ps, ps_hold, up/down/left/right,
cross (X), circle through Chiaki default keyboard mappings, PostMessageW
addressed to allowlisted visible Chiaki window. No global SendInput,
arbitrary typing, controller combos, network listener or persistent
controller access. Button duration restricted and rate-limited.
chiaki_disable_control disables the current server process.

LIVE CONFIRMATION: Initial short PS press produced a screenshot of
the PS5 Control Centre (showing "Please reconnect controller" at that
moment). Rebuilt v0.3.0 standalone executable, 15/15 source tests
PASS, packaged self-test and stdio MCP handshake PASS. Called
actual packaged MCP chiaki_press_button button=ps_hold, duration=1350ms
with opt-in and disabled process immediately afterward; fresh Chiaki
screenshot showed PS5 Games Home with KB-RPCS3 tile selected.
Then called one D-pad Right via new opt-in session: screenshot confirmed
PS5X360 tile selected. Called Left via new opt-in session: screenshot
confirmed KB-RPCS3 tile selected again. No game launched or settings
changed. README and reusable control helper at sibling
chiaki-ng/mcp-bridge/tests/live_control_mcp.py.

PS Home DOES NOT IMPLY GTA IV / KB-RPCS3 fully stopped; the game
may remain running in background. Before PS5 binary deployment, recheck
process state independently. Patch0064 MFC gate1 candidate remains
installed and FPS A/B/A benchmark is outstanding. Remote Play may affect
FPS; prior 23.42 FPS baseline should not be assumed comparable to
Remote Play conditions without matched tests.


### 2026-10-30: Agent guides updated for on-demand closed-loop PS5 testing

Updated workspace AGENTS.md and created KB-RPCS3/AGENTS.md and
chiaki-ng/AGENTS.md for future AI-assisted testing. The documented
workflow is: read latest game state, edit and build, verify both
title/launcher processes stopped, safely stage and independently
verify the paired PS5 artifacts, launch through the Chiaki-ng
screen/controller MCP bridge when available, confirm each UI step
with a fresh screenshot, capture native RPCS3 FPS/frame-time logs,
then update research and perform guarded A/B/A rollback if needed.
Agent guidance requires opt-in one-shot Chiaki button presses,
read-only screen capture by default, no blind UI navigation,
no saving private frame/base64 data, and no live executable swaps.
It explicitly notes that PS5 Games Home does NOT prove GTA IV or
KB-RPCS3 closed and that Remote Play may affect FPS comparisons.
The bridge cannot start a Remote Play session; a visible Chiaki
stream is required. It is tool-driven during an active session,
not an unattended background service. These were **documentation
changes only**, not a new runtime capture or console deployment.
Patch0064 gate1 candidate FPS runs and return-control comparison
remain outstanding; consult the latest experiment state.


## Patch0064 automated candidate and guarded return-control - 2026-10-30

Using the Chiaki-ng v0.3.0 MCP screen/controller bridge, resumed GTA IV
from PS5 Home (it was already paused in the map), unpaused and visually
confirmed the outdoor reference street near hydrant/lamppost. Captured
two distinct 45-second candidate gate1/helper_probes0 windows:

| Capture | FPS mean | 1% low mean | frame p50/p95/p99 ms | FPS windows | New SPU |
| --- | ---: | ---: | --- | ---: | ---: |
| mfc0064-candidate-run1 | 24.79 | 20.85 | 40.18 / 46.02 / 48.06 | 11 | 0 |
| mfc0064-candidate-run2 | 25.06 | 21.28 | 39.88 / 44.74 / 47.14 | 12 | 0 |

Both capture JSON files valid with no rejection reasons: latest profile
patch0064 gate1, helper_probes0, scheduler B, SPU Mega, XFloat Approximate,
resolution150, clocks100, frame limit60, Performance Report disabled,
and four runtime tuning flags all0. Both RSX sampling checks valid,
with sampled FIFO spin CPU share 16.14% and 13.24%; live SPU gateway
coverage valid, but **completed SPU interval timing not available** and
the live ages are not CPU-work duty-cycle estimates. Worker-activity
JSON saved beside captures; two-run summary stored in
results/gta4-mfc-meter-20261030/candidate-0064-combined.json.
Candidate mean FPS **24.925**, mean 1% low **21.065**. Original gate0
two-run FPS **23.42**; nominal gap +1.505 FPS, **not a credible patch
speedup estimate** because the candidate was observed under Chiaki
Remote Play and the earlier control was under different conditions.
Only return controls using matched Remote Play can help attribute a gain.

Returned to PS5 Games Home via PS hold, selected KB-RPCS3 Options >
Close Game (extended the bridge allowlist with the default Chiaki
Options/O mapping). Screenshot confirmed Home. Independent process
listing via 192.168.0.137:9021 completed with no eboot.bin or launcher.
Installer status confirmed candidate live and two matched gate0 backup
files; the guarded candidate rollback exited0 and preserved gate1
files as .mfc0064-candidate-stage. Post-rollback FTP status:
live ELF117434056 / mirror74605201, staged candidate
ELF117434056 / mirror74605329. Full independent downloaded control
ELF load/TLS comparison PASS and mirror exact SHA256
e48a5c75cc3357d7f51474d1ded457e4d27e221c15fde446023538d8f48eda7b
PASS. Earlier patch0062 backup untouched.

Navigated KB-RPCS3 game list through Chiaki, selected GTA IV NPUB30702,
and visually confirmed boot/Building SPU Cache. New boot loaded inside
Niko's apartment instead of the outdoor reference. Added bounded
Chiaki left-stick movement from default keyboard bindings (Insert,
Delete, bracket keys) with 60-1800ms limits and one-shot opt-in sessions;
16/16 bridge tests and packaged executable smoke PASS. Moved through
apartment door into stairwell, but scene/camera could not be matched.
No return-control FPS capture was attempted. Game remains running
inside building/stairwell on gate0 control. Live RPCS3 log preflight:
gate0/helper_probes0, scheduler RPCS3 Scheduler, Mega SPU, 150%
resolution, clocks100, XFloat Approximate, cap60, Performance Report
false, 0 new SPU compilation lines and no MFC mode errors.

**NEXT ACTION:** position Niko in same outdoor street at lamppost and
fire hydrant, camera stationary and warmed; retain Chiaki Remote Play
ON. Capture mfc0064-return-control-run1 and -run2, 45s each, using
tools/gta4-scheduler-ab.py capture with --mode B,
--expected-mfc-meter-gate 0, --expected-resolution 150 and all tuning
flags0. Reject SPU compilation or altered scene. Then compare A/B/A
with uncertainty about scene/time drift; no gain claimed yet. No
executable swap while title runs.


## Patch0064 A/B/A completed: no demonstrated gate1 FPS gain - 2026-10-31

User returned Niko to the same GTA IV NPUB30702 outdoor street, standing
near the lamppost and fire hydrant. Fresh live Chiaki screenshot verified
the location before measurement; camera/Niko facing and moving vehicles/
pedestrians were **not exactly identical** to the candidate phase.
Matched patch0064 **gate0 control** remained installed and running
(independently verified on boot: gate0, helper_probes0, scheduler B,
resolution150%, Mega SPU, XFloat Approximate, clocks100%, cap60,
Performance Report off, experiment tuning0). Took two distinct 45s
return-control runs without moving Niko.

| Variant / run | Mean FPS | Mean window 1% low FPS | Window p50 / p95 / p99 ms | Windows | New SPU |
| --- | ---: | ---: | --- | ---: | ---: |
| Original gate0 control 1 | 23.48 | 20.47 | 42.62 / 47.04 / 48.99 | 12 | 0 |
| Original gate0 control 2 | 23.36 | 20.18 | 42.88 / 47.16 / 49.72 | 11 | 0 |
| Gate1 candidate 1 | 24.79 | 20.85 | 40.18 / 46.02 / 48.06 | 11 | 0 |
| Gate1 candidate 2 | 25.06 | 21.28 | 39.88 / 44.74 / 47.14 | 12 | 0 |
| Return gate0 control 1 | **27.36** | 23.15 | 36.54 / 41.64 / 43.28 | 11 | 0 |
| Return gate0 control 2 | **27.72** | 23.78 | 36.21 / 40.82 / 42.14 | 11 | 0 |

All six scripted capture validators passed with no rejection reasons,
correct MFC compiled gate/probe markers and zero new SPU compilations.
Return gate0 means: **27.54 FPS**, 1% low **23.465 FPS**, p50 **36.375ms**,
p95 **41.23ms**, p99 **42.71ms**. Candidate gate1 means: **24.925 FPS**,
1% low **21.065 FPS**, p50 **40.03ms**, p95 **45.38ms**, p99 **47.60ms**.
Gate1 − return gate0 = **−2.615 FPS / −9.5%**. Candidate minus original
gate0 = +1.505 FPS, but this is not valid evidence of improvement.

Per-run `gta4-worker-activity.py` reports parsed successfully. RSX
FIFO spinning share of sampled FIFO CPU time: historical gate0
**20.31%, 19.63%**, gate1 **16.14%, 13.24%**, return gate0
**15.18%, 10.71%**; descriptive classifications only, not GPU command
counts or a causal throughput explanation. RSX measurement valid
for all six; live SPU gateway coverage valid. Completed SPU timing
is absent on some runs, so do not infer SPU idle/duty cycle.

**Critical limitations:** (1) original gate0 controls predated use of
Chiaki Remote Play in the test loop; candidate and return controls
used Chiaki ON; (2) after a safe reboot, user manually walked back
to the lamppost/hydrant street, with slightly different viewpoint
and differing traffic/pedestrian dynamics; (3) time-of-day, run order,
cache/warmup and reboot state can drift; (4) reported summaries average
individual FPS windows, not pooled raw-frame percentiles. A/B/A does
not establish causal significance from two samples per phase.

**Conclusion:** compiled `PS5_MFC_METER_GATE=1` has **no demonstrated
reproducible gain** in GTA IV with Performance Report disabled. Do
not promote candidate as an FPS optimization; nor claim a proven
−9.5% regression. Maintain verified gate0 control and focus next
research on measured RSX/SPU/rendering bottlenecks or improve the
scene-matching test protocol before reconsidering gate1.

**Console state:** gate0 control installed after process-checked
rollback with independent ELF load/TLS and mirror SHA256 verification;
gate1 retained as staged paired files; patch0062 backup untouched.
GTA IV remained running in the reference outdoor scene when the
return-control capture completed. No binary/config/save changes
during capture. Close and independently list running title/launcher
before *any* future executable swap.

Saved data: `results/gta4-mfc-meter-20261030/` with individual
`B-mfc0064-return-control-run{1,2}.json/.log`, `-worker-activity.json`,
`return-control-0064-combined.json` and `comparison-0064-aba.json`,
plus the earlier original-control/candidate combined files and builds.json.


## Patch0065 RSX method-word diagnostic on PS5, rolled back - 2026-10-31

Implemented port patch0065 after completed patch0064 gate experiment:
a **diagnostic-only** sparse probe in the actual RSX run_FIFO method
loop. It measures 1/512 method-bearing calls, counting loop iterations,
direct handlers and flattener-suppressed words, with a watchdog
aggregate; no guest state/command dispatch decisions changed.
Prior full source bytes archived and exact reverse/forward patch
replay PASS. Clang++19 native tests with probe OFF/ON PASS.
Full PS5 core+title build, native TLS, nine package gates, exact
RPCS3PS5TEXT 28-byte wrapper plus payload/PT_LOAD correspondence PASS.
The local diagnostic compile explicitly pinned MFC gate0/probes0.

Guarded installer staged and deployed the matched diagnostic pair
only after complete process-list checks found no GTA IV/launcher;
verified both stage files and installed ELF load/TLS/mirror SHA256.
Preserved original matched gate0 pair as
`.before-rsx0065-20261031`. Booted GTA IV via Chiaki, verified
runtime gate0/probes0, scheduler B, 150% resolution, Mega SPU,
Approximate XFloat, clocks100%, cap60 and all tuning flags0.
Game loaded in Niko apartment facing blue door; diagnostic workload
was **indoors**, not comparable with the outdoor FPS A/B/A.

| 45s indoor capture | Sampled method runs | Method-loop words | Direct handler calls | Words per run | Handlers per run | Max words |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| rsx0065-indoor-run1 | 158,280 | 330,241 | 217,542 | 2.0864 | 1.3744 | 288 |
| rsx0065-indoor-run2 | 146,945 | 305,823 | 200,942 | 2.0812 | 1.3675 | 288 |
| **Combined** | **305,225** | **636,064** | **418,484** | **2.08392** | **1.37107** | **288** |

Both capture JSON files valid with zero new SPU compilations; method
probe parser validated no contradictory counts. Zero flattened
suppression in this workload; about **65.79%** of sampled loop words
call a direct methods[reg] handler. Under stationary indoor
conditions FPS was capped near60; this is **not evidence of a
speedup**. Values are periodic samples not a complete or
unbiased histogram, GPU commands, exclusive CPU cost, or frame
critical-path time. An occasional 288-word run is real observed
sampled work but may not be representative of outdoor gameplay.

Closed game normally via PS5 KB-RPCS3 Options > Close Game.
Independent full process list found neither title nor launcher.
Guarded rollback restored matched gate0 control (ELF117434056 /
mirror74605201); diagnostic patch0065 preserved as
`.rsx0065-stage` (ELF117434176 / mirror74605521).
Original gate1 0064 stage remains present. Independent full
download confirmed gate0 ELF load/TLS and exact code-mirror
SHA256 `e48a5c75cc3357d7f51474d1ded457e4d27e221c15fde446023538d8f48eda7b`.
Original patch0062 backup retained, and saves/configs unchanged.
Title and launcher were independently confirmed **closed** after
rollback.

Data: `results/gta4-rsx-words-20261031/`, combined result
`rsx0065-indoor-combined.json` plus per-run FPS/log/counter JSONs.
Source, build hashes, deploy workflow, purpose and limitations in
`game research/GTA-IV-RSX-methodwords-20261031.md`.
**NEXT:** use these data to design a sparse method/register-class
distribution or exclusive RSX dispatch CPU cost measurement before
selecting a semantic-preserving optimisation. No FPS gain claimed.


## Patch0066 live method-register histogram completed; gate0 restored — 2026-10-31

Selected manifest patch count66 after diagnostic-only patch0065.
Sampled the same one-in-512 *method-bearing* run_FIFO calls,
attributing actually decoded register words and direct
methods[reg] calls into 256 buckets of 256-byte RSX offsets.
Watchdog emits `PS5 RSXCLASS2` full totals and top-12
`PS5 RSXCLASS` ranked buckets per roughly four-second window.
No guest method/RSX FIFO/state behavior modified. Native
Clang++19 probe-on/off tests and exact source reverse/forward
patch replay PASS. Full PS5 core/title build, native TLS template
128/memory15104/alignment32, nine package gates, 28-byte
RPCS3PS5TEXT wrapper and byte-identical full ELF executable
PT_LOAD mirror PASS. Diagnostic archive and hashes:
`/home/callum/work/rsx0066-registerclasses-20261031/`.

After complete PS5 process listing verified no title or
launcher, guarded pair staging/activation and independently
readback verified ELF/TLS/mirror. Saved original gate0 in
`.before-rsx0066-20261031`. Booted GTA IV through Chiaki.
Startup log MFC gate0/helper probes0; warmed game spawned
*inside Niko's apartment facing the blue exit door*, the same
indoor diagnostic location used in patch0065. No outdoors
FPS A/B attempted. Two 45s captures both valid with
zero new SPU compilations; indoor FPS at 60 cap.

| Register offset band | Run1 words/handlers | Run2 words/handlers | Combined words | Combined direct handlers |
| --- | --- | --- | ---: | ---: |
| 0x1800–0x18FF | 61,025 / 56,874 | 63,334 / 59,337 | **124,359** | **116,211** |
| 0x1700–0x17FF | 54,350 / 29 | 53,002 / 33 | **107,352** | **62** |
| 0x1600–0x16FF | 40,088 / 40,088 | 43,563 / 43,563 | **83,651** | **83,651** |
| 0x0300–0x03FF | 34,554 / 17,121 | 35,211 / 17,500 | **69,765** | **34,621** |
| 0x1A00–0x1AFF | 34,932 / 34,932 | 34,798 / 34,798 | **69,730** | **69,730** |
| 0x1F00–0x1FFF | 23,472 / 20,145 | 23,508 / 20,281 | **46,980** | **40,426** |

Full sampled 256-bucket totals across both runs:
**660,003 method words**, **435,865 direct handler calls**,
top12 coverage ~**98.77%**, 26 valid histogram watchdog reports.
`results/gta4-rsx-classes-20261031/rsx0066-indoor-combined.json`
includes every top band and full per-capture output.

Exact source `rpcs3/Emu/RSX/gcm_enums.h` examples:
0x1740 `NV4097_SET_VERTEX_DATA_ARRAY_FORMAT`, 0x1680
`NV4097_SET_VERTEX_DATA_ARRAY_OFFSET`, 0x1808
`NV4097_SET_BEGIN_END`, 0x1814 `NV4097_DRAW_ARRAYS`,
0x1824 `NV4097_DRAW_INDEX_ARRAY`, 0x1A00
`NV4097_SET_TEXTURE_OFFSET`, and 0x1F00
`NV4097_SET_TRANSFORM_CONSTANT`. These are names of registers
within a 256-byte range, **not exact frequencies**.
The 0x1700 bucket has 107,352 sampled words but only
62 direct handler calls; potentially state-latch/format updates,
not evidence of a high-CPU bottleneck. Investigate exact registers
and value-change rates before modifying decode/dispatch.

**Limitations:** periodic 1/512 sampling may alias with workload;
top12 lists omit less active bands, though totals include all
256 bins; class counters and RSXWORDS counters are independently
drained across watchdog boundaries; method packet count is not
exclusive handler CPU time or GPU utilization. This light
indoor scene hits a 60FPS cap. No proven performance win.

Closed title normally through Chiaki KB-RPCS3 > Options >
Close Game. Independent completed process list confirmed both
title and launcher absent. Guarded patch0066 rollback exited0.
Independent full downloaded prior patch0064 control ELF load/TLS
and mirror exact SHA256 verification PASS. Live sizes
ELF117434056/mirror74605201. Patch0066
stage ELF117438440/mirror74607761 retained; patch0065
and patch0064 candidate stages also preserved. No game saves,
config or caches changed. Both processes closed after test.

**Suggested next phase:** targeted exact-register/value-change
measurement on the 0x1700 range, or narrow sampled CPU timings
of 0x1800/0x1600/0x1A00 handler paths. Require fresh outdoor
matching and diagnostic-off controls before FPS claims.


## External PS5 RPCS3 forks screened for CPU speedups — 2026-10-31

Reviewed lavavex/rpcs3-PS5, its actual emulator submodule `lavavex/rpcs3:ps5`, and 10 identifiable public direct wrapper forks. Evidence and compatibility matrix in `game research/GTA-IV-lavavex-forks-CPU-audit-20261031.md`. No measured GTA IV FPS optimization to import. Lavavex core is older upstream (Oct6 vs KB Oct29); KB already uses `-march=znver2 -O3`, and upstream state decoding/PPU cache improvements are already present. Their PS5 CPU usage overlay patch might improve PPU attribution as *instrumentation*, after runtime validation. Their std::mutex self-notify patch is not applicable to KB's PS5 `USE_FUTEX` path; v0ltfault's FW7.40 JIT exec pool is opt-in and unrelated to known warm-frame bottleneck; jmelovich's /dev device-size fix is cross-game compatibility only. No PS5 or source changes made in this audit; current verified installed title remains patch0064 gate0, title/launcher previously closed. Prior patch0066 results and next exact-register/exclusive CPU-time investigation remain valid.


## Patch0067 PS5 CPU-time grouping: on-console results and safe return (2026-10-31)

Lavavex commit https://github.com/lavavex/rpcs3/commit/5e0e0e613d218e2450b8b3c8adab4576286ca92c adds PPU/SPU/RSX CPU time to its performance overlay via thread_ctrl::get_cycles(). On KB's tested PS5, pthread_getcpuclockid(target) returns the calling thread's clock, so directly backporting it would risk bogus data. The current KB Utilities/Thread.cpp has a signal-based monitor: send SIGUSR1 to every registered RPCS3 worker, and each worker reports its own CLOCK_THREAD_CPUTIME_ID nanoseconds. Patch0067 reuses SAME snapshots (no extra signals) and aggregates ALL worker deltas into PPU, SPU, exact main rsx::thread, OTHER. Other includes SPU JIT compilation worker pool, graphics helpers and miscellaneous RPCS3 host threads, so avoid assuming that OTHER is idle CPU or that main-RSX is complete graphics-driver time. Percent is of one logical host hardware thread, not a physical core or game frame.

Source patch: port/rpcs3-latest-patches/0067-PS5-report-exact-PPU-SPU-RSX-main-host-CPU-time.patch. Source original /home/callum/work/ps5cpu0067-original-20261031. Reversible patch replay PASS; GCC and Clang++19 C++20 tests PASS (port/tests/check-ps5-cpu-groups.py); synthetic legacy/exact parser tests PASS (port/tests/check-ps5-cpugroups-parser.py). Full PS5 build, TLS 128/15104/alignment32, ELF vs code-mirror full byte equality, all nine package checks PASS. Archived pair/hashes at /home/callum/work/ps5cpu0067-groups-20261031. Guarded stage/readback/activate verified no title or launcher processes, retained prior full gate0 pair, matched ELF load and TLS, code mirror SHA256. Loaded GTA IV normally via Chiaki and warmed SPU compilation before captures.

| GTA IV apartment measurement (logical-core equivalents) | Run1 | Run2 | Mean |
| --- | ---: | ---: | ---: |
| PPU | 1.577 | 1.552 | **1.565** |
| SPU | 3.883 | 3.827 | **3.855** |
| Main RSX | 0.557 | 0.550 | **0.554** |
| Other RPCS3 host threads | 0.083 | 0.082 | **0.083** |
| All registered host threads | 6.093 | 6.005 | **6.049** |
| FPS (60 cap) | 59.94 | 59.96 | **59.95** |

Each capture had 45s, 11 FPS windows and 12 valid exact CPU time reports; both had zero new SPU compilations. Captures/logs and per-run parsed JSON are in results/gta4-ps5cpu-20261031/; combined result is ps5cpu0067-indoor-combined.json. The 60 cap prevents FPS inference. CPU time over parallel workers cannot distinguish which wait or worker gated frame delivery. Out-of-registry driver/kernel tasks are excluded.

**Previously captured historical GTA IV CPU lower bounds (top14-only reports):** initial outdoor control ~23.42 FPS and total ~8.94 logical cores, printed PPU ~2.35/SPU ~5.52/main RSX ~0.89; return outdoor gate0 control ~27.54 FPS, total ~8.77, top14 PPU ~2.22/SPU ~5.45/main RSX ~0.92. Historical JSON: results/gta4-rsx-classes-20261031/ps5cpu0067-historical-top14-estimates.json. These older group values omit smaller workers and have integer rounding; differing outdoor scenes/Remote Play/boot state confound FPS attribution. The SPU group being busier is NOT itself evidence it controls the FPS.

**Rollback:** Chiaki Games Home, selected KB-RPCS3, Options, Close Game. Complete independent process list verified title/launcher stopped, guarded rollback exit0. Independent download confirmed restored original ELF PT_LOAD and PT_TLS and exact original mirror SHA256; the title files now have original gate0 sizes (ELF 117434056 bytes; mirror 74605201 bytes). Both diagnostic stage files remain (0067 ELF 117438656 bytes; mirror 74608465 bytes). Final process list after rollback again confirms both processes closed. No user game data or config changed.

**Next:** measure exact CPU groups in *uncapped, matched outdoor gameplay* with stable controls, and pair with PPU/SPU/RSX wait or per-frame critical-path evidence before making any performance optimization.


## Patch0067 matched-area outdoor CPU experiment, completed 2026-10-31

User positioned GTA IV Niko beside the hydrant/lamppost outdoors. Two 45s gate0 controls were captured in that exact user-set viewpoint; both passed 11 FPS reporting windows, gate0/helper probes0 and zero new SPU compilations. The PS5 title and launcher were stopped via Chiaki Home > KB-RPCS3 Options > Close Game, independently process-checked, and the staged patch0067 paired executable/mirror activated with guarded full SHA256 and ELF/TLS readback. The game rebooted into the apartment, and bounded Chiaki movement returned Niko to the same block; new viewpoint, precise Niko position, daylight and traffic were different. Both 45s patch0067 outdoor diagnostic runs passed, with 12 exact all-registered-thread CPU reports each and zero new SPU compiles.

| Phase | Run 1 FPS | Run 2 FPS | Mean FPS | PPU host cores | SPU host cores | Main RSX host cores |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Original gate0 control, top14 group LOWER BOUNDS | 26.77 | 29.35 | **28.06** | 2.2815 | 5.5300 | 0.9425 |
| Patch0067 exact all-worker groups | 28.20 | 29.32 | **28.76** | 2.2925 | 5.4435 | 0.9215 |

Original gate0 total CPU ~8.937 logical host cores; patch0067 total ~8.737, OTHER ~0.0845. Control group sums omit registered workers outside top 14, but its overall total includes all registered workers. Patch0067 exact group counts include all registered workers, not kernel/driver threads outside the registry. Six guest SPU threads consume ~5.44 cores total and the main RSX worker ~0.92 of one logical host core. Summed CPU time does NOT say which thread waits on another or gates the next frame. Neither phase was FPS capped in the outdoor street. The control samples themselves differed by 2.58FPS. Nominal +0.70FPS diagnostic phase difference is NOT an optimization result: changed camera/position/traffic/lighting, load/boot conditions and sampling order make it noncausal.

After capture, game closed normally via Chiaki; independent full PS5 process list confirmed no title or launcher. Guarded patch0067 rollback exit0; independently downloaded restored exact gate0 executable ELF load/TLS and code mirror exact SHA256 verification PASS. Patch0067 remains staged; old gate1 and diagnostic stages remain intact; no game data/config/cache changes.

Data: results/gta4-ps5cpu-20261031/ps5cpu0067-outdoor-control-vs-diagnostic-20261031.json, four individual FPS/log files, ps5cpu0067-outdoor-control-groups.json and ps5cpu0067-outdoor-run1-groups.json / ps5cpu0067-outdoor-run2-groups.json. Next capture PPU/SPU/RSX per-frame dependency and waits in a same-angle outdoor test before any source-code optimization.


## Patch0068 SPU reservation-wait timings, completed 2026-10-31

Two stationary outdoor GTA IV 45s diagnostic captures passed, zero new SPU compiles, mean27.36FPS. Patch0068 exact invocation counts during the complete watchdog intervals: 453056 reservation callbacks (~4885/s), 342418 atomic waits (~3692/s), 115436 nested notify_all calls (~1245/s). Timed 1/128 samples separate CLOCK_MONOTONIC and CLOCK_THREAD_CPUTIME_ID: callback 3.141us wall/1.431us worker CPU; atomic wait 114.410us wall/9.627us worker CPU; notification 3.013us wall/1.397us worker CPU. Nested metrics cannot be summed as exclusive costs; samples include clock overhead and phase bias. Waiting time is predominantly non-running time, **not proof it limits FPS**. Native TLS lookup is already cheap. See GTA-IV-SPU-reservation-wait-timing-20261031.md. Guarded diagnostic rollback and independently verified original patch0064 gate0 ELF PT_LOAD/TLS + exact mirror SHA256 PASS, both processes CLOSED; 0068 retained in .spuwait0068-stage, no user configs or saves changed. Source patch count68 is NOT installed.


## Patch0069: sampled SPU reservation page and notification origin (2026-10-31)

After completed patch0068 elapsed-vs-CPU wait measurement, patch0069 measured which 4KiB guest page receives sampled SPU waits and which guest thread class initiates successful notification transitions. Two valid 45s stationary **outdoor** captures, FPS28.77 / 26.78, zero new SPU compiles. 1/128 per-host-worker/path samples: 2449 wait returns, 2279 successful notifier transitions; 0 table overflow. 2429 SPU wait samples (**99.18%**) on guest page **0x017F7000**; changed notifier flag2421, cleared reservation8; 256 PPU-origin and 1689 SPU-origin successful notify samples on same page. Other 20 wait samples on 0x017F8000. Note global notifier samples also include pages not in top8 wait list. Notification caller is not necessarily guest data writer or actual wake cause. Per-4s window wait count correlated positively with FPS (+0.663), but per-estimated-frame-normalized counts only weakly (+0.115). **No FPS speedup or actual frame-gating dependency is proven.** Next identify exact 128B line and guest data writer/callsites. Original patch0064 gate0 installed and independently ELF/TLS + mirror hash verified after guard rollback; game and launcher CLOSED; patch0069 safely staged. See GTA-IV-SPU-reservation-page-attribution-20261031.md.
