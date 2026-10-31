# GTA IV: watched FIFO self-jump yield experiment

<!-- latest-state:start -->
**FIFO experiment COMPLETE (2026-10-30):** Direct OS yielding showed no
useful FPS gain. Original policy retained, tuning absent. Do not repeat
without new evidence. Subsequent SPU helper diagnostics are complete;
console is now restored/readback-verified to lighter0062, with0063 retained
as stage. See [helper findings](GTA-IV-SPU-helper-boundaries-20261030.md) for
the measured MFC lead, overhead caveats and exact next source-audit step.
<!-- latest-state:end -->

Date: 2026-10-30. Profile: `rpcs3-latest`, patch 0061 on top of 0060.
Status: host checks and full PS5 build PASS; patch0061 installed and verified
in control mode 0 after user closure confirmation.
Completed on-console A/B/A shows no demonstrated useful gain; original policy retained.

## Evidence and hypothesis

The two patch0060 captures recorded 24.927 and 27.492 timestamp-weighted
FPS, no SPU compilations, and 15.62% / 12.32% of sampled `run_FIFO`
wall time classified as spinning. These are sampled FIFO time shares, not
frame latency shares or predicted gains. The dominant sampled FIFO time
was running, and the SPU timing probes did not cover their target.

`FIFO_control::set_get()` installs a memory watch for self-jumps.
`FIFO_control::read()` returns `FIFO_EMPTY` while the watched guest word
is unchanged. The dispatcher's empty branch then calls
`std::this_thread::yield()`. On PS5 that reaches the shared fastclock yield
wrapper: usually a 2-us spin, periodically an OS yield, eventually a sleep
for a sustained burst. The wrapper serves other waits too; this experiment
does not change it globally.

Hypothesis: giving up the RSX timeslice directly while waiting for a
producer to rewrite a self-jump could help that producer progress. It can
also increase RSX wake latency or syscall overhead and reduce FPS. Near-full
SPU/RSX CPU occupancy does not establish physical-core contention.

## Isolated change

The title appends key **11**, `rsx_fifo_yield`, to its existing tuning ABI:

- `0` (default, also after deleting the tuning file): original wrapper.
- `1`: `scePthreadYield()` for a watched self-jump wait only.
- Other values: clamp to `0`.

`is_self_jump_wait()` checks that no arguments are pending, the watch is
active, and GET is at the watched position. The read path clears the watch
when the word changes, the address changes, or the mapping is invalid.
True empty queues retain their original policy, including when the
performance state still says spinning. The first running-to-empty
transition retains its timestamp and state update.

Each call yields once and returns to the existing outer loop. The next
read checks guest memory again. No new notification dependency, indefinite
wait, command skipping, altered FIFO ordering or guest state is introduced.
Stop/pause/context/backend handling remains in the existing outer loop;
OS scheduling latency still needs measurement on PS5.

Existing patch0060 worker sampling remains enabled and unchanged. The
older heavy profiler and patch0059 frame probes remain disabled.

## Files and rollback

- Core change: `port/rpcs3-latest-patches/0061-PS5-opt-in-self-jump-OS-yield.patch`.
- Title tuning/parser: `app/ps5/src/ps5_tuning.c`.
- Focused host proof: `port/tests/check-ps5-fifo-yield.py <upstream-source>`.
- Paired-file installer: `tools/deploy-gta4-rsx0061.py` (hash-pinned stage,
  activation readback and `.before-rsx0061-20261030` rollback pair).
- Tuning helper: `tools/gta4-fifo-yield.py`.

The actual build source is `/home/callum/work/rpcs3-latest` in
**Ubuntu-24.04**, user `callum`. The Windows `rpcs3` checkout is untouched.
The selected profile has 61 patches; the established profile is unchanged.

Exact original 0060 signed executable, code mirror and converted ELF were
preserved in `/home/callum/work/rsx0060-control-20261030` before rebuilding.
Their SHA256 values match the recorded patch0060 build. The local ignored
session `results/gta4-fifo-yield-20261030/tuning` records that the console's
original tuning file was **absent** and contains control/candidate variants.
Preparation and console size inspection were read-only on PS5.

## Controlled on-console test

Before changing either executable or tuning: close GTA IV and KB-RPCS3,
then verify the actual console process list. FTP is `192.168.0.137:2121`.
Keep the signed executable and code mirror paired; preserve all previous
backups, game data, configs, saves and caches.

1. Install the verified patch0061 package with mode `0` (no tuning file
   also selects it). Keep current B / Mega / Approximate XFloat / 150%
   resolution / 100% clocks / 60 FPS cap and all SPU experiments off.
