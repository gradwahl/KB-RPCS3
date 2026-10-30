# GTA IV — NPUB30702

## Verified console evidence — October 30, 2026

Console FTP: `192.168.0.137:2121`. Latest-upstream PS5 port; installed code mirror
matches the local latest build by SHA-256:
`c17a3496aff4b890565d6efd2e218b31eb9129d3ed34242eaab81a441cdd6fe7`.

The pre-test RPCS3.log records:

- SPU and PPU LLVM recompilers; SPU Block Size **Mega**; XFloat **Approximate**.
- Clock scale **100%**, frame limit **60**, vblank **60 Hz**.
- OS thread scheduler; Multithreaded RSX **false**; resolution scale **150%**.
- On-disk shader cache disabled. Experimental SPU tuning flags disabled.
- Applied `Unlock FPS` by Zolika1351, PPU hash
  `d5041972c3464b734ed27f0b94b505a2a14471c8`, one instruction.
- Applied `ARMSX3 Approximate collision fix` by jpolo1224, SPU hash
  `d0a1508208613e2184fbd64906d34d5f07890033`, 14 instructions.
- Last eight reporting windows: **21.1–23.5 FPS**, window 1% lows
  **17.3–19.6 FPS**. Guest/host ratio **1.000**, vblank **59.9–60.0/s**.
  These are historical observations, not a controlled scheduler comparison.
- Several SPU threads at 93–99% CPU; GTA RenderThread and RSX also busy.
- The saved per-game config was **Safe**, despite Mega in the captured run.

## Profiling interpretation

The profiler calls addresses outside the fixed title image "system code" and
tags a stack-derived title address `sys@`. SPU JIT code is also outside that
image. **Do not interpret every `sys@` sample as a syscall or wasted waiting.**
With the matching linked ELF and the documented `0x400000` load-base subtraction:

| Reported address | Resolved function |
| --- | --- |
| `bb7378` | `spu_thread::cpu_task()`; disassembly shows return from indirect execution call |
| `bc685b` | `spu_thread::get_ch_value()` |
| `bc322d`, `bc371e` | `spu_thread::process_mfc_cmd()` |
| `bbe43d`, `bbd6ff` | `spu_thread::do_dma_transfer()` |
| `870c53` | `atomic_wait_engine::wait()` |
| `1204e3c` | `vm::writer_lock::writer_lock()` |

These identify investigation targets; they do not establish recoverable frame
time or prove a particular fix. PS5 affinity code is bypassed in OS scheduler
mode. Its shared SPU mask does not guarantee individual SPU threads each own a
physical core. The hardcoded SMT topology still needs hardware validation.
RADV wait counters have weak zero-valued fallback storage; zeros do not prove
the absence of GPU waits.

## Scheduler A/B — completed (October 30, 2026)

Tool: `tools/gta4-scheduler-ab.py` (Python standard library).
Session: `results/gta4-scheduler-20261030/` (ignored by Git).
The original config, prior log, patch file and patch enablement config are saved.

- **A:** OS scheduler + Mega.
- **B:** RPCS3 Scheduler + Mega.
- A/B files differ only in `Thread Scheduler Mode`. Both preserve XFloat,
  patches, clock scale, 60 FPS limit, resolution and all other original settings.
- **A runs 1–2 and B runs 1–2 measured** with matching runtime settings, both
  patches applied, normal-speed timing, and no SPU compilations. Four valid
  45-second captures, nine windows each. Config B was uploaded to the console
  and verified after the A2 confirmation; takes effect on the *next* game launch.
  The currently running game remains on A until relaunched.

### Test A, run 1 — measured October 30, 2026

User positioned the game in an outdoor scene. A 45-second capture produced nine
new reporting windows and passed runtime config, applied patch and timing checks.
No new SPU blocks compiled during the window.

| Metric | OS scheduler + Mega |
| --- | --- |
| Mean reported FPS | 23.00 |
| Minimum reported window FPS | 21.8 |
| Mean window p50 frame time | 43.52 ms |
| Mean window p95 frame time | 47.33 ms |
| Mean window p99 frame time | 49.54 ms |
| Mean window 1% low | 20.22 FPS |

Raw capture: `results/gta4-scheduler-20261030/A-run1.log` and `.json`.
SPU SecondaryCellSpursKernel0 remained at 99%; primary SPU kernels 2 and 3
mostly 97–98%; RSX 85–89%; GTA RenderThread 84–87%. These are CPU usage
observations, not a breakdown of recoverable frame time.

### Test B, runs 1–2 — measured October 30, 2026

Two 45-second captures under RPCS3 Scheduler + Mega, nine new reporting windows
per run, passed runtime config/patch/normal-speed checks. No new SPU block
compilations in either run.

| Metric | A run 1: OS | B run 1: RPCS3 | B run 2: RPCS3 |
| --- | ---: | ---: | ---: |
| Average window FPS | 23.00 | 24.01 | 23.93 |
| Average window 1% low FPS | 20.22 | 20.17 | 20.51 |
| Mean window p50 frame time | 43.52 ms | 41.59 ms | 41.86 ms |
| Mean window p95 frame time | 47.33 ms | 46.72 ms | 46.30 ms |
| Mean window p99 frame time | 49.54 ms | 49.60 ms | 48.87 ms |
| Minimum reporting-window FPS | 21.8 | 22.8 | 23.1 |
| New SPU compilations | 0 | 0 | 0 |

B average across its two runs: **23.97 FPS**, **20.34 FPS** mean window 1% low.
After the confirmation A2 run, A averages **23.065 FPS**, **20.04 FPS** mean
window 1% low. B shows **+0.905 FPS / +3.9% average FPS**, with only +0.30 FPS
(+1.5%) in 1% low. Two runs per mode in one outdoor scene are promising but
insufficient to establish universal gains, stability, or driving performance.
The B RSX thread reported ~89–91% CPU, with multiple SPU threads ~95–99%; this
is CPU utilization only, not proven bottleneck attribution.
Raw captures: `results/gta4-scheduler-20261030/B-run1.{log,json}` and
`B-run2.{log,json}`.

