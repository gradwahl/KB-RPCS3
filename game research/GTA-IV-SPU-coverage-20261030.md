# GTA IV NPUB30702: repair missing SPU timing coverage

<!-- latest-state:start -->
**Latest handoff (2026-10-30): helper measurement COMPLETE; console restored
and verified to lighter patch0062.** Two valid0063 captures:23.40/23.18 FPS,
zero SPU compilation/errors. Direct MFC helper calls ~2.2M/s; SPU0x04000100
sampled MFC means1.54-1.68us versus~0.20-0.29us others. Native MFC reservation
handling is the next source-audit lead, not a proven frame bottleneck.
Detailed probes may cost FPS; no causal overhead percentage established.
After fresh closure/process check, restored0062 live pair independently
matched its archived ELF/TLS/mirror. Tuning absent (FIFO0/SPU experiments OFF).
0063 retained as stage; local source/manifest still63: compile out helper
probes before any performance candidate. No more broad helper captures needed.
Next: audit process_mfc_cmd GETLLAR/PUTLLC/PUTLLUC and command mix; preserve
synchronization. See [helper findings](GTA-IV-SPU-helper-boundaries-20261030.md)
and `results/gta4-spu-helpers-20261030/spu-helpers-0063-combined.json`.
<!-- latest-state:end -->

Date: 2026-10-30. Selected latest profile: patch0062 on top of 0061.
Status: host checks, full PS5 build, native TLS and all nine package gates
PASS. Patch0062 installed and live gateway coverage verified in two valid PS5 captures.

## Evidence and confirmed instrumentation defect

Patch0060/0061 produced valid RSX samples but no SPU completed interval
samples in GTA IV, despite high SPU host thread CPU occupancy. The FIFO
direct-yield A/B/A experiment is complete with no demonstrated useful gain;
do not repeat it as part of this task.

The old probe skipped the first 255 native JIT gateway invocations and only
published a selected invocation after it returned. Registered slots with
zero completed samples were silently omitted by the watchdog. A single
long-lived gateway therefore could execute throughout a capture without
reporting anything. This blind spot is confirmed by source and a host test.
Whether it explains the exact console run is not yet proved: previously
there were no entry/return/live counters to distinguish that case from
registration failure, too few calls or an unvisited path.

`cpu_work()` is a specific pending-work path, not all SPU execution. Its old
sample phase depended on the existing emulator iteration counter. Missing
cpu_work durations did not prove idle SPUs or a slow helper. The new
first-call sample and accepted-entry counter remove that ambiguity.

`spu_runtime::g_escape` restores the native stack and returns through the
gateway epilogue without normal C++ unwinding. A destructor-based helper
timer would be unsafe as the sole cleanup mechanism. The fix uses explicit
boundaries, records normal cpu_work completion before its final escape, and
discards a still-active cpu_work sample when the gateway returns.

## Change and interpretation

Core patch: `port/rpcs3-latest-patches/0062-PS5-report-live-SPU-gateway-coverage.patch`.
Actual source: `/home/callum/work/rpcs3-latest` in WSL Ubuntu-24.04 as callum.
Windows emulator checkout untouched. Selected manifest has 62 patches;
established profile unchanged. Existing source/workspace edits preserved.

The existing watchdog now emits `PS5 SPUCOVER: v2` for every registered
slot even when no completed durations exist:

| Field | Meaning |
| --- | --- |
| tasks / jit_tasks | Cumulative entries to SPU cpu_task, including JIT selection |
| gateway_entries / gateway_returns | Cumulative native JIT gateway boundaries, including the first |
| gateway_active / gateway_age_us | Current invocation observed in progress; inclusive live wall age |
| cpu_work_entries | Accepted cpu_work calls after its recursion guard; not guest instructions |
| cpu_work_sample_active / cpu_work_sample_age_us | In-progress selected cpu_work interval, inclusive live wall age |
| cpu_work_abandoned | Selected intervals bypassed by a nonlocal escape, discarded at gateway return |

Zero-ID registration attempts have a separate `PS5 SPUCOVER2` diagnostic;
existing slot-overflow reporting is retained. Unused registrations remain
visible instead of masquerading as absent instrumentation.

Completed gateway durations are measured for every native gateway call,
**not every guest JIT block/instruction**. CPU-work timings select the first
accepted call and every 1024th thereafter. That path adds one relaxed atomic
entry increment per accepted call, uses cached slot resolution and reads
the TSC only for selected samples. Gateway boundaries use TSC reads and
atomics; no new per-instruction logging, signals, sleeps or locks. Added
diagnostic overhead must still be measured on PS5; no zero-overhead claim.

