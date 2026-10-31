# GTA IV NPUB30702: MFC reservation audit

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

Date: 2026-10-30. Scope: source audit, compiled-baseline inspection and
isolated host proof. No emulator source, selected manifest, build artifact
or console file changed by this audit. Console last verified on lighter0062;
local latest source/manifest still includes0063 helper probes.

## Outcome

**Recommended first candidate: skip reporting-only entry timestamp reads in
do_putllc and do_putlluc when performance reporting is disabled.** Use the
existing disabled perf_meter constructor, then restart only when reporting
is enabled at entry. Limit the proposed port change to PS5 at these two sites.

This removes incidental work without changing reservation reads, comparisons,
locks, writes, version updates, LR events, notifications, queue ordering or
guest-visible status. It is a small throughput candidate, not a demonstrated
FPS gain or an explanation for SPU0x04000100's slower samples. No shortcut
through the reservation protocol is justified by the present evidence.

The candidate is reviewable but **not implemented in production sources**:
`results/gta4-mfc-audit-20261030/candidate-reporting-meter-gate.diff`.
Do not treat this fixture as an applied port patch or deployed build.

## Evidence used

Previous0063 captures established ~2.2M direct native MFC helper calls/s,
SPU0x04000100 sampled MFC means1.54-1.68us versus~0.20-0.29us on others,
and sparse active GETLLAR/PUTLLC/PUTLLUC observations. They did **not**
establish per-command frequencies, exclusive CPU costs or a frame bottleneck.
Probe overhead was a material concern; lighter0062 was restored/verified.
Those experiments are complete and were not repeated for this audit.

Inspected actual WSL source `/home/callum/work/rpcs3-latest`:

- Cell/SPUThread.cpp: process_mfc_cmd, GETLLAR reuse/wait/read loop,
  do_putllc, do_putlluc, do_cell_atomic_128_store and scheduler watchdog.
- Emu/perf_meter.hpp: constructors, copy/reset/restart and destructor.
- Memory/vm_reservation.h and Memory/vm.cpp: reservation stamps, unique
  lock, waiter registration/version recheck and notification protocol.
- RSX/Core/RSXReservationLock.hpp: configuration guards and destructor.
- Emu/system_config.h: dynamic configuration declarations.
- util/tsc.hpp and exact0062 symbol ELF disassembly.

The functions above are relative to `rpcs3/` within that source checkout.
Source HEAD f568df06faacb30cb1a93a64668f55b00d357332 plus existing uncommitted
port work. Source hash and candidate metadata are recorded in
`results/gta4-mfc-audit-20261030/audit-summary.json`.

## Why the timer candidate is narrow

perf_meter's default constructor always calls restart, which reads TSC.
Its destructor checks perf_report only later. In do_putllc, perf0 is copied
to the plus/dot meters and reset according to success/failure; none of these
timestamps feed guest logic. In do_putlluc, perf0 is used only by its reporting
destructor. Full-function use checks found no functional get/restart/push use
at either site. The proposed diff changes only these constructor blocks;
all guest protocol statements remain byte-identical in the isolated fixture.

Exact patch0062 ELF `/home/callum/work/rsx0062-spu-cover-link-20261030.elf`
confirms unconditional entry RDTSC in both compiled functions:

- do_putllc starts0x7c29f0; entry RDTSC at0x7c2a1a.
- do_putlluc starts0x7c36d0; entry RDTSC at0x7c36de.

Disassembly saved in `results/gta4-mfc-audit-20261030/baseline-putll-disassembly.txt`.
When disabled, the proposal removes one entry clock read per do_putllc or
do_putlluc invocation (two when PUTLLUC also invokes PUTLLC). The first config
check adds a branch/read; exact net cost needs target benchmarking. The direct
MFC helper count is not the frequency of these two commands, so no FPS estimate
can be calculated from the existing call totals.