### Test A, run 2 — confirmation October 30, 2026

The A2 capture passed runtime config, applied patches, normal-speed timing and
window-count checks. Nine reporting windows and zero new SPU compilations.

| Metric | OS scheduler + Mega, A2 |
| --- | ---: |
| Average window FPS | 23.13 |
| Mean window 1% low FPS | 19.86 |
| Mean window p50 | 43.29 ms |
| Mean window p95 | 48.54 ms |
| Mean window p99 | 50.72 ms |
| Minimum reporting-window FPS | 20.4 |

Raw capture: `results/gta4-scheduler-20261030/A-run2.{log,json}`.

### Final scheduler comparison (two captures per mode)

| Metric | OS scheduler A | RPCS3 scheduler B |
| --- | ---: | ---: |
| Average FPS | 23.065 | 23.970 |
| Average window 1% low | 20.040 | 20.340 |
| Average window p95 | 47.935 ms | 46.510 ms |
| Average window p99 | 50.130 ms | 49.235 ms |

**Decision:** retain B for subsequent tests, with its +3.9% average FPS in
this reproducible scene. The 1% lows have not materially improved. B has been
uploaded and FTP read-back verified; the running title uses A until relaunched.
This scheduler comparison is not evidence that a stable 60 FPS is possible.

Close/relaunch the game after changing scheduler. Use the same save, stationary
outdoor position and camera for both runs; allow compilation to settle. Capture
45 seconds with the game already positioned. Repeat A/B if traffic/weather or
compilation makes a result ambiguous. Do not run the older BLES01128 benchmark
scripts: they target a different serial/config and can overwrite this experiment.

```powershell
# B is installed on the console for the NEXT launch. Restart GTA IV to use it.
# A1, B1, B2, and A2 captures are complete.
# To repeat later, use a fresh capture label and the appropriate mode.
python tools/gta4-scheduler-ab.py capture --session results/gta4-scheduler-20261030 --mode B --label run3

# Exact restoration of the original per-game config, including Safe block size:
python tools/gta4-scheduler-ab.py restore --session results/gta4-scheduler-20261030
```

Captures retain full logs and report only newly appended windows. Runtime config,
patch application, timing and minimum window count are checked. Replaced logs
invalidate the capture. Percentiles and 1% lows are means of RPCS3 reporting-window
statistics, not pooled frame statistics. New SPU compilation counts are included.
Restore refuses to overwrite a config changed outside this experiment.

## Next steps

Scheduler B is provisionally preferred (+3.9% average FPS in two stationary
outdoor captures per mode). Verify this improvement in moving/driving gameplay,
then improve profile attribution and investigate SPU channel/DMA/reservation paths.
Stable 60 FPS remains an unverified target requiring about 2.6–2.9x the throughput
of the last recorded windows. No code-level performance gain is claimed.

## Live follow-up — October 30, 2026, 150% resolution

After relaunching with scheduler B + Mega + Approximate XFloat + 100% clocks
and the existing GTA IV patches, the user stood in the same outdoor scene.
The 45-second **B-run3** capture was valid: 9 FPS/timing windows, no new
SPU compilations, runtime scheduler B. Summary:

| Metric | B run 3 (150% resolution) |
| --- | ---: |
| Mean reported FPS | **25.29** |
| Mean window 1% low | **21.73 FPS** |
| Mean window p50 frame time | 39.47 ms |
| Mean window p95 frame time | 43.48 ms |
| Mean window p99 frame time | 46.25 ms |
| Minimum window FPS | 23.1 |

Raw: `results/gta4-scheduler-20261030/B-run3.{log,json}`. Higher FPS
than B1/B2 does **not** prove a new performance gain: identical settings
were retained; time-of-day/traffic/weather and positioning may differ.

### Profile samples from this capture

From the 45 seconds ending at title log timestamp ~198.85 s:

- Secondary SPU kernel: 90/400 sampled instruction pointers attributed to named
  guest SPU JIT functions; repeated `spu_thread::cpu_task()`, SPU channel/DMA.
- Primary SPU kernel 2: 183/400 JIT-named; `spu_thread::cpu_task()`,
  `process_mfc_cmd()`, `get_ch_value()`, `vm::writer_lock` and
  `atomic_wait_engine::wait` also sampled.
- Primary SPU kernel 3: 128/400 JIT-named; similar SPU MFC and reservation paths.
- RSX samples resolve against matching locally linked ELF (profile address
  minus 0x400000): `0x1392670` is
  `rsx::draw_command_processor::write_vertex_data_to_memory()`;
  `0x1378e8d` is `write_index_array_data_to_buffer()`;
  `0x4ee80b` and `0x4ee7e7` are the custom `tsc_now` fastclock;
  `0x1364684` is `rsx::thread::run_FIFO()`. These samples implicate
  draw-data preparation and polling but cannot determine the critical path
  or quantify potential gains.
- `PS5 WAITS` counters are all zero; pinned RADV supplies weak zero-value
  fallbacks, so do **not** interpret this as proof of no GPU waits.
- `sys@` does **not** necessarily indicate a syscall: the profiler can tag
  guest SPU JIT as system code.

### Next controlled diagnostic: 150% versus 100% resolution

**Purpose:** isolate GPU resolution pressure before touching timing-sensitive
SPU or RSX core code. Preserve scheduler B, Mega, Approximate XFloat, 100%
clock scale, 60-FPS patch, and all other settings. Lower only the active
`Resolution Scale` from 150 to 100. It is a *diagnostic*, not a permanent
image-quality recommendation.

