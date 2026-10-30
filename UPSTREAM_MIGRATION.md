# RPCS3 upstream migration and measured optimization

The October 29, 2026 upstream snapshot is
`8e26652c85bb5658965fa5731d9a0309ca10b42b`, 302 commits beyond the established
`46aee28f8` base. This is an update of the emulator source compiled for PS5.
The desktop executable is not used on the console.

The existing 48 PS5 patches have been replayed onto this snapshot, preserving
the Vulkan platform backend, native TLS, PS5 runtime and installed-title boot
path fix. The two replay conflicts were resolved by retaining upstream's
Windows GLEW condition plus the PS5 exclusion, and retaining upstream's SPU
calling convention plus the PS5 tracking hooks. Patch 0049 is an optional,
off-by-default RSX DMA wait experiment. Patch 0050 adapts the PS5 frontend to
upstream's separated renderer backend and display counter APIs, and excludes
the unavailable OpenGL backend from the new renderer factory on PS5.
Patch 0051 excludes the new Qt keyboard-window update from PS5 controller input.
Patch 0052 includes upstream's blob-detector helpers in the PS5 target and
excludes the unsupported HID Wiimote-to-GunCon bridge.

## Separate source and output directories

The established `~/work/rpcs3`, `rpcs3-build-native` and `ps5-rpcs3-app-native`
remain available. The migrated build uses:

- Source: `~/work/rpcs3-latest`
- Core build and compiler log: `~/work/rpcs3-build-latest`, `~/work/rpcs3-build-latest.log`
- Title output: `~/work/ps5-rpcs3-app-latest/dist/PPSA99303/`
- Full build log: `~/work/kb-rpcs3-latest-build.log`

From Ubuntu WSL, in the Windows KB-RPCS3 checkout:

```bash
# Only needed when creating the new source checkout on another machine:
bash port/prepare-rpcs3-latest.sh "$HOME/work/rpcs3-latest"

set -o pipefail
bash tools/wsl-build-latest.sh 2>&1 | tee "$HOME/work/kb-rpcs3-latest-build.log"
```

The original patch series remains the default for
`port/apply-rpcs3-patches.sh`. The latest profile uses the separate, pinned
latest series (now 54 patches) recorded in `port/rpcs3-latest.json`.

## First optimization candidate

The captured Multithreaded RSX regression profiles spent many RSX samples in
`rsx::dma_manager::sync()`, which polls an offloader completion counter.
Patch 0049 adds a bounded atomic wait after a short spin on PS5. Renderer
callbacks continue to run between waits; no guest clock or physics setting is
changed. Completion is rechecked before sleeping, and waits have a finite
timeout so a missed notification cannot permanently stall callback servicing.

The experiment defaults to `rsx_dma_wait_us 0`, preserving the polling behavior.
Once the migrated build has passed startup and gameplay tests, compare the
same route with Multithreaded RSX enabled in both runs and this line in
`rpcs3/ps5-tuning.txt`:

```text
rsx_dma_wait_us 100
```

Set the value to `0` or delete the tuning file to restore the default. Supported
values are 0–2000 microseconds. Keep the game's clock scale at 100%, vblank at
60 Hz, and the existing matching collision patch enabled. Compare FPS, frame
times, RSX/offloader CPU use and audio, not just the FPS limit.

Host checks exercise the actual sync routine's completion, disabled mode,
callback progress, wakeup race, fault and termination behavior. They also test
the actual title-side parser's default, clamp and deletion rollback:

```bash
python3 port/tests/check-ps5-boot-path.py "$HOME/work/rpcs3-latest"
python3 port/tests/check-ps5-rsx-wait.py "$HOME/work/rpcs3-latest"
```

These checks do not establish a console performance improvement or 60 FPS.
Do not replace console game data or reuse native build archives from the
established source checkout when linking the migrated title. Console deployment
must use the signed `eboot.bin` together with its matching code mirror.

## Build verification — October 30, 2026

The complete PS5 core and signed title build passed at port revision
`f568df06faacb30cb1a93a64668f55b00d357332` (RPCS3 build `20560-f568df06`).
All nine required title files passed packaging checks. Native TLS template
validation passed with 128 initialized bytes, 15104 memory bytes and 32-byte
alignment. The 52-patch replay reproduces the same source tree.

