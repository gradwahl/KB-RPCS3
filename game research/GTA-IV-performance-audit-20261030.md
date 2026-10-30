# GTA IV NPUB30702 — PS5 RPCS3 critical-path performance audit
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