The script `tools/gta4-resolution-test.py` saved exact `150.yml` and
`100.yml` variants in `results/gta4-resolution-20261030/`.
`apply100` was uploaded to the console and verified byte-for-byte by FTP;
**it takes effect on the next GTA IV launch**. Until then the current game
session remains at 150%.

After the user relaunches and parks in the same warmed outdoor scene:

```powershell
python tools/gta4-scheduler-ab.py capture --session results/gta4-scheduler-20261030 --mode B --label res100-run1 --expected-resolution 100
```

Capture validation must confirm `Resolution Scale: 100` in runtime log,
plus all previous timing, patches, scheduler and compilation checks. Compare
against B-run3 and B1/B2, repeat if noisy. Regardless of result, the original
150% resolution with scheduler B can be restored via:

```powershell
python tools/gta4-resolution-test.py restore150
```

This restoration also takes effect on next GTA IV launch. Do not overwrite
any out-of-experiment edits; the script refuses unknown configs.

## Resolution-scale A/B outcome — October 30, 2026

The user relaunched in the same outdoor spot with **Resolution Scale 100%**,
still using scheduler B (RPCS3 Scheduler), MEGA, Approximate XFloat, 100%
clocks, 60 FPS frame limit and the two applied GTA IV patches.

45-second capture: `results/gta4-scheduler-20261030/B-res100-run1.{log,json}`.
The test passed: 9 FPS/timing windows, zero new SPU compilations, runtime
configuration matches 100% resolution, patches applied and timing checks
satisfied.

| Metric | B run 3 @ 150% | B res100 run 1 @ 100% |
| --- | ---: | ---: |
| Average FPS | 25.29 | 24.77 |
| Mean window 1% low FPS | 21.73 | 21.07 |
| Mean window p50 frame time | 39.47 ms | 40.25 ms |
| Mean window p95 frame time | 43.48 ms | 45.04 ms |
| Mean window p99 frame time | 46.25 ms | 47.65 ms |
| Minimum window FPS | 23.1 | 23.3 |
| New SPU compilations | 0 | 0 |

**Interpretation:** lowering resolution produced **no measured FPS improvement**
in this controlled comparison (−0.52 FPS; −2.1% compared to B run 3).
The small reverse difference can be natural scene/run variance, and a
single 100% capture cannot prove that the GPU is never the bottleneck.
Several SPU threads were still ~95–99% active and RSX ~89–92% CPU,
supporting further profiling of CPU-side work (SPU execution/channel/DMA/
reservation, RSX vertex/index preparation). High CPU usage alone cannot
prove which path sets the frame time.

**Restoration:** `python tools/gta4-resolution-test.py restore150`
succeeded; the saved 150%-resolution scheduler-B config was FTP uploaded
and verified byte-for-byte. It takes effect **on the next game launch**.
The current game session remains at 100% resolution until then.
All other settings retained.

**Next investigation:** priorise a low-risk, targeted CPU-side profile of
SPU MFC/channel/reservation handling versus RSX vertex/index data staging.
Only implement an isolated code optimisation with the ability to rollback
and measure before/after on the same game scene. Consider moving/driving
scene validation before claiming a gameplay-wide improvement.
Stable 60 FPS remains unverified.

## Patch 0054 — RSX copy fast path prepared (not deployed, October 30, 2026)

A code-level PS5-only candidate was added in the local latest-upstream
checkout `~/work/rpcs3-latest/rpcs3/Emu/RSX/RSXOffload.cpp` and persisted as:
`port/rpcs3-latest-patches/0054-PS5-skip-non-strict-RSX-copy-reservation-setup.patch`.

Rationale: in the synchronous `rsx::dma_manager::copy(void*,void*,u32)`
used by vertex-data staging, the old path always called
`vm::try_get_addr(src)` and constructed
`rsx::reservation_lock<true,1>`, even when
`Strict Rendering Mode: false`. In this mode, the existing three-argument
lock constructor never takes a lock. The new PS5-only non-strict branch
directly performs `memcpy`. The matching offload `raw_copy` path also
skips that no-op setup. Strict rendering and desktop paths are unchanged.

**Validated locally:** targeted PS5 core C++ object compiled; the full
PS5 core, native TLS and signed-title build succeeded, with all nine
package checks passing. Compiled real-code tests
`port/tests/check-ps5-rsx-copy.py` passed for PS5 and desktop,
covering synchronous/offloaded, strict/non-strict copies and null source.
Existing RSX wait and renderer identity host tests passed, and patch 0054
passed forward application against the clean Git index and reverse
application against the modified source.

**Matching staged (not installed) candidate outputs:**
`~/work/ps5-rpcs3-app-latest/dist/PPSA99303/eboot.bin`
SHA-256 `ff19977e5eb84421487ab5101e0353dc176412ec1e4e8dae45d104500d343957`,
114,101,214 bytes.
`~/work/ps5-rpcs3-app-latest/dist/PPSA99303/rpcs3ps5-text.bin`
SHA-256 `90dd397340fc2c0f67cbc8247068ec46e92b9c4b75f38ed363177fbec23fba10`,
74,601,297 bytes.

**Current console:** deliberately unchanged; do not replace the eboot
or code mirror while KB-RPCS3 is running. Saved NPUB30702 config is
scheduler B + Mega + Approximate XFloat + 150% resolution (restored by
FTP earlier); it takes effect on next launch. Original 150% run B3:
25.29 FPS average, 21.73 FPS mean window 1% low; earlier B1/B2:
24.01 and 23.93 FPS. These are reference observations, not performance
results for patch 0054.

**Next controlled test once the game is fully closed:** preserve the
existing working executable and mirror together for rollback, install
the matching staged pair, relaunch to verify patched title startup,
then capture stationary outdoor A/B at 150% resolution, normal speed,
and the identical save/camera, followed by moving/driving validation.
Record applied patches, 1% lows, p95/p99 and SPU/RSX thread usage.
Roll back both files if a regression appears or gains are lost to noise.
This small fast path is unlikely by itself to supply the roughly 2.4x
throughput needed for 60 FPS; there is currently **no measured gain**.