The RSX DMA wait experiment remains disabled by default. This build result is
not a console gameplay or performance result; startup, game compatibility and
same-route profiling must be verified on the console after installation.

## Loading-screen flashing fix — October 30, 2026

Patch 0053 resolves saved Vulkan adapter aliases to the console's physical GPU
when comparing renderer identities. The startup log repeatedly replaced
`Vulkan | PlayStation 5 GPU (RADV NAVI21)` with `Vulkan | PS5 GPU (RADV)` during
PPU compilation. The alias selected the correct GPU, but upstream's new identity
check treated it as an adapter change on every flip and recreated the renderer.
The PS5 now compares the physical GPU identity; backend changes still trigger
replacement, and desktop adapter selection is unchanged.

The focused regression check compiles the actual identity method for both paths:

```bash
python3 port/tests/check-ps5-renderer-identity.py "$HOME/work/rpcs3-latest"
```

The patch series contained 53 patches after the renderer fix; patch 0054 adds
a separate, experimental RSX-copy fast path described below. Hardware verification
requires a restart into the rebuilt executable and its matching code mirror.

The rebuilt core, signed title, native TLS layout and all nine packaging checks
passed. The pair was installed over FTP at `192.168.0.137:2121` after the app
closed, with the original pair retained under `.flicker-fix-old` filenames.
FTP returns a decrypted ELF: its ELF/program headers and every PT_LOAD/PT_TLS
segment matched the converted build; the code mirror matched by SHA-256.
After relaunching GTA IV (`NPUB30702`), the first 33 seconds of the new startup
log covered module loading and rendering with zero renderer replacements,
compared with 222 replacements in the captured failing log. This establishes
that the reset loop stopped; it is not a long-duration gameplay benchmark.

## Patch 0054 — candidate PS5 RSX copy fast path (October 30, 2026)

Gameplay profiles of GTA IV NPUB30702 on the migrated title sampled
`rsx::draw_command_processor::write_vertex_data_to_memory()`, index
upload and SPU MFC/reservation execution. A resolution change from 150%
to 100% produced no measured FPS improvement (25.29 vs 24.77 FPS in
individual 45-second captures); further CPU-side investigation is warranted.
This is not proof of a particular critical path.

`port/rpcs3-latest-patches/0054-PS5-skip-non-strict-RSX-copy-reservation-setup.patch`
adds a conservative PS5-only branch to `rsx::dma_manager::copy(void*,void*,u32)`
and offload `raw_copy`. With `Strict Rendering Mode: false` (the captured
GTA IV setting), the old reservation guard could not lock, but the code
still calculated the guest VM address and constructed the no-op guard
per copy. The new path copies directly in non-strict mode; strict mode
and desktop RPCS3 preserve their original paths.

Tests completed:
- `port/tests/check-ps5-rsx-copy.py` compiled the actual copy method and
  raw-copy branch for both PS5 and desktop, testing strict, non-strict,
  synchronous and queued copies, plus non-VM input.
- Existing RSX wait and Vulkan renderer-identity tests passed.
- `git apply --cached --check` passes against the source checkout index;
  reverse-check against the modified worktree passes.
- Modified PS5 RSXOffload C++ object built successfully.

**Status:** source candidate tested; **not installed on the console and not
yet measured for GTA IV FPS**. It may only remove a very small amount of CPU
work. Do not report the change as progress toward stable 60 FPS without
a controlled build A/B and frame-time comparison.

Build with `tools/wsl-build-latest.sh`, keeping this patched WSL source
checkout. Install only the matching signed `eboot.bin` and code mirror
after the app is closed, and preserve the existing working pair for rollback.
Use scheduler B, MEGA, Approximate XFloat, 100% clocks, existing 60 FPS and
collision patches, `Resolution Scale: 150`, and the same warmed outdoor
save/camera. Capture `PS5 FPS`, frame-time percentiles and thread CPU.
If the result is negative or indistinguishable from noise, roll back.

### Patch 0054 build status

The subsequent full migrated-core and PS5 title build succeeded with patch
0054 present in the WSL working source. Native TLS validation and all nine
title packaging checks passed. Locally staged candidate:

- `~/work/ps5-rpcs3-app-latest/dist/PPSA99303/eboot.bin`,
  SHA-256 `ff19977e5eb84421487ab5101e0353dc176412ec1e4e8dae45d104500d343957`
- `~/work/ps5-rpcs3-app-latest/dist/PPSA99303/rpcs3ps5-text.bin`,
  SHA-256 `90dd397340fc2c0f67cbc8247068ec46e92b9c4b75f38ed363177fbec23fba10`

**Not deployed:** the console still has its previous known-working title pair.
Before replacing any running files, close the game, retain the previous
signed executable and matching mirror for rollback, then install both new
files together. A successful build and host tests are not an FPS result.

### Patch 0054 installed for console validation

The user confirmed KB-RPCS3 closed on October 30, 2026.
The PS5 process listing confirmed no running `eboot.bin` or launcher,
and `tools/deploy-gta4-rsx0054.py` installed the staged, SHA/ELF-validated
signed title and code mirror pair over FTP `192.168.0.137:2121`.
Old versions were retained as `eboot.bin.before-rsx0054-20261030`
and `rpcs3ps5-text.bin.before-rsx0054-20261030`. The installed mirror
matched SHA-256 `90dd397340fc2c0f67cbc8247068ec46e92b9c4b75f38ed363177fbec23fba10`;
the decrypted installed ELF's PT_LOAD and PT_TLS contents matched the
locally linked ELF. All other title files and game data were unchanged.
The saved GTA IV config is scheduler B + Mega + 150% resolution + normal
speed, with Strict Rendering Mode disabled.

This verifies deployment only, **not game startup or FPS improvement**.
After user relaunch, confirm runtime and compare at the same outdoor scene.
Rollback (only after game closes): `python3 tools/deploy-gta4-rsx0054.py rollback`
in Ubuntu WSL; it restores both previous files together.

### Patch 0054 first GTA IV FPS captures

After the user launched the installed patched pair and returned to the
stationary 150%-resolution GTA IV scene, two 45-second samples both passed
runtime config, patches and normal-speed validation with no new SPU
compilations. Raw results in
`results/gta4-scheduler-20261030/B-rsx0054-run{1,2}.{log,json}`.

| Metric | Pre-patch B3 | Patch 0054 run 1 | Patch 0054 run 2 |
| --- | ---: | ---: | ---: |
| Average FPS | 25.29 | 26.38 | 26.46 |
| Mean window 1% low FPS | 21.73 | 22.44 | 22.96 |
| Mean window p95 ms | 43.48 | 42.33 | 41.92 |
| Mean window p99 ms | 46.25 | 44.66 | 43.65 |

The two patched runs averaged **26.42 FPS**, +1.13 FPS / +4.5%
relative to the strongest and last unpatched 150% reference B3.
The improvement is **not yet attributable causally to patch 0054**:
time-of-day, camera, scene load and run order can vary. The next useful
control is to close the title, safely revert the old executable and
mirror *as a pair* using
`python3 tools/deploy-gta4-rsx0054.py rollback`, then repeat the
same scene and restore the patched pair by running
`python3 tools/deploy-gta4-rsx0054.py activate` after another close.
The console's old pair is preserved. Performance in moving/driving
gameplay and long-term stability remain unverified.

### Patch 0054 rollback control provisioned — October 30, 2026

The user closed GTA IV and KB-RPCS3 after the two patched FPS captures.
The deployment script verified the console process listing was free of
`eboot.bin` and restored both original executable and original code
mirror by paired FTP renames. Post-rollback FTP status shows the original
mirror is 74,601,553 bytes and the patched mirror is staged under
`rpcs3ps5-text.bin.rsx0054-stage` (74,601,297 bytes). The original
executable is active again; the patched executable is preserved under
`eboot.bin.rsx0054-stage`. No config changed: scheduler B, Mega,
Approximate XFloat, resolution 150%, clocks 100%, frame limit 60,
Strict Rendering disabled.

**Next:** relaunch unpatched GTA IV, return to the same outdoor spot
and camera angle, settle compilation, then capture 45 seconds using
`B-rollback-control1` label and runtime `--expected-resolution 150`.
After that comparison, the original and patched pair can be exchanged
again once the user closes KB-RPCS3.

