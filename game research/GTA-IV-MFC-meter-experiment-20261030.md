# GTA IV NPUB30702: matched MFC reporting-timer experiment

<!-- latest-state:start -->
**Latest verified handoff — 2026-10-31:** patch0066 RSX register-address
histogram diagnostic **COMPLETED, installed/tested/ROLLED BACK**.
Two valid stationary 45s GTA IV NPUB30702 *indoor-apartment* captures
with scheduler B, 150%, Mega SPU, XFloat Approximate, 100% clocks,
60FPS cap, Performance Report OFF, four tuning flags0, Chiaki ON,
MFC compiled gate0 / helper probes0 and **zero new SPU compilations**.
Across both: **660,003 sampled method-loop words** and **435,865
direct handlers** (1/512 method-bearing run_FIFO calls sampled);
top-12 address bands cover **98.77%** of sampled words. Most active:
**0x1800–0x18FF** 124,359 words/116,211 handlers (draw, other state);
**0x1700–0x17FF** 107,352 words/**only 62** direct handlers
(vertex-array format/state, other registers);
**0x1600–0x16FF** 83,651 words/83,651 handlers
(vertex-array offset range); and **0x1A00–0x1AFF**
69,730 words/69,730 handlers (texture-state range).
Symbols are *range examples*, not proof of specific hot registers.
Samples have periodic/phase bias, top12 truncation and watchdog
boundary uncertainty; CPU-exclusive cost and GPU runtime remain
unknown. The indoor scene was capped at ~60 FPS; **NO FPS
improvement can be claimed** and do not compare to outdoor baseline.

**Console now:** exact earlier **patch0064 gate0 control** restored
after guarded patch0066 rollback; independently downloaded full
ELF load/TLS and mirror SHA256
`e48a5c75cc3357d7f51474d1ded457e4d27e221c15fde446023538d8f48eda7b`
PASS. Independent complete PS5 process listing confirms **GTA IV
and launcher stopped**. Diagnostic0066 pair preserved in
`.rsx0066-stage`; diagnostic0065 still in `.rsx0065-stage`,
and compiled MFC gate1 candidate in `.mfc0064-candidate-stage`.
Saves/config/caches unchanged. Full diagnostic:
`results/gta4-rsx-classes-20261031/rsx0066-indoor-combined.json`.

**NEXT:** narrowly sample exact 0x1700-range register frequencies,
changed-versus-unchanged writes and possibly batch/set state cost;
alternatively sample **exclusive** CPU time of method handlers
associated with 0x1800/0x1600/0x1A00. No optimisation should
bypass RSX semantics based only on packet counts. Do not repeat
patch0064 gate1 or FIFO-yield negative experiments; any future
deployment requires new stopped-process checks.
<!-- latest-state:end -->

Date: 2026-10-30. Patch0064 on latest profile; implementation and two local
builds complete. Matched control installed/verified; runtime comparison pending.

## Change and experimental control

User authorised implementing the audited two-site change and testing it.
`do_putllc` and `do_putlluc` use disabled perf_meter construction when
performance reporting is off, restarting only if enabled at entry.
GETLLAR functional timestamps and all reservation protocol statements stay
unchanged. Non-PS5 behavior remains unchanged. Dynamic reporting enable
mid-call begins measurement with the next invocation, as documented in audit.

`PS5_MFC_METER_GATE` is a compile-time switch in
`rpcs3/Emu/Cell/ps5_mfc_meter.h`. Control=0 retains original constructors;
candidate=1 applies the gate. The durable patch defaults to candidate1.
Control was built/archived first with header0, then the same header changed
to1 for candidate. Archived headers differ only in that value; source and
toolchain otherwise shared. No runtime tuning lookup was added to this path.

`PS5_SPU_HELPER_ACTIVE` defaults to0: helper entry/exit/escape/observation
functions compile to no-ops and helper watchdog logging is compiled out.
Low-rate0062 SPU gateway/cpu_work coverage and RSX sampling remain identical
in both versions. Native helper semantic tests passed with diagnostics ON,
non-PS5 bodies, and PS5 diagnostics OFF; OFF adds no wrapper probe clocks or
counter activity. Both binaries omit SPUHELP/SPUHELPSTAT and older heavy PERF/
PROFILE markers. FRAMEDEP's format string remains in both and known0062,
but its source enabled flag remains false and earlier live captures had no
events: string presence alone is not execution. The tracer was not changed.

Boot marker: `PS5 MFCMETER: gate <0|1> helper_probes 0`.
`tools/gta4-scheduler-ab.py --expected-mfc-meter-gate N` verifies this marker,
Performance Report=false and no helper output. Wrong/missing mode, reporting
enabled and active helper logs are rejected. Existing checks still validate
scheduler, resolution, clock speed, patches and SPU tuning. Reject any run
with new SPU compilation even if the capture tool marks it valid.

## Completed local validation

- `check-ps5-mfc-meter.py`: compiles the actual constructor blocks and actual
  perf_meter definition for control, candidate and non-PS5. TSC counts and
  named reporting events pass for reporting ON/OFF, success/failure and nested
  PUTLLUC/PUTLLC shapes. Removing the two gates/include reproduces the complete
  pre-change SPUThread source, proving no other guest/protocol text changed.
- `check-ps5-spu-helpers.py`: ten actual native helper bodies in all three
  configurations pass; source returns/state, nonlocal escape, opt-in probes
  and default-OFF no-clock/no-counter behavior verified.
- Existing worker counter/coverage test PASS. New capture-mode guard tests PASS.
- Both full PS5 builds PASS: core/title, native TLS and all nine package gates.
- Both code mirrors verified byte-for-byte against their converted ELF's
  executable load segment; artifacts hashed and immutable archives retained.
- Exact target assembly: control reads RDTSC unconditionally at both entries;
  candidate checks perf_report and branches past RDTSC in both. Disassemblies
  and guard addresses saved in results/build record.
- Patch0064 reverse check and isolated replay reproduce all four actual
  candidate source files, including the new config header, PASS.

No full guest fault/concurrent-reservation runtime test or FPS improvement is
claimed by these host/source checks. In-game correctness and performance
comparison remain required. The gate changes only reporting construction.

## Local artifacts

| Variant | Signed eboot bytes / SHA256 | Mirror bytes / SHA256 |
| --- | --- | --- |
| Control0 | 114106750 / `20ca8f1125aea184dcf57d4c21974cb5c1ab85eb0162a0653701140422924e42` | 74605201 / `e48a5c75cc3357d7f51474d1ded457e4d27e221c15fde446023538d8f48eda7b` |
| Candidate1 | 114106878 / `3a1b1a9a54713c9613f99174b7625332ca3d96e8a6965972e99565e7afaf0927` | 74605329 / `67932ee98595f873c381e61cb7e4409ffc17c0bf61f7a4e0ebe261019241ed8a` |

Both converted ELFs are117434056 bytes, with different hashes recorded in
`results/gta4-mfc-meter-20261030/builds.json`. Archives include signed file,
mirror, converted ELF, symbol ELF and exact config header:

- `/home/callum/work/mfc0064-control-20261030`.
- `/home/callum/work/mfc0064-candidate-20261030`.

Build logs: `/home/callum/work/mfc0064-{control,candidate}-build-20261030.log`.
Actual source: Ubuntu-24.04 `/home/callum/work/rpcs3-latest` as callum.
Windows emulator checkout untouched. Earlier workspace/core work preserved.
Selected latest profile now64 patches; established series unchanged.
Core patch: `0064-PS5-gate-PUTLL-meters-disable-heavy-helper-probes.patch`.

## Deployment and next action

Hash-pinned paired installer: `tools/deploy-gta4-mfc0064.py`, requires
`--variant control` or `--variant candidate`. Each selects its immutable
archive, hash set, converted ELF and independent stage/backup suffix.
It checks actual stopped processes and verifies staged/preactivation/live
decrypted load/TLS segments and exact mirror hashes.

Read-only status still matches installed0062 (ELF117434056/mirror74605073),
no0064-control stage/backup. Original tuning was absent; do not modify it,
game configs, saves or caches. Fresh closure confirmation is required before
the installer process check permits binary changes. No console writes yet.

1. User closes GTA IV and KB-RPCS3. Stage/activate **control** first.
2. User launches same warmed stationary outdoor scene and replies
   `MFC control ready`. Capture two45s runs, labels `mfc0064-control-run1/2`,
   in `results/gta4-mfc-meter-20261030`, scheduler B/150%, all four tuning
   flags0, `--expected-mfc-meter-gate 0`. Performance Report must be OFF.
3. After closure/process checks, stage/activate **candidate**. Capture two
   same-scene windows with gate1 and unique candidate labels.
4. After closure/process checks, candidate rollback restores the exact
   matched control; capture two return-control windows for A/B/A.
5. Compare FPS, 1% lows and frame-time summaries, plus visual/audio/input/
   gameplay correctness. Window percentiles are not pooled frame percentiles.
   No command-frequency histogram exists, so no advance FPS estimate.

Control installation preserves0062 as `.before-mfc0064-control-20261030`.
Candidate preserves matched control as `.before-mfc0064-candidate-20261030`.
Candidate rollback restores control and retains candidate as its stage;
control rollback can subsequently restore0062. Old0063 stage/backups remain
untouched. Never rename/overwrite executable pairs while the title runs.

If there is no repeatable gain beyond scene variation, record and stop this
candidate. Do not repeat earlier broad helper/FIFO experiments as a substitute.


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