## Patch 0054 deployment — October 30, 2026

After the user confirmed the game was closed, the PS5 process-list payload
verified that neither `eboot.bin` nor the RPCS3 launcher was running.
`tools/deploy-gta4-rsx0054.py` staged and installed the *matching* new
build pair over FTP at `192.168.0.137:2121`. The process saved previous
installed files by FTP rename **without overwriting them**:

- `/data/homebrew/PPSA99303/eboot.bin.before-rsx0054-20261030`
- `/data/homebrew/PPSA99303/rpcs3ps5-text.bin.before-rsx0054-20261030`

The new files occupy the normal `eboot.bin` and `rpcs3ps5-text.bin`
paths. Before activation, the staged executable's FTP-decrypted ELF
`PT_LOAD`/`PT_TLS` payloads and entry point matched the converted,
linked build; after activation the same segment comparison passed.
The new mirror's full FTP readback SHA-256 matches
`90dd397340fc2c0f67cbc8247068ec46e92b9c4b75f38ed363177fbec23fba10`.
The new signed executable's build SHA-256 is
`ff19977e5eb84421487ab5101e0353dc176412ec1e4e8dae45d104500d343957`
(the FTP server exposes it as a decrypted ELF, not byte-identical SELF).
The retained old mirror is 74,601,553 bytes versus 74,601,297 new bytes.
The deployed pair was rechecked independently after activation.

Console config was fetched independently after deployment and still states:
RPCS3 Scheduler, SPU Block Size Mega, XFloat Approximate,
Resolution Scale 150%, Clocks scale 100%, Frame limit 60,
Strict Rendering Mode false. GTA IV game files, saves, existing patches,
and other title assets were **not changed**.

**Awaiting user launch and capture:** this is a successful *file deployment*,
not yet a proof of launch or measured gain. After GTA IV is relaunched,
capture a warmed 45-second stationary baseline under the new patched
executable and compare against the valid pre-patch 150% B runs (23.93,
24.01, 25.29 FPS). Inspect runtime settings and applied patches,
speed/vblank, SPU compilations, p95/p99 and 1% low. Also test moving/
driving scenes and watch for stability issues.

**Rollback:** close the game, verify no `eboot.bin` process, then run
`python3 tools/deploy-gta4-rsx0054.py rollback` from WSL, restoring the
old executable and mirror together by FTP renames. The script refuses
overwriting occupied stage names. Keep the backups until the new build is
proven stable; do not mistake the staged test for a 60 FPS result.

## Patch 0054 live validation — October 30, 2026

After installing the matching RSX-copy fast-path executable/mirror pair and
relaunching GTA IV NPUB30702, the user returned to the stationary outdoor
scene. Two fresh 45-second captures were made:

- `results/gta4-scheduler-20261030/B-rsx0054-run1.{log,json}`
- `results/gta4-scheduler-20261030/B-rsx0054-run2.{log,json}`

Both reported `valid: true`; runtime **RPCS3 Scheduler**, SPU Block
Size **Mega**, Approximate XFloat, **150%** resolution, 100% clocks,
frame limit 60, both applied patches, valid normal-speed guest/host
timing and **zero new SPU compilations**. Run 1 included nine reporting
windows; run 2 included ten. These numbers are means of *window summaries*,
not pooled frame percentiles.

| Metric | Pre-patch B1 | Pre-patch B2 | Pre-patch B3 | Patch 0054 run 1 | Patch 0054 run 2 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Mean FPS | 24.01 | 23.93 | 25.29 | **26.38** | **26.46** |
| Mean window 1% low FPS | 20.17 | 20.51 | 21.73 | 22.44 | 22.96 |
| Mean window p50 frame time ms | 41.59 | 41.86 | 39.47 | 37.82 | 37.86 |
| Mean window p95 frame time ms | 46.72 | 46.30 | 43.48 | 42.33 | 41.92 |
| Mean window p99 frame time ms | 49.60 | 48.87 | 46.25 | 44.66 | 43.65 |
| Minimum reported window FPS | 22.8 | 23.1 | 23.1 | 24.7 | 25.0 |
| New SPU compilations | 0 | 0 | 0 | 0 | 0 |

Patch 0054 two-run mean: **26.42 FPS**, **22.70 FPS** mean window
1% low, **42.125 ms** mean window p95, **44.155 ms** mean window p99.
Pre-patch B3 (the last and strongest pre-patch 150% baseline) had
25.29 FPS and 21.73 FPS 1% low. Relative to B3, patched average FPS
was +1.13 (+4.47%), 1% low +0.97 FPS; p95 was ~1.36 ms lower.
Across all three pre-patch B runs average FPS was 24.41, but the
larger difference to this historical mean is more susceptible to
run order/scene variance.

Thread CPU activity did not show an obvious fall in RSX utilisation:
B3 RSX mean ~93.4%, patched runs ~93.4% and ~93.1%.
Secondary SPU kernel 0 remained ~98%, Primary SPU kernels 2 and 3
~96–97%; these measurements do not attribute a particular amount
of frame time to the changed path.

**Conclusion:** two repeat patched captures are consistently better
than each pre-patch 150% run, with improved frame-time tails.
This is encouraging **correlation**, but a paired rollback-to-old
executable test in the same scene is still required before claiming
a causal 4.5% speedup from the RSX-copy code.

**Next:** in addition to moving/driving stability validation, an
A/B/A comparison can be done by closing the game, running the
documented `tools/deploy-gta4-rsx0054.py rollback` (both files),
relaunching in the same scene and capturing a 45-second pre-patch
confirmation. Then close again, reinstall the matching new pair and
capture one more patched confirmation. Preserve the backups and
never replace the running executable. No stable 60 FPS claim.

## Patch 0054 controlled rollback — October 30, 2026