2. Launch the same outdoor save/camera, let compilation settle, capture
   two separate 45-second A windows.
3. Close game/title, apply `tools/gta4-fifo-yield.py os-yield`, relaunch
   the same warmed scene and capture two B windows.
4. Close game/title, apply `control`, relaunch and capture two A-return
   windows. Add another B if the result remains ambiguous.
5. Compare FPS, 1% lows and p95/p99 interval summaries, gameplay speed,
   graphics, sound, input and progress. Check a repeatable driving route
   before adopting any apparent stationary-scene win.

Run helpers from the repository root in WSL. For each capture, use:

```bash
python3 tools/gta4-scheduler-ab.py capture \
  --session results/gta4-fifo-yield-20261030 --mode B \
  --label fifo0061-control-run1 --expected-resolution 150 \
  --expected-tuning rsx_fifo_yield=0 \
  --expected-tuning spu_insert_select=0 \
  --expected-tuning spu_narrow_ls_store=0 \
  --expected-tuning spu_narrow_ls_check=0
```

Here `--mode B` selects the existing **scheduler B**, independently of the
FIFO A/B experiment. Use unique labels and `rsx_fifo_yield=1` for candidate
captures. Reject any capture with nonzero `new_spu_compilations` even if
the tool marks it valid. Window percentiles are not pooled frame percentiles.
Use `tools/gta4-worker-activity.py` on each capture stem for the unchanged
FIFO sample distribution; do not interpret sampled CPU wall time as GPU
completion or an additive per-frame critical path.

After testing, close the title and run `tools/gta4-fifo-yield.py restore`
to restore the exact original tuning file or its absence. Binary rollback
must likewise happen with both game and title stopped. No speedup is
established until matched repeat controls exceed observed scene variation.

## Completed local validation

- Focused host C++ harness compiled/run with and without `__PROSPERO__`:
  default/opt-in dispatch, changed command during yield, pending arguments,
  true-empty/stale-state fallback, mapping/channel changes, original idle
  transition PASS. OS yields are mocked; this does not measure PS5 wake time.
- Actual title-side C parser: key 11, mode 0 default, mode 1 opt-in, invalid
  values, runtime description and deletion rollback PASS.
- Tuning variants preserve other keys, reject duplicate keys and external
  edits, and preserve an absent original file PASS.
- Existing DMA wait/parser and worker activity host checks PASS.
- Patch 0061 replays cleanly on saved exact pre-change 0060 FIFO sources
  and reproduces the build source bytes; reverse apply check PASS.
- Full `JOBS=3 bash tools/wsl-build-latest.sh` completed: 57 core build
  steps, 182 title build steps, native TLS and all nine packaging gates PASS.
- Build log: `/home/callum/work/rsx0061-build-20261030.log`.

Local build pair:

| Artifact | Bytes | SHA256 |
| --- | ---: | --- |
| Signed eboot.bin | 114105438 | `03802ba2770fad58a3859f54291fac1119c712eff23f700b923597ad8242ef89` |
| rpcs3ps5-text.bin (including 28-byte header) | 74604561 | `2914eb59da947339ac5f672b0b19d0c772007c5ea8fa1b29a17b9957021e20f8` |
| Converted eboot.elf | 117429696 | `54e113cc9710ed6cfe8aa98b8bf1cf7d876336a59766589597d6a1af54215b0a` |

## Console installation completed

User explicitly confirmed **both GTA IV and KB-RPCS3 closed**. Installer
process checks passed on staging, activation entry, and immediately before
renames. Both staging and installed readbacks verified executable load/TLS
segments against the converted ELF and the code mirror's exact SHA256.

Live files are now patch0061: decrypted ELF 117429696 bytes, mirror
74604561 bytes. Exact prior patch0060 pair is retained under
`.before-rsx0061-20261030` (117429696 / 74604305 bytes). Older backup chains
remain untouched. Original tuning was absent; initial mode is 0/control.
No game configuration, saves, caches or game data were modified.

Next user action: launch GTA IV, restore the reference stationary outdoor
camera, allow compilation to settle, then say `FIFO control ready`. Take
two 45-second mode-0 captures (`fifo0061-control-run1`, `run2`) with the
expectations above. Only after collecting these controls, close the title,
apply `os-yield`, and collect the candidate and return controls. The initial control and candidate captures are now complete; see the latest handoff above.

Rollback after closing the title: `python3 tools/deploy-gta4-rsx0061.py rollback`
restores the paired 0060 backup and retains 0061 as stage. If tuning was
changed for the experiment, run `python3 tools/gta4-fifo-yield.py restore`
while stopped to restore its exact original absence as well.


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