### Patch 0054 — follow-up rollback controls overturn apparent gain

After the two patched captures (26.38 and 26.46 FPS), the user closed
the game and the original executable and mirror were restored as a pair.
Two 45-second 150%-resolution rollback captures passed normal-speed,
scheduler, patch and compilation checks with **24.60 and 28.08 FPS**.

| Metric | Unpatched rollback mean | Patch 0054 mean |
| --- | ---: | ---: |
| Average FPS | **26.34** | **26.42** |
| Mean window 1% low FPS | 22.88 | 22.70 |
| Mean window p95 ms | 42.07 | 42.13 |
| Mean window p99 ms | 44.08 | 44.16 |

**Result: no measurable code-level improvement established.** The
+4.5% versus previous run B3, and the apparent +7.4% versus the first
rollback control, were both swamped by run-to-run scene/runtime
variation: the second unpatched control (28.08 FPS) was faster than
either patched capture. The two-run average difference is +0.08 FPS
(+0.3%), with no 1% low or tail improvement.

The known-working original executable/mirror are currently active;
the patched 0054 pair is retained on the console under the
`.rsx0054-stage` filenames and the patch remains replayable in the
source series. Do not report 0054 as a performance win. Future tests
need repeatable scene/traffic workload controls and more targeted
SPU JIT, MFC/DMA and RSX profiling.

### SPU JIT vector-insert hotspot research and patch 0055

Investigation of **unpatched** GTA IV NPUB30702 profiles
(October 30, 2026) found recurring hot guest machine-code offsets in
`spu-148f0`, `spu-0e168`, `spu-37530` and `spu-09548`.
The matching SPU JIT binary dumps were downloaded **read-only** from
the existing console `/app0/rpcs3/jit` cache and disassembled.
Observed instructions include `vpshufb`, 16-byte stack vector store,
variable-index `vpextrb`/`vpextrd` insertion, stack vector reload,
and a full 16-byte local-store write. This is a plausible cost
for the existing default LLVM variable-index vector insertion,
but sampling is not a frame-time critical path measurement.

The optional `spu_insert_select` experiment can target this class
without changing memory store semantics. The more aggressive
`spu_narrow_ls_store` already has a debug equivalence check, but
inspection found a vector-condition LLVM IR issue in that check.
**Patch 0055** (`port/rpcs3-latest-patches/0055-PS5-compare-narrow-store-quad-as-scalar.patch`)
changes its 128-bit vector equality to a scalar `i128` equality before
a conditional branch. The modified SPU recompiler C++ object built.
This fix **has not been installed or run on console**; no narrow-store
mode may be enabled on the currently installed original build.

New tools: `tools/gta4-spu-hotspots.py` for sampling summaries,
`tools/gta4-spu-tuning.py` for reversible FTP tuning while game is
closed (narrow-store modes blocked), and
`port/tests/check-ps5-spu-tuning.py`, which successfully compiled
the real C parser and tested each configuration and deletion rollback.
`tools/gta4-scheduler-ab.py capture` accepts
`--expected-tuning spu_insert_select=1` to check the actual runtime.
The original console's `ps5-tuning.txt` is **absent**, preserved as
the exact baseline. No console files changed in this investigation.
Future test: one setting only, `spu_insert_select=1`, next *fresh*
title launch, with repeated same-scene baseline/control runs.
A positive FPS result needs to beat the several-FPS noise seen during
the patch 0054 rollback study. Nothing yet establishes stable 60 FPS.

### First console FPS test of SPU insert-select (October 30, 2026)

Three verified 45-second, 150%-resolution, scheduler-B GTA IV
captures with **`spu_insert_select=1`** and both narrow-store flags
0 returned **28.60, 26.23, 28.76 FPS**, mean **27.86 FPS**;
mean reported window 1% low **24.34 FPS**, p95 **39.65 ms**,
p99 **41.31 ms**. The prior two rollback controls (all options
off) yielded **24.60 and 28.08 FPS**, mean **26.34 FPS**,
1% low **22.88 FPS**, p95 **42.07 ms**, p99 **44.08 ms**.
All five captures passed runtime patch, speed, resolution and
scheduler checks with no SPU block compilation during capture.
An apparent +1.52 FPS/+5.8% mean increase is **not yet causal**,
given the several-FPS run-to-run variability.