The user confirmed KB-RPCS3/GTA IV closed for rollback.
`tools/deploy-gta4-rsx0054.py rollback` queried the console process
listing and confirmed no `eboot.bin` or `rpcs3ps5-launch.elf`
before changing executable files. The tool restored the **original,
pre-0054 signed executable and matching code mirror together** using
FTP renames; no GTA IV save, game data, patches or configuration
was touched.

A fresh FTP status query after rollback verified:

| Remote path suffix | FTP reported size | Meaning |
| --- | ---: | --- |
| `eboot.bin` | 117,425,144 | restored original pre-0054 executable, decrypted by FTP |
| `rpcs3ps5-text.bin` | 74,601,553 | restored original pre-0054 code mirror |
| `eboot.bin.rsx0054-stage` | 117,425,144 | patched executable retained for reactivation |
| `rpcs3ps5-text.bin.rsx0054-stage` | 74,601,297 | patched code mirror retained for reactivation |

The `.before-rsx0054-20261030` backup names are now absent because their
contents were restored to the active filenames; the patched files were
moved into the `.rsx0054-stage` filenames rather than deleted.

The custom NPUB30702 YAML was fetched after rollback and still contains:
RPCS3 Scheduler, SPU Block Size Mega, SPU XFloat Accuracy Approximate,
Resolution Scale 150, Clocks scale 100, Frame limit 60 and
Strict Rendering Mode false.

**Current test status: original unpatched version provisioned;
awaiting user relaunch and same-camera outdoor 45-second baseline.**
Use a distinct capture label such as:

```powershell
python tools/gta4-scheduler-ab.py capture --session results/gta4-scheduler-20261030 --mode B --label rollback-control1 --expected-resolution 150
```

Compare with patched captures `B-rsx0054-run1` (26.38 FPS) and
`B-rsx0054-run2` (26.46 FPS), both valid at 150% resolution.
The previous unpatched 150% runs were 24.01, 23.93 and 25.29 FPS.
Do **not** attribute the difference to patch 0054 until this current
rollback control is captured.

For reactivation **only after closing the game again**, execute from WSL:

```bash
python3 /mnt/c/Users/Callum/Documents/GitHub/KB-RPCS3/tools/deploy-gta4-rsx0054.py activate
```

The deploy script checks process state and verifies both staged files,
moves the original active pair into paired backup names and installs the
new patched pair. It must not be run over a running title.

## Patch 0054 rollback controls — October 30, 2026 (updated conclusion)

After restoring the **original pre-patch executable and matching code
mirror**, the user relaunched GTA IV at the same stationary outdoor scene
and camera. Two independent 45-second capture windows were collected
with mode B and explicit 150% resolution verification:

- `results/gta4-scheduler-20261030/B-rollback-control1.{log,json}`
  (10 reporting windows)
- `results/gta4-scheduler-20261030/B-rollback-control2.{log,json}`
  (9 reporting windows)

Both were marked **valid**, verified normal clocks/patches/settings,
and reported **zero new SPU compilations**.

| Metric | Unpatched rollback 1 | Unpatched rollback 2 | Unpatched mean | Patched 0054 mean (2 runs) |
| --- | ---: | ---: | ---: | ---: |
| Average FPS | 24.60 | 28.08 | **26.34** | **26.42** |
| Mean reporting-window 1% low FPS | 21.26 | 24.50 | **22.88** | **22.70** |
| Mean reporting-window p50 ms | 40.68 | 35.60 | **38.14** | **37.84** |
| Mean reporting-window p95 ms | 44.89 | 39.25 | **42.07** | **42.13** |
| Mean reporting-window p99 ms | 47.26 | 40.89 | **44.08** | **44.16** |

**Corrected conclusion: patch 0054 does NOT show an established FPS
gain.** Comparing only the first rollback sample (24.60) against
26.42 patched led to an apparent +7.4% that was **not repeatable**.
The next consecutive unpatched rollback sample reached 28.08 FPS,
**faster than either patched run**. The two unpatched mean is
26.34 FPS versus 26.42 patched: a trivial **+0.08 FPS / +0.3%**;
the patched mean reporting-window 1% low is actually **0.18 FPS lower**
and p95/p99 are essentially indistinguishable.
Unpatched two-run spread was 3.48 FPS (14.1% of the slower run),
demonstrating significant run-to-run variation even with verified
settings and zero new compilation. Avoid equating a static camera with
a deterministic gameplay workload (traffic, simulation state, rendering
load and other conditions can drift). No single CPU hot path has been
proven a bottleneck by these results.

Thread CPU summary (mean of sampled reports):
unpatched controls RSX ~92.4% then 94.8%;
patched ~93.4% and 93.1%. Main GTA RenderThread
~83.4%, 82.8% unpatched and ~81.6%, 81.3% patched.
SPU kernels remain heavily active in all runs. These are utilisation
statistics, not frame-time attribution.

**Decision:** retain the known-working pre-0054 executable and
matching code mirror currently active on the console. Patch 0054
remains staged under `.rsx0054-stage` names and preserved as a
reproducible source patch, but is not justified for FPS by this test.
No more title changes are required for this A/B. For meaningful future
CPU optimisation testing, improve workload reproducibility, capture
per-window data and, ideally, use isolated functional microbenchmarks
plus repeated A/B/A/B controls. Prefer deeper SPU MFC/channel,
reservation, guest JIT and RSX draw-data investigations over
guessing at a 60-FPS solution.

**Never claim an observed 4.5% or 7.4% causal gain from patch 0054
based on these captures.** The patched executable can be restored only
after confirming the game fully closed, with both matching files
swapped together. Normal game settings remain at scheduler B, Mega,
Approximate XFloat, 150% resolution, 100% clocks, 60 FPS cap.

## SPU JIT hotspot investigation — October 30, 2026

