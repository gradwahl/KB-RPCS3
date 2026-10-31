# GTA IV NPUB30702: native SPU LLVM helper boundaries

<!-- latest-state:start -->
**Latest handoff (2026-10-30): MFC source audit COMPLETE.** Recommended first
small candidate: gate reporting-only entry perf_meter timestamps in do_putllc
and do_putlluc when perf_report is off. Compiled0062 entry RDTSC confirmed;
actual-meter host proof PASS. GETLLAR functional timestamps and all guest
reservation checks/locks/events/notifications must stay. Reviewable candidate
diff exists only in ignored audit results; no production patch/build/deploy
performed and no FPS gain claimed. Dynamic mid-call reporting enable drops
one in-flight diagnostic event under the proposal; documented/tested.
Console last verified lighter0062, tuning absent. Local source/manifest still63:
compile out helper probes before any matched performance candidate. Next:
implement narrow timer gate, build/prove, then controlled PS5 validation.
See [MFC reservation audit](GTA-IV-MFC-reservation-audit-20261030.md).
<!-- latest-state:end -->

Date: 2026-10-30. Latest profile patch0063 on top of verified patch0062.
Status: local and on-console helper checks complete; findings recorded.
Lighter patch0062 restored and independently verified; no FPS gain claimed.

## Why this is the next measurement

Patch0062 verified six long-lived SPU gateways, total entry counts 4-51,
and zero accepted cpu_work entries. The old missing-coverage problem is
resolved. Gateway age includes guest JIT, native helpers, waits and OS
descheduling; it cannot identify which work holds up GTA IV frames.
Do not repeat the completed FIFO direct-yield experiment (no useful gain)
or blindly add more probes to the unvisited cpu_work pending-work path.

Source tracing found a dedicated `wait_on_spu_channel` native lambda that
bypasses exec_rdch, plus multiple native MFC paths. Instrumenting just the
two originally named functions would omit relevant channel/MFC work.

## Scope and recorded fields

Core patch: `port/rpcs3-latest-patches/0063-PS5-observe-SPU-LLVM-helper-boundaries.patch`.
Actual source is Ubuntu-24.04 `/home/callum/work/rpcs3-latest`, user callum.
Windows emulator source checkout untouched. Selected manifest now 63 patches;
established profile unchanged. Previous workspace/core edits preserved.

Ten native LLVM helper bodies are instrumented without changing generated
guest IR or guest fast paths:

| Kind | Native boundary | Live argument |
| --- | --- | --- |
| 0 rdch | exec_rdch (also mailbox/event read wrappers) | Channel number |
| 1 wrch | exec_wrch | Channel number |
| 2 mfc_cmd | exec_mfc_cmd, saveable and non-saveable | MFC command byte |
| 3 channel_wait | wait_on_spu_channel lambda | 1 read / 0 write |
| 4 rchcnt | exec_rchcnt | Channel number |
| 5 events | exec_get_events | Event mask |
| 6 read_dec | exec_read_dec | 0 |
| 7 list_unstall | exec_list_unstall | Tag |
| 8 stop | exec_stop | Stop code |
| 9 queued_mfc | Shuffled MFC queue-processing lambda | 0 |

Each outer measured native helper publishes kind, argument and start TSC.
Entry/return counts are cumulative. The first outer invocation of each
kind per SPU and every 1024th thereafter gets a completed duration sample.
Normal-return and escaped samples have separate counters. At gateway return,
an outstanding helper is recorded as a nonlocal escape, not a normal return.
No destructor cleanup is relied on across g_escape's stack restoration.
Nested measured helpers are suppressed and counted; their work remains
inclusive in the outer helper. This is not an exclusive nested profiler.

`PS5 SPUHELP: v1` is emitted once per registered SPU per watchdog report:
active, stable, kind, arg, age_us, nested. Start is checked before/after
reading metadata; changing snapshots are marked unstable. Watchdog phase
observations are sparse samples, **not time fractions or CPU utilisation**.
Outside the measured helpers is **unresolved**, not pure guest JIT: other
native helpers, waits and descheduling can still occur there.

`PS5 SPUHELPSTAT: v1` reports cumulative per-kind entries, returns, escapes,
and separate normal/escape sampled counts, sums and lifetime maxima.
Never sum cumulative watchdog rows. Report-to-report deltas are used for
sample means, and can include a long interval that began before capture.
There is no GPU/frame timing or full SPU job dependency graph here.