New machine-code evidence: fetched and compared matching saved
SPU JIT dumps, before vs after enabling insert-select, from the
console's `rpcs3/jit` directory. In five freshly regenerated
function dump regions (`spu-01450`, `spu-09548`, `spu-0e168`,
`spu-148f0`, `spu-37530`), the indexed
`vpextrb/vpextrd` stack-buffer insert operations disappeared
(old counted 32, 18, 6, 34, 21 respectively; **all 0** in new
dump regions). The saved regions can have different lengths;
these are not whole-function instruction-count comparisons.
A sixth `spu-37860` dump retained its old Oct 30 02:18 timestamp
and was not regenerated. This **confirms intended JIT codegen
change in hot functions** but not an FPS gain or behavioral
equivalence for all possible game states.

Console remains on the original pre-0054 executable with
`ps5-tuning.txt` temporarily set to `spu_insert_select=1`.
Next controlled test: close game and title first, then
`python3 tools/gta4-spu-tuning.py restore --session results/gta4-spu-tuning-20261030`
from the Windows repo in Ubuntu WSL, verify the tuning file is again
**absent** and relaunch for a fresh baseline. Preserve all snapshots
in `results/gta4-spu-jit-20261030` and
`results/gta4-scheduler-20261030`; do not claim stable 60 FPS.

### SPU insert-select controlled rollback completed (03:09 UTC)

User closed KB-RPCS3/GTA IV. `tools/gta4-spu-tuning.py restore`
verified the title and launcher were stopped and restored the exact
**original absent** tuning file. PS5 ftpsrv's nonstandard FTP reply
`226 File deleted` made the initial command exit in final cleanup,
but **independent FTP readback confirmed success** and absence of the
live, stage and backup tuning files. The original pre-0054 code mirror
remains 74,601,553 bytes; game config is unchanged (B/MEGA/
Approximate, 150%, 100% clocks, 60 cap, non-strict).

Fixed cleanup in the experiment helper: accept a 226 deletion response
only after verifying the removed path really is absent.
Added `port/tests/check-ps5-spu-tuning-ftp.py`: all five mocked FTP
deletion/rollback tests pass. No executable or game files changed.
The console is now ready for a fresh default-SPU launch and several
unoptimised 45-second controls to compare with insert-select ON
28.60 / 26.23 / 28.76 FPS. Still no proven causal FPS gain.

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

### Patch 0056 first runtime benchmark results (03:45–03:48 UTC)

Two valid 45-second GTA IV stationary outdoor captures on installed
diagnostic patch 0056, scheduler B / Mega / 150%, SPU experiment flags
off, no SPU compilations:
**24.71 FPS** (p95 44.14ms) and **22.94 FPS** (p95 47.78ms).
The `PS5 PERF` counters are active and valid. The last nine logged
counter windows correspond to ~44.6 seconds in each capture;
`tools/gta4-rsx-perf.py --capture-only` now selects only those
windows instead of including game startup.

CPU wall time normalised by frame rate, runs 1/2:
vertex copy **2.757/2.706 ms/frame**, index conversion
**0.935/0.921 ms/frame**, Vulkan close+submit
**0.703/0.702 ms/frame** (primary submit is nested;
never add it), DMA sync **0.084/0.083 ms/frame**.
This **~4.4ms/frame in specific measured stages** is not a
critical-path decomposition, and the much longer RSX FIFO dispatch
and SPU/PPU/GPU work remain unaccounted for. Observed vertex
upload counts ~1760/frame and index conversions ~3030–3060/frame,
nearly identical across different FPS. First-run/second-run rates
saved in `results/gta4-rsx-perf-20261030/capture-analysis.json`.

An exact symbol map from this diagnostic build's
`build/ps5/link/llvm-pie.elf` identified recurring RSX samples in
`tsc_now` (PS5 fast clock), vertex/index conversion, FIFO fetching
and execution, Vulkan query/texture/descriptor handling, and RADV.
Roughly 255/1600 and 265/1600 RSX profiler samples across four
recent windows per log hit fast-clock helper addresses (~16%).
This is *sample frequency*, not a percentage of frame latency.
FIFO running vs idle counters are only 1-in-128 sampled iterations
and classification is based on the **post-call state**; it does
not prove the number of productive RSX commands processed.
GPU execution and actual present timing remain unmeasured.