**Goal:** investigate the CPU work blocking 60 FPS, not simply change a
setting. The best recent unpatched controlled mean was 26.34 FPS
(24.60 and 28.08 FPS, demonstrating noise). Sustained 60 FPS would
require ~2.28 times the current throughput and remains unproven.

### Evidence recovered from the running original console build

Read the existing `PS5 PROFILE` SIGUSR1 sampling reports and fetched
six already-saved SPU JIT machine-code dump/launch address pairs from
`/data/homebrew/PPSA99303/rpcs3/jit/` **without changing PS5 files**.
Local ignored diagnostics:
`results/gta4-spu-jit-20261030/` and
`hotspot-summary.json`. Summarisation tool:
`tools/gta4-spu-hotspots.py` (last 50 seconds of each log snapshot to
avoid counting old startup samples as new).

Across the original 150% run B3 and the two recent unpatched rollback
controls, the busiest primary SPU kernels repeatedly sampled function
`spu-148f0-__spu-0x148f0-RAYfTjj9unArSvkoJKrSQi8vWG4G`,
especially machine-code offset **+0x28fa**. In the respective 50-second
windows the top-function *listed* offsets included +0x28fa with
15, 25 and 19 hits. These numbers are summed from only the reported
top three functions per profile, not all collected samples.

Offline x86-64 disassembly around +0x28fa shows an aligned local-store
vector load, `vpshufb`, a 16-byte vector saved to the stack,
`vpextrb` into a variable indexed stack byte, reload of the
16-byte stack vector, another `vpshufb`, and a full 16-byte store
to SPU LS. Other guest SPU functions `spu-0e168` at +0x22b and
`spu-37530` at +0x137b show the analogous 32-bit
`vpextrd` stack-overwrite-and-reload pattern; `spu-09548`
at +0x6489 shows the byte case. These are exact observed generated
instruction sequences, **not proof of a specific critical path**.
The previously estimated critical RSX addresses include vertex/index
staging, but resolution 150%->100% had no measured FPS effect.

The existing PS5 port already has two *disabled* SPU JIT options:
`spu_insert_select` (use lane-select rather than variable-index
LLVM insertelement, avoiding a stack round-trip) and
`spu_narrow_ls_store` (when a conservative tracked load/insert/store
pattern matches, write the changed LS element rather than the whole
quad). Do **not** combine their flags for the first test.

### Checker problem and prepared correction

Source inspection found the dormant `ps5_narrow_check` used
`ICmpEQ` on `<16 x i8>` vectors and passed its vector boolean to
`CreateCondBr`, which requires a scalar `i1`. Prepared and saved
`port/rpcs3-latest-patches/0055-PS5-compare-narrow-store-quad-as-scalar.patch`:
bitcast each 128-bit quad to LLVM `i128` and compare the scalar values.
The modified `SPULLVMRecompiler.cpp` **compiled successfully** to a
PS5 core object, with only a pre-existing deprecated `wait` warning.
**Patch 0055 has not been deployed to the console**; a compiled object
does not verify actual checked-narrow-store runtime correctness.
The narrow-store tuning modes are **intentionally blocked** by the new
experiment script until the checker fix is built/deployed/verified.

### Prepared low-risk insert-select-only comparison

Tool: `tools/gta4-spu-tuning.py`. Read-only `prepare` succeeded
against the console: **the original `rpcs3/ps5-tuning.txt` was absent**.
Exact absent baseline and four generated variants are in ignored
`results/gta4-spu-tuning-20261030/`. `insert-select` changes
**only** `spu_insert_select` to 1, explicitly keeping
`spu_narrow_ls_store=0` and `spu_narrow_ls_check=0`.
The real title-side `ps5_tuning.c` parser compiled on the host
and passed `port/tests/check-ps5-spu-tuning.py` for all four variants
and deletion-to-default restoration. The capture script now supports
`--expected-tuning spu_insert_select=1` and detects any nonzero narrow
checker mismatch reports. Existing tests/captures remain valid.

**No console tuning or executable has been modified during this
investigation**; the currently running build is still the known-working
unpatched executable with default SPU JIT options.

Next: once KB-RPCS3 and GTA IV are **fully closed**, apply from
Ubuntu WSL (the script checks the PS5 process list and refuses if
`eboot.bin` is running):

```bash
cd /mnt/c/Users/Callum/Documents/GitHub/KB-RPCS3
python3 tools/gta4-spu-tuning.py insert-select --session results/gta4-spu-tuning-20261030
```

Then launch GTA IV fresh, return to the same outdoor save/camera, allow
SPU JIT compilation to settle, confirm runtime `PS5 TUNING` reports
`spu_insert_select=1`, and use separate new capture labels with:

```powershell
python tools/gta4-scheduler-ab.py capture --session results/gta4-scheduler-20261030 --mode B --label insert-select-run1 --expected-resolution 150 --expected-tuning spu_insert_select=1 --expected-tuning spu_narrow_ls_store=0
```

Follow up with repeated same-scene trials and **restore baseline
after closing the title** using `python3 tools/gta4-spu-tuning.py
restore --session results/gta4-spu-tuning-20261030`, which removes the
experiment-created tuning file. Verify its absence and relaunch
before baseline comparisons. Performance fluctuations of several FPS
in stationary GTA IV make even a positive single run inconclusive.
Monitor crashes, collisions, physics, audio, and p95/p99 frame times
as well as FPS; back out at the first regression.

## SPU insert-select experiment enabled — October 30, 2026

The user confirmed GTA IV / KB-RPCS3 was closed. The prepared isolated
experiment was applied using:

```bash
python3 tools/gta4-spu-tuning.py insert-select --session results/gta4-spu-tuning-20261030
```

The script checked the PS5 process listing via port 9021 and confirmed
there was no running `eboot.bin` or launcher. It atomically staged,
renamed and **byte-for-byte read-back verified** the new tuning file
via FTP at `192.168.0.137:2121`. A separate FTP read-back also
confirmed the exact bytes:

```text
spu_insert_select 1
spu_narrow_ls_store 0
spu_narrow_ls_check 0
```

`/data/homebrew/PPSA99303/rpcs3/ps5-tuning.txt` was previously
**absent**; that absence is saved as the exact baseline in the local
ignored session. The original, pre-patch-0054 executable and
mirror remain installed; the mirror is still 74,601,553 bytes.
The custom game resolution remained 150%. No save, game patch,
title code, physics, or clocks were changed.

**Status: awaiting user's next fresh launch and warmed scene.** Once
launched, verify runtime `PS5 TUNING` actually reports
`spu_insert_select=1` (and both narrow-store flags 0), gameplay
correctness and normal speed. Capture using, e.g.:

```powershell
python tools/gta4-scheduler-ab.py capture --session results/gta4-scheduler-20261030 --mode B --label insert-select-run1 --expected-resolution 150 --expected-tuning spu_insert_select=1 --expected-tuning spu_narrow_ls_store=0 --expected-tuning spu_narrow_ls_check=0
```

Run multiple 45-second comparisons; repeated unpatched controls
were 24.60 / 28.08 FPS, demonstrating substantial scene noise.
A single change in average FPS does not prove a gain. Watch visual
integrity, collision, motion and audio as well as frame times.
To restore defaults later, close the game and run
`python3 tools/gta4-spu-tuning.py restore --session
results/gta4-spu-tuning-20261030` in Ubuntu WSL; the tool restores
the original **absent** tuning file. Verify absence after rollback.

The optional narrow-store checker patch 0055 is still source-only,
not installed; narrow-store tests remain blocked in the helper.

## GTA IV SPU insert-select runtime experiment — October 30, 2026, 03:01–03:04 UTC

The user confirmed the scene had loaded and remained stationary.
The 150%-resolution, scheduler-B, MEGA-SPU, normal-speed GTA IV
benchmark was recorded in three new 45-second windows. The capture
script explicitly verified the runtime `PS5 TUNING` line contained
`spu_insert_select=1`, `spu_narrow_ls_store=0` and
`spu_narrow_ls_check=0`; both usual GTA IV patches, frame limit 60,
normal clock scale, vblank and guest/host timing were verified.
All three captures reported `valid: true` and **no newly compiled
SPU blocks during the 45-second measurement windows**.

The three JSON/log captures are:

- `results/gta4-scheduler-20261030/B-insert-select-run1.{json,log}`
- `results/gta4-scheduler-20261030/B-insert-select-run2.{json,log}`
- `results/gta4-scheduler-20261030/B-insert-select-run3.{json,log}`

| Mean-window metric | Original rollback 1 | Original rollback 2 | Insert-select run 1 | Insert-select run 2 | Insert-select run 3 |
| --- | ---: | ---: | ---: | ---: | ---: |
| FPS | 24.60 | 28.08 | 28.60 | 26.23 | 28.76 |
| Reported 1% low FPS | 21.26 | 24.50 | 25.11 | 23.30 | 24.61 |
| p50 frame time (ms) | 40.68 | 35.60 | 34.95 | 38.22 | 34.76 |
| p95 frame time (ms) | 44.89 | 39.25 | 38.49 | 41.76 | 38.71 |
| p99 frame time (ms) | 47.26 | 40.89 | 40.09 | 43.11 | 40.73 |
| Reporting windows | 10 | 9 | 10 | 9 | 8 |

The three insert-select runs averaged **27.863 FPS**, **24.34**
reported window 1% low, p50 **35.977 ms**, p95 **39.653 ms**,
and p99 **41.31 ms**. The two original rollback controls averaged
**26.34 FPS**, 22.88 reported window 1% low, p50 **38.14 ms**,
p95 **42.07 ms**, p99 **44.075 ms**. The 27.863 vs 26.34 means
represent an *observed* **+1.52 FPS / +5.8%**, which **is not yet a
verified causal performance gain** given the 3.48-FPS unoptimised and
2.53-FPS insert-select run spreads, non-deterministic GTA IV
traffic/simulation, and incomplete A/B/A crossover.

### Direct JIT machine-code comparison: optimisation **is active**

Retrieved the same six named SPU JIT binary files *read-only* via
console FTP from `/data/homebrew/PPSA99303/rpcs3/jit/` during
the insert-select run and saved the second set in
`results/gta4-spu-jit-20261030/insert-select/`.
The original files were fetched before enabling the option.

Disassembly of each dump with `objdump -D -b binary -m i386:x86-64
-M intel` confirms five regenerated dumps had their variable-index
stack-buffer `vpextrb` / `vpextrd` operations removed.
The following figures count indexed `vpextrb BYTE PTR [rsp...]`
and `vpextrd DWORD PTR [rsp...]` inside the *available dumped
regions*, not entire JIT code functions:

| JIT entrypoint | Off/default dump | On/insert-select dump |
| --- | ---: | ---: |
| `spu-01450` | 32 | **0** |
| `spu-09548` | 18 | **0** |
| `spu-0e168` | 6 | **0** |
| `spu-148f0` | 34 | **0** |
| `spu-37530` | 21 | **0** |
| `spu-37860` | 14 | 14 (not regenerated; console mtime Oct 30 02:18) |

The five differing dump hashes, sizes and timestamps confirm fresh
JIT output. **111** indexed `vpextrb/d` instances from the saved
five old dump regions are absent from the corresponding *new*
saved regions, strongly supporting that insert-select removes the
intended stack round-trip machine-code pattern. This is codegen
validation, **not** proof of frame-time savings or game correctness:
the saved dump lengths may vary according to sample offsets and no
entire-function instruction-by-instruction equivalence test has been
performed. The unchanged sixth file is a stale previously cached
dump; do not count it as a failure of the optimisation.

### Status and next control

