# GTA IV NPUB30702 — patch 0065 sampled RSX method-loop workload

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

## Motivation

Patch0057 sampled the *first* FIFO word per invocation (~71% method,
~27% NOP). But one run_FIFO invocation can dispatch multiple method
words through its do/while loop; first-word classification is not
a count of actual guest register workload. Prior FIFO OS yielding
and MFC meter gating gave no demonstrable FPS gain. This phase
measures missing RSX CPU work rather than tuning it speculatively.

## Diagnostic scope

- Added a 1/512 **method-bearing FIFO invocation** sampler after
  early control/NOP/empty returns in RSXFIFO.cpp. Count do/while
  iterations, direct methods[reg] handler calls and flattener
  suppressed words; one aggregate update per sampled invocation.
- Watchdog emits a ~4s PS5 RSXWORDS row with run samples, words,
  handler calls, flattened skips and maximum method words per run.
  No per-method timestamps, locks, allocation or logging.
- No guest-visible RSX method processing, state transitions, FIFO
  sync_get or scheduling decisions changed. PS5 only; non-PS5
  source path untouched. Compile-time probe can be disabled.
- Samples may be periodically phase-biased. The counts are
  *RSX CPU method-loop work*, not all GPU commands, GPU time,
  complete workload frequency or per-frame critical-path time.
  Flattener-synthetic direct handler calls are not included.

## Build, source and verification

- Durable patch: port/rpcs3-latest-patches/
  0065-PS5-sample-RSX-method-words-per-FIFO-run.patch;
  selected latest patch count now 65.
- Actual WSL source: /home/callum/work/rpcs3-latest.
  Source bytes before the patch preserved at
  /home/callum/work/rsx0065-original-20261031/.
- Native regression port/tests/check-ps5-rsx-words.py PASS:
  reverse-apply isolated patch exactly reconstructs source before
  0065; forward replay identical to edited sources; Clang++19
  C++20 tests pass for both probe=0 and probe=1.
- Full PS5 build log:
  /home/callum/work/rsx0065-diagnostic-build-20261031.log.
  Core compiled, title linked and signed, native TLS verified
  (template128 / memory15104 / align32), 9 package gates PASS.
- Archive: /home/callum/work/rsx0065-methodwords-20261031/
  includes both paired binaries, eboot.elf, exact gate headers
  and archive-manifest.json with SHA256s. Local build explicitly
  pins PS5_MFC_METER_GATE=0, while patch0064 retains default1;
  do not assume that patch replay alone pins diagnostic gate0.
- The rpcs3ps5-text.bin mirror includes a 28-byte
  RPCS3PS5TEXT header before executable PT_LOAD bytes. Validated
  magic/vaddr/size/reserved and full code payload byte-for-byte.
  A naive whole-file match against PT_LOAD initially failed,
  correctly preventing archive approval until header was parsed.
- Guarded installer: tools/deploy-gta4-rsx0065.py with
  --variant diagnostic and stage/status/activate/rollback.
  It checks title and launcher stopped; stages both files,
  verifies hashes and ELF load/TLS, backs up the previous pair
  under .before-rsx0065-20261031 and uses .rsx0065-stage.
  Does not touch user config, saves, caches or game files.

## Runtime plan

1. Gracefully close title using Chiaki PS5 Home, Options > Close
   Game; independently verify completed process list free of
   eboot.bin and rpcs3ps5-launch.elf before staging.
2. Stage/activate after exact readbacks and process rechecks.
   Validate both installed files, stage/backup invariant.
3. Boot GTA IV, verify gate0/probes0 and presence of
   PS5 RSXWORDS rows with nonzero method-run samples.
4. Capture two 45s windows using native RPCS3 log at a documented
   stationary scene, warm and with no new SPU compilation.
   If the save loads in an apartment, label it as indoor, not
   an outdoor A/B FPS test; diagnostic word counts still useful.
5. Close safely and guarded rollback to gate0, verify hashes,
   preserve the result and identify a measured next bottleneck.


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