The RSX 1/512 sampler is unchanged. Heavy interrupt profiling and old
frame-event tracing remain disabled. No guest execution, SPU LLVM codegen,
DMA/channel semantics, scheduler or FIFO tuning behavior changed.

These counts/ages are approximate atomic snapshots, not a transactional
frame timeline. Never sum cumulative counts or growing live ages across
watchdog windows. Live age includes nested helpers, waits, descheduling and
guest work; it is not productive CPU time or an exclusive JIT/helper split.

`tools/gta4-worker-activity.py` distinguishes:

- `spu_completed_timing_valid` (and legacy `spu_measurement_valid`): completed intervals exist.
- `spu_live_coverage_valid`: entry coverage exists without zero-ID/overflow errors in the capture window.
- `spu_coverage`: last cumulative values, report-to-report deltas, active observations and maximum ages per ID.

Patch0062 completed gateway sampling is labelled 1/1; legacy logs retain
1/256. A live-only gateway is reported as such, with no fabricated completed
sample or CPU-busy percentage. No coverage still produces an explicit warning.

## Validation completed so far

- Host C++ tests: shared state across two translation units, first long-lived
  gateway visible with no return, normal completion, first/1024th cpu_work
  sampling, live helper age, simulated nonlocal escape cleanup, null slots,
  zero-ID registration and existing counter/overflow behavior PASS.
- Parser synthetic tests: live-only gateway, cumulative counts/maximum age,
  completed samples, legacy sample rate, registration errors and missing
  data PASS.
- Regression parse of all six patch0061 A/B/A captures retains exact FPS,
  worker timings and validity flags; raw records unchanged.
- Three affected PS5 translation units compiled: SPUThread, RSXThread,
  ps5_frontend. Full build log: `/home/callum/work/rsx0062-build-20261030.log`.

Exact patch0061 signed executable, mirror and converted ELF were preserved
before rebuilding in `/home/callum/work/rsx0061-control-20261030`; hashes
match the recorded installed build. All older rollback chains remain intact.

## Next action and console state

Patch0061 remains installed and was running after the completed FIFO
captures. Original tuning file absence is restored, so rsx_fifo_yield=0
and SPU experiments OFF. Do not modify console executables while running.

Finish full build/package verification and prepare a hash-pinned paired
0062 installer. Only after the user closes GTA IV and KB-RPCS3 and the
installer independently verifies both stopped may the pair be replaced.
Then boot the same warmed outdoor scene at B/Mega/Approximate/150%/100%
clocks/60 cap and capture two 45-second windows. Check SPUCOVER records,
entries vs returns, live gateway/helper ages, zero IDs, slot overflow,
completed samples and FPS. Reject compilation-heavy windows. Report
whether the long-lived-gateway explanation is supported before selecting
any SPU optimisation. This is a measurement fix, not an FPS optimisation.


## Full package ready locally

Full latest-profile build completed successfully. Native TLS verified:
128-byte template, 15104-byte memory, 32-byte alignment. All nine packaging
gates PASS. Linked ELF has one shared `ps5_worker_activity::spu` array
(address 0x6cee6c0), consistent with the two-translation-unit host proof.
Isolated patch replay against exact pre-0062 snapshots reproduces all
three actual build sources byte-for-byte; reverse apply check also PASS.

| Local artifact | Bytes | SHA256 |
| --- | ---: | --- |
| Signed eboot.bin | 114106558 | `d293d74636aa6e7cf19876d086a8ca98cf666999c8010771ded7cff7f3691644` |
| Code mirror including header | 74605073 | `5430f413e0574d082fa71add8e6b40dcf2a1a6bf714212f77469e5883d8a0d60` |
| Converted eboot.elf | 117434056 | `cbf1d625e97d9800de23bbb2cc31daef0a06135a5884d24b8ecf922222eff8a4` |

Hash-pinned paired installer: `tools/deploy-gta4-rsx0062.py`.
It checks actual processes before staging/activation/rollback, verifies
staged and installed decrypted ELF load/TLS segments and exact mirror hash,
and preserves the current 0061 pair as `*.before-rsx0062-20261030`.
Build record: `results/gta4-spu-coverage-20261030/build.json`.
Symbol ELF archived at `/home/callum/work/rsx0062-spu-cover-link-20261030.elf`.

Next: user closes both GTA IV and KB-RPCS3, then stage/activate after
independent process checks. No new closure confirmation has been received
for patch0062 at the time of this local-build record. No console writes yet.


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
