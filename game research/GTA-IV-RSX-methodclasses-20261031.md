# GTA IV NPUB30702 — patch 0066 RSX method-address histogram

<!-- latest-state:start -->
**Latest verified GTA IV testing — 2026-10-31:** patch0067 OUTDOOR all-worker host CPU attribution COMPLETE, with guarded rollback PASS. Two 45-second original patch0064 gate0 control runs at the user-positioned lamppost/hydrant: **26.77 / 29.35 FPS** (mean **28.06**). After safely swapping to patch0067 and restarting GTA IV, two 45-second diagnostic runs on the **same physical street**: **28.20 / 29.32 FPS** (mean **28.76**). Different camera, exact Niko position, daylight, traffic and reboot/time conditions; the nominal 0.70FPS difference is **NOT** a demonstrated gain. All four captures valid, scheduler B, 150% resolution, Mega SPU, XFloat Approximate, 100% clocks, cap60, all tuning0, gate0/helper probes0 and **zero new SPU compilations**.

24 exact outdoor ~4s CPU group reports from patch0067, using the console-tested SIGUSR1 self-report monitor, give **SPU 5.4435, PPU 2.2925, main RSX 0.9215, OTHER 0.0845 logical-core equivalents**, total ~8.7367; sampled 6 guest SPU, 18 PPU and 1 main RSX host worker. Historical unmodified control group measurements are TOP14-ONLY lower bounds, not exact. One logical-core equivalent is one host logical thread fully occupied, not a guest frame or physical core. SPU is busiest in aggregate, RSX main nearly saturates one logical core, but no critical path or GPU latency is proven.

**Console NOW:** exact original patch0064 gate0 matched executable and mirror RESTORED and independently verified: ELF load/TLS PASS, exact mirror SHA256 e48a5c75cc3357d7f51474d1ded457e4d27e221c15fde446023538d8f48eda7b PASS. Complete PS5 process listing says GTA IV and launcher both CLOSED. Patch0067 pair retained as .ps5cpu0067-stage (ELF117438656/mirror74608465); patch0065/0066 diagnostic and MFC gate1 stages preserved. Source profile patch count67 but installed game remains original gate0. No saves/config/caches changed. Full paired results: results/gta4-ps5cpu-20261031/ps5cpu0067-outdoor-control-vs-diagnostic-20261031.json. Next: match outdoor camera and measure per-frame PPU/SPU/RSX waiting and critical path, not rely on summed CPU occupancy.
<!-- latest-state:end -->

## Why this test exists

Patch0065 found 305,225 sampled method-bearing FIFO invocations with
636,064 decoded method words and 418,484 direct handlers in two warmed
45-second indoor GTA IV captures. An average of 2.08392 method words
per sampled invocation does not tell us which method registers matter.
Patch0066 adds only a sampled register-address histogram to identify
high-volume groups for the *next* exclusive CPU-cost investigation.

## Source and instrumentation

- `port/rpcs3-latest-patches/0066-PS5-sample-RSX-method-address-class-histogram.patch`
  adds a 256-element counter array in `ps5_rsx_words.h`, keyed by
  `((command.reg & 0xffff) >> 2) >> 6`, corresponding to one 256-byte
  RSX register offset band. Counts one word on decoded methods, one
  handler when `methods[reg]` is actually called. This excludes
  flattener-suppressed words; high-volume bands are not necessarily
  the highest CPU-time contributors.
- It reuses patch0065's sampled invocation selector (1/512); no
  clocks, locks, allocations, guest control changes or per-command
  logging. Relaxed atomic updates occur only in those samples.
  Watchdog drains 256 buckets approximately every four seconds
  and logs totals plus top 12 address groups.
- Top 12 per window is **truncated**: aggregate recorded top groups
  may omit a band in windows where it was not in the top 12. Per
  window totals cover all 256 bins. Sample-phase bias and separate
  watchdog draining mean histogram and FIFO word-count windows may
  not match exactly; neither measures exclusive CPU or GPU time.

## Offline verification

- Exact source before patch0066 saved at
  `/home/callum/work/rsx0066-original-20261031/`.
- `port/tests/check-ps5-rsx-classes.py` PASS: reversible source patch,
  exact bytes reproduced and native Clang++19 tests ON/OFF.