All helper entries add a cached ID lookup, an entry atomic increment,
TSC read and a few atomic stores. Normal exit adds an atomic return count;
only selected samples read the exit TSC and update duration counters.
No per-instruction probes, per-call logs, new sleeps, signals or locks.
Instrumentation overhead is real and remains to be measured on console;
do not claim an FPS improvement or zero cost from a diagnostic-only build.
Existing 0062 live gateway coverage, RSX sampler and default tuning remain.

## Completed local proof

- Compiled the ten actual native helper bodies in a host harness with PS5
  probes enabled and disabled. Original return values, channel/MFC actions,
  stop PC increment, unsavable state and read-dec wait behavior PASS.
- Real setjmp/longjmp escape tests bypass end_helper, then explicit gateway
  cleanup clears live state and records separate escaped samples PASS.
- First/1024 sampling, live kind/argument/age, nesting suppression and
  null/invalid-kind guards PASS. Existing two-TU gateway coverage test PASS.
- Helper parser tests cover inside/outside/unstable observations, live-only
  long calls, cumulative deltas, normal/escape separation, missing legacy
  reports, invalid kinds and counter reset rejection PASS.
- Existing coverage parser tests PASS; regression parsing of eight earlier
  FIFO/SPU captures retains their original measured fields and raw evidence.
- Isolated patch replay reproduces the three actual build sources byte for
  byte; reverse apply check PASS.
- Full `JOBS=3 bash tools/wsl-build-latest.sh` PASS, including SPULLVM,
  SPUThread, RSXThread, frontend, native TLS and all nine package gates.
  TLS template 128 bytes, memory 15120 bytes, alignment 32 verified.

Tools/tests: `tools/gta4-spu-helpers.py`, `tools/gta4-worker-activity.py`,
`port/tests/check-ps5-spu-helpers.py`, `port/tests/check-ps5-spu-helper-parser.py`.
Worker parser retains legacy outputs and now exposes its log time bounds
so both parsers use the same measurement interval.

## Verified local package and rollback

| Artifact | Bytes | SHA256 |
| --- | ---: | --- |
| Signed eboot.bin | 114114254 | `ff517155d3dafd76add414f0fbe3f6c497ec2f165e9f7abbfca1d76ef738e1b1` |
| Code mirror including header | 74611793 | `8ef00a6f9a4cece63e4de693c667b7921ac2fa5325b46758307f09ade63b8fca` |
| Converted eboot.elf | 117434488 | `ce48a60743edba91ef0a91ecd25287e62f343cb0a176d715d21857767baf893a` |

Build log: `/home/callum/work/rsx0063-build-20261030.log`.
Symbol ELF: `/home/callum/work/rsx0063-spu-helpers-link-20261030.elf`.
Exact prior 0062 signed/mirror/converted control preserved before rebuilding:
`/home/callum/work/rsx0062-control-20261030`, hashes checked against 0062 record.
Machine record: `results/gta4-spu-helpers-20261030/build.json`.
Hash-pinned paired installer: `tools/deploy-gta4-rsx0063.py`.
Process checks and staged/installed decrypted-ELF load/TLS plus exact mirror
readback are required; prior pair is retained as `.before-rsx0063-20261030`.

## Current console and exact next step

Read-only status still matches installed 0062 (117434056 / 74605073 bytes).
No 0063 stage/backup exists. Console was running at the last capture;
user has not yet confirmed closure for this new installation. Original
tuning file remains absent: FIFO0 and SPU experiments OFF. Older backups,
configs, game files, saves and caches preserved; no console writes yet.

After fresh user confirmation that GTA IV and KB-RPCS3 are both closed,
stage/activate with independent process checks. User launches the same
warmed stationary outdoor camera at B / Mega / Approximate / 150% / 100%
clocks / 60 cap, then replies `SPU helper ready`. Capture two 45s runs
with labels `spu-helpers0063-run1`, `run2`, expecting all four tuning flags
0 and no new SPU compilation. Run both worker and helper parsers on each
capture stem. Inspect actual helper entries/deltas, sampled normal/escape
durations, active helper kinds/arguments, nested suppression and unstable
observations. Do not convert point observations into runtime percentages.
Record findings before selecting a specific optimisation or another probe.


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