**Console currently runs the original pre-patch-0054 executable,
with `rpcs3/ps5-tuning.txt` containing `spu_insert_select 1`
and the two narrow flags 0.** The user can now move after completing
the three stationary captures. No game data, saves or original binary
were changed.

Next step for causal test: ask the user to close GTA IV/KB-RPCS3,
use `python3 tools/gta4-spu-tuning.py restore --session
results/gta4-spu-tuning-20261030` from Ubuntu WSL; the script
confirms no title process and restores the *original absent tuning
file*. Verify FTP confirms its absence. Relaunch at the same scene
and capture at least two 45-second runs with
`--expected-tuning spu_insert_select=0` and
`--expected-tuning spu_narrow_ls_store=0`, then repeat enabled
if warranted. Check moving/driving game behaviour, crashes,
SPU patch output and graphic/physics anomalies.
Even if insert-select is beneficial, it is not within sight of
stable 60 FPS from 26–28 FPS.

## SPU insert-select rollback verified — October 30, 2026, 03:09 UTC

The user confirmed GTA IV and KB-RPCS3 were **closed** for the
controlled SPU insert-select switch-back. The initial
`tools/gta4-spu-tuning.py restore --session
results/gta4-spu-tuning-20261030` run **confirmed the PS5 process list
had no `eboot.bin`/launcher** and performed the file restoration, but
exited with `ftplib.error_reply: 226 File deleted` during its final
cleanup operation. PS5 ftpsrv emits nonstandard **226 File deleted**
instead of the expected 250. The issue was in the helper's treatment
of the FTP success response, **not** the restored tuning state.

Multiple independent readbacks verified **all three** paths absent:

- `rpcs3/ps5-tuning.txt` (originally absent, the exact baseline)
- `rpcs3/ps5-tuning.txt.spu-test-stage`
- `rpcs3/ps5-tuning.txt.spu-test-prev`

The verified custom NPUB30702 config still has scheduler B/RPCS3,
Mega SPU blocks, Approximate XFloat, 150% resolution, 100% clocks,
60 frame cap and Strict Rendering disabled. The original
pre-patch-0054 `rpcs3ps5-text.bin` remains 74,601,553 bytes.
No executable, save, game patch or title configuration changed.

**Tool fix:** `tools/gta4-spu-tuning.py` now uses
`delete_verified()`: accept a nonstandard 226 deletion reply
*only if an independent FTP RETR proves the file absent*; otherwise
raise. The recovery path uses this helper too.
`port/tests/check-ps5-spu-tuning-ftp.py` contains five mocked
tests (standard 250, nonstandard 226, false 226, unexpected 421
and restoring absent original); **5/5 PASS**. Python compilation
and `git diff --check` PASS.

**Console state after restoration:** Original pre-patch-0054
executable/mirror with **all default SPU tuning**. Neither insert-select
nor narrow-store options are on. The runtime defaults take effect
upon a *fresh relaunch*.

**Next:** user to launch KB-RPCS3 and GTA IV, return to the same
outdoor save/camera/conditions and let JIT settle. Once they reply
`SPU rollback ready`, capture two or three separate 45-second
original-control windows, checking live
`--expected-tuning spu_insert_select=0`
and `--expected-tuning spu_narrow_ls_store=0` and
`--expected-tuning spu_narrow_ls_check=0` and
`--expected-resolution 150` with unique labels
`B-insert-rollback1`, `B-insert-rollback2`, etc.
Compare against insert-select ON runs 28.60, 26.23 and 28.76 FPS;
the initial unoptimised controls 24.60 and 28.08 show substantial
normal variance. No causal performance conclusion yet.

## Cross-subsystem performance audit initiated — October 30, 2026

The user proposed auditing the entire emulator rather than continuing
single-flag FPS guesses. Completed an initial source- and trace-grounded
critical-path review and saved the full report at:
`game research/GTA-IV-performance-audit-20261030.md`.

**Preliminary conclusion (not a proven root cause):**
The two strongest candidate bottlenecks are SPU JIT/MFC work and
CPU-side RSX command/draw preparation; current high RSX CPU utilisation
may partly measure **deliberate spin/yield waiting** from the
PS5 `rpcs3ps5_sched_yield` fast-clock implementation rather than
productive GPU work. The current frame counter records
`ps5_gs_frame::flip` callbacks, not the critical path, GPU timestamps
or true presentation completion. The existing RSX FIFO idle-load
counter is **not** logged in the FPS captures; Vulkan submission,
fence/present waits and per-frame vertex/index uploads likewise
lack durations in the current test logs.
The SPU sampler interrupts one hot thread 400 times at ~5 ms spacing;
the impact of this profiler on performance has not been measured.

Provisional symbolisation of the recurring RSX sample addresses
against the latest **patched** linker output suggests
`write_vertex_data_to_memory`, `write_index_array_data_to_buffer`,
and `FIFO_control::fetch_u32`; **do not claim exact symbol matches
without the original console build's matching ELF**. The candidate
0054 memcpy optimisation already failed to show an FPS improvement,
so more blindly tweaking RSX copy guards is not justified.

Existing resolution 150%->100% comparison showed no gain but was only
one trial, and warmed mprotect counts are near zero/low tens per
second despite the large startup burst. Console core frequency
readouts around 3.3–3.4 GHz do not explain a >2x frame budget miss.
Stable 60 FPS requires reducing ~38 ms of typical frame latency
to <=16.67 ms; no current evidence demonstrates such a path.

**Next recommended engineering task:** build diagnostic-only
low-overhead counters for RSX FIFO productive vs idle,
index/vertex staging, GPU queue/present and waits, guest SPU
execution vs channel/DMA stalls, and PS5 yield/sleep overhead;
measure profiler-on/off perturbation; collect reproducible
moving-scene data with per-frame correlation. **No PS5 files or
settings were altered by this audit.** Original SPU tuning was
already restored before the user asked.

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