No additional console changes since deployment.
Next engineering step: instrument real RSX FIFO packet vs
BUSY/EMPTY/NOP/self-jump polling, clock/yield/sleep counts
and exact timing, and SPU/PPU dependencies. FPS difference
from previous executable is confounded by a rebuilt core
(0054, 0055 and 0056) and noisy GTA IV workloads;
avoid claiming profiler overhead is proven.
**Rollback only after user closes GTA IV and KB-RPCS3.**

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

### Patch 0057 45-second FIFO / fast-clock measurements (04:08–04:10 UTC)

Two clean, validated same-camera GTA IV captures on patch 0057
at 150% resolution, scheduler B, with **0 newly compiled SPU
blocks**: **23.50 FPS** and **23.69 FPS** (window mean).
Each run yielded nine new `PS5 PERF`, `PS5 FIFO2` and
`PS5 CLOCK2` reporting windows. All three record types
matched in window duration. First-read FIFO category totals
agree with the previous running/idle sample count to +/-1.

1-in-128 first-read FIFO sample percentages run1/run2:
- ordinary method **71.47% / 71.27%**
- NOP **26.58% / 26.74%**
- EMPTY **0.86% / 0.91%**
- BUSY **0% / 0%**
- self-jump **0.18% / 0.17%**
- other flow **0.91% / 0.90%**

The theory that the RSX FIFO is *primarily returning EMPTY/BUSY*
during these stationary captures is **not supported**, but later
commands within each invocation and other RSX wait stages
remain unmeasured. NOPs are common; don't mistake a sampled NOP
for a completed guest draw or assign it an entire frame interval.

Global clock reads ~**1.360–1.361 million/sec**, spin decisions
~22–23k/sec, actual OS yields ~7.1–7.4k/sec, and sleeps
~732–774/sec across all emulator threads. The matched linked
ELF shows `clock_gettime` and `rpcs3ps5_clock_gettime`
both resolve to code 0xEE560. Counting entry+exit timestamps
generated **by the diagnostic instrumentation itself** gives
~**470,852–478,306 extra clock calls/sec** (34.6–35.1% of
observed clocks). Approx ~883k–889k remaining calls/sec
have other sources, and may still include other diagnostics.
Do not assert 1.36M calls are baseline traffic or that
`tsc_now` overhead is independently proven.

Saved `results/gta4-rsx-perf-20261030/fifo-0057-combined.json`
and individual captured logs/summary files; full interpretation,
caveats and next step are in
`game research/GTA-IV-performance-audit-20261030.md`.
The next defensible diagnostic is **per-thread** clock/useful
FIFO/PPU-SPU attribution plus **instrumentation-on/off
same-code A/B**. Current patch 0057 remains installed;
rollback requires first confirming KB-RPCS3 is fully closed.

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

### 2026-10-30 — 150→100→150 diagnostic completed, patch 0058 profiler OFF

All selected GTA IV runs: scheduler B, 150/100/150 scales,
Mega SPU, Approximate XFloat, clocks 100, FPS cap 60, no
experimental SPU tuning, **0 new SPU compilations**.

Two 45s runs each condition:
- initial 150: 25.21/24.44 FPS; report-interval weighted 24.822 FPS
- 100: 25.04/24.38 FPS; weighted 24.712 FPS
- returned 150: **25.41/21.93 FPS**; weighted **23.668 FPS**

Excluded 100% run2 (23.29 FPS) due to **180 new SPU
compilations** and a severe p99 spike; even though capture
tool reports basic config valid, the comparison tool rejects
new compilations.

The 100%-minus-initial-150% difference is **-0.11 FPS
(-0.44%)**, so reducing scaled pixels by ~2.25x yielded
no observed performance benefit. However, the restored
150% captures varied **3.48 FPS between themselves**,
so the reversal failed as a stable precise causal FPS
comparison: background GTA IV load drift is large.
This deprioritises **pixel-count-scaled GPU fill/shader**
optimisation but does **not** prove CPU-only bottleneck,
nor rule out fixed GPU driver/geometry/queue costs.