- `port/tests/check-ps5-rsxclasses-parser.py` PASS: synthetic
  rank/total/window tests, malformed records and SPU compilation rejected.
- Build: `JOBS=2 bash tools/wsl-build-latest.sh`, log
  `/home/callum/work/rsx0066-diagnostic-build-20261031.log`,
  full PS5 core/title, native TLS (128/15104/alignment32),
  nine packaging gates PASS.
- Local archive: `/home/callum/work/rsx0066-registerclasses-20261031/`
  with executable, code mirror, matching ELF, compile headers,
  `archive-manifest.json` SHA-256s. Native ELF executable PT_LOAD
  matches the complete mirror payload after its documented 28-byte
  RPCS3PS5TEXT wrapper. MFC gate0 and helper probes0.
- Guarded installer `tools/deploy-gta4-rsx0066.py` pins hashes;
  deployment performed after independent full PS5 process list
  confirmed title/launcher stopped. Staged and readback-verified
  pair then activated; prior exact gate0 backup retained as
  `.before-rsx0066-20261031`. Runtime checks pending.

## Runtime and rollback plan

1. Wait for GTA IV to finish SPU cache; confirm gameplay and
   expected gate0/helper probes0 in live RPCS3 log.
2. Verify PS5 RSXCLASS2 reports nonzero method words and ranked
   RSXCLASS rows. Keep Chiaki Remote Play on as in 0065.
3. Capture two 45-second warmed stationary indoor gameplay
   windows with scheduler B/150%, no new SPU compilation and
   expected tuning flags zero. Do **not** compare indoor capped
   FPS to outdoor uncapped critical-path measurements.
4. Parse top address groups and compare distributions between
   captures; do not infer method handler CPU-time or GPU load.
5. Close title normally, check full process listing, guarded
   rollback and independent full matching gate0 ELF+mirror readback.
6. Record findings in this study plus GTA IV top-level audit and
   latest-state agent guidance. Choose focused next instrumentation.


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


## Related external CPU improvement audit — 2026-10-31

Completed read-only review of the experimental [lavavex/rpcs3-PS5](https://github.com/lavavex/rpcs3-PS5) PS5 port, the [lavavex/rpcs3](https://github.com/lavavex/rpcs3) emulator submodule and 10 identifiable public direct wrapper forks. Full evidence, commit links and code-level applicability: [GTA-IV-lavavex-forks-CPU-audit-20261031.md](GTA-IV-lavavex-forks-CPU-audit-20261031.md).

**No validated GTA IV CPU/FPS optimization to cherry-pick.** Compiler flags `-march=znver2`, `-O3` are already used; current KB upstream includes later RSX state-decode and PPU cache optimizations. Parent CPU overlay thread-time correction is the best *diagnostic* borrowing candidate, but must be validated, not counted as FPS. v0ltfault's FW7.40 executable pool became opt-in and is unrelated to the validated GTA IV frame path. The parent std::mutex self-notify fix does not match KB's `__PROSPERO__` futex path. jmelovich's `/dev/urandom` fix may help other games boot, but is not an FPS optimization.

**Live console was not changed:** patch0064 gate0 control remains installed, earlier stage/backup state intact; no boot, executable swap or benchmark was performed for the external-source review. The next actual performance work remains exact RSX 0x1700-register/value-change frequencies or exclusive dispatch CPU time, with possible validated PPU CPU-time attribution before choosing an optimization.


Patch0067 follow-up completed 2026-10-31: two valid 45s indoor CPU-group captures (PPU1.565, SPU3.855, main RSX0.554, OTHER0.083 logical cores), safely rolled back to verified patch0064 gate0; no FPS win. See GTA-IV-PS5-thread-CPU-groups-20261031.md.


Latest outdoor patch0067 follow-up: gate0 control 28.06FPS vs diagnostic 28.76FPS, scene view and traffic NOT identical, no FPS gain claim. Outdoor exact CPU cores SPU5.4435/PPU2.2925/main RSX0.9215/OTHER0.0845, 4 valid 45s runs with no new SPU compilations. Original gate0 fully restored, title and launcher stopped; see GTA-IV-PS5-thread-CPU-groups-20261031.md.