**GETLLAR is excluded.** Its perf0 timestamps drive retry reuse, loop
identification and wait-policy decisions even when reporting is off.
Globally disabling perf_meter or gating that GETLLAR timer would change
execution policy. STORE128 also has explicit get arithmetic; it is outside
the initial two-site candidate and needs a separate use audit if expanded.

## Correctness constraints and rejected/deferred ideas

| Idea | Audit decision |
| --- | --- |
| Remove concurrent_execution_watchdog | Not useful under measured Preferred SPU Threads=0: acquire/release path already inactive. Setting is dynamic; do not hardcode/cache0 for other configurations. |
| Remove RSX reservation lock | Accurate RSX reservation access=false already makes this lock inactive. Keep the dynamic setting supported; no new locking saving established. |
| Collapse GETLLAR double data/version checks | Reject. They detect concurrent changes while reusing/reading128 bytes and preserve LR-event behavior. |
| Treat unchanged PUTLLC as a no-op | Reject. Its reservation CAS/version transition matters even when stored bytes are identical. |
| Skip accurate-reservation writer locks/page-fault checks | Reject without a separate protocol proof. These protect concurrent guest writes, visibility and fault behavior. Keep Accurate SPU Reservations enabled. |
| Drop PUTLLUC fallback/notifications | Reject. Active-reservation reuse, LR handling and notifications for previous reservation versions must remain. |
| Change reservation-table hashing or coalesce waiter buckets | Reject as a local optimisation. Reads/stores/waiters share the protocol; collisions and notification/version rechecks cannot be changed in one caller. |
| Move scan16_rdata after acquiring the unique lock | Defer. It may avoid a scan on failed acquisition, but moves local-store observations and changes lock hold duration. Concurrent local-store access requires separate proof; not the first candidate. |
| Shorten waits/remove check_state or reservation wakeups | Reject from this evidence. CPU occupancy/point observations do not prove unproductive waiting; shutdown/progress and wake races must remain correct. |

## Host proof and its limits

`port/tests/check-ps5-mfc-meter-audit.py <upstream-source>` copies the actual
perf_meter definition to a temporary harness with a counted fake TSC.

- Full-function checks restrict the two audited timers to reporting-only uses.
- Disabled reporting: original shape reads TSC, proposed shape does not.
- Fixed enabled reporting: original/proposed meter sample sequences match for
  PUTLLC success/failure and standalone/nested PUTLLUC shapes.
- Candidate diff applies cleanly in an isolated fixture and changes no guest
  statements outside the two reporting-construction blocks.
- Production source bytes are unchanged by the fixture/proof.

**Dynamic reporting caveat:** perf_report is explicitly dynamic. Enabling it
during an already-running call would produce a meter event in the old code;
the proposed disabled-at-entry meter skips that one in-flight event and starts
with the next invocation. A host test records this difference explicitly.
Guest emulation is unaffected, but the proposal is not bit-identical for all
diagnostic toggling behavior. Accept/document this reporting policy in a real
patch; do not claim the host proof preserves every observable log event.

This is construction/reporting proof, not a full concurrent reservation test,
PS5 candidate build, FPS benchmark or proof of the game's critical path.
No candidate performance improvement or console test is claimed.

## Exact next step

Implement only the two-site PS5 timer gate if proceeding. Compile out0063's
full-rate helper entry probes before any performance comparison. The local
manifest remains63 although the console is0062: rebuilding the current series
without explicitly disabling those probes would reintroduce the confound.

Build a matched baseline and candidate with the same diagnostic policy;
preserve the exact0062 control. Run focused reporting/fault/event/reservation
checks, verify the target assembly really branches around RDTSC when disabled,
then compare warmed same-scene A/B/A plus gameplay correctness on PS5. Keep
all guest synchronization and Accurate SPU Reservations behavior intact.
Only claim a default improvement if the target result exceeds run variation.

If this small candidate has no measurable gain, record that and stop it.
The remaining0x04000100 outlier needs a command mix/contention explanation;
do not repeat broad0063 helper instrumentation or assume all MFC commands
are GETLLAR based on the sparse live snapshots.