Verified zero PERF/FIFO2/CLOCK2/PROFILE instrumentation
markers in all six comparison logs. Runtime CPU utilisation
of multiple SPUs is near 95–99%, RSX ~80–93%,
RenderThread ~74–87%, but CPU utilisation alone cannot
identify the frame's serial critical path.

All six clean captures and the excluded contaminated run
are documented in
`results/gta4-resolution-20261030/resolution-compare.json`,
with more detailed account in
`game research/GTA-IV-performance-audit-20261030.md`.

The next step is *low-overhead frame dependency tracing* at
PPU render boundary → SPU job/wait → RSX FIFO/flip →
Vulkan queue submit/completion/fence. Use infrequent
timestamps and buffered reports; retain separate
instrumentation-on/off controls to quantify perturbation.
Inspect VKPresent.cpp, VKCommandStream.cpp and VKQueryPool.cpp
before touching the title. Current installed build is
patch 0058 OFF, restored 150%; game is still **running**.
**Do not deploy or alter config until user closes both
GTA IV and KB-RPCS3 and a process check passes.**

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

### 0059 live diagnostic results (2026-10-30 ~05:13–05:16 UTC)

After deployment of 0059 sparse CPU timeline, user launched GTA IV
at preserved 150% scale, scheduler B/Mega/Approximate, 100% clocks,
all SPU tuning flags off. Two 45-second stationary scene runs:
`B-framedep0059-run1` **22.14 FPS**, 34 sampled guest queue
epochs, 1,422 events; `run2` **23.45 FPS**, 35 epochs,
1,485 events. Both: zero new SPU compilations, zero dropped
events and no old PERF/FIFO2/CLOCK2/SIGUSR1 profiler markers.
Time-weighted FPS 22.136/23.455, mean **22.795**.

At sampled sites, RSX present host call 0.392/0.358 ms,
vkQueueSubmit CPU call 0.079/0.079 ms, vkAcquire 0.019/0.018
ms, vkPresent 0.010/0.011 ms. Not GPU execution or
complete critical-path timings. No host fence waits recorded
during sample windows.

PPU RenderThread (`0x0100000a`) observed semaphore blocking
waits averaged only 3.334/2.363 ms (11/8 instances).
Much longer PPU waits belong to GTA Audio Update
(`0x0100000e`, ~42/39ms), RMPTFX Update
(`0x01000015`, ~42/39ms), RAGE crmtScheduler[0]
(`0x01000010`, ~31/32ms), audio Multistream
(`0x0100000c`, ~10ms), one unnamed low-CPU worker
(`0x01000008`, ~46/43ms) and infrequent streamer
long waits. **Do not attribute these to frame-critical
stalls** without proving frame dependencies. RenderThread
could still wait through uninstrumented mechanisms. Last
11 watchdog CPU windows per capture: RSX 88.6/89.6%,
GTA RenderThread 84.4/84.9%, secondary SPU 97.5/97.0%,
primary SPU worker 97.1/97.7%; utilisation is not the
serial critical path.

Relative to all four prior 0058 profiler-OFF 150%-scale
controls (weighted mean **24.245 FPS**), new trace mean
**22.795 FPS** is **-1.450 FPS (-5.98%)**. But patch0058
return-to-150 alone ranged from 25.409 to 21.927 FPS;
**no causal trace overhead claim** until fresh 0058
switchback. Neither Vulkan CPU submission nor background
PPU waits explain the missing ~23 ms toward 60 FPS.
Prioritise low-perturbation active PPU/SPU/RSX FIFO
execution/boundary measurements and actual GPU timestamp
queries if available.

Machine-readable results:
`results/gta4-rsx-perf-20261030/frame-dep-0059-combined.json`
with both capture summaries, per-thread wait breakdown,
timing, CPU utilisation and controls. The individual
`B-framedep0059-run{1,2}.{json,log}` and
`B-framedep0059-run{1,2}-framedep.json` are in
`results/gta4-scheduler-20261030`. Parser
`tools/gta4-frame-dep.py` now emits
`ppu_waits_by_thread_id`.

PS5 remains running 0059 at 150%. **Do not alter console
files until user explicitly closes GTA IV and KB-RPCS3.**
To restore 0058 control after process check:
`tools/deploy-gta4-rsx0059.py rollback`.

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
