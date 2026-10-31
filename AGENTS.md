# KB-RPCS3 agent guide — automated console test loop

Read the workspace-level `../AGENTS.md` first. This guide applies to this
repository and overrides no PS5 safety constraints. Never assume a game
is closed or a build installed merely because the PS5 Home screen appears.

## Agent workflow for authorized game testing

Use the connected Local File Editor tools (Windows workspace) plus WSL
Ubuntu-24.04 (`callum` user) for builds/captures. Prefer finishing the
edit/build/deploy/launch/measure/record cycle in the same active session
instead of asking the user to press every button or upload screenshots.
Neither the shell tools nor Chiaki run independently after the turn ends.

1. **Read the game state first.** Consult `game research/` (especially the
   newest experiment latest-state block), the build profile, and `tools/`.
   Inspect `git status --short` to preserve existing uncommitted changes.
   Verify the *actual* WSL core source tree being built; Windows `../rpcs3`
   sources are not automatically the WSL build sources.
2. **Build, pin, validate.** Use the selected `WSL_BUILD.md`,
   `BUILDING.md` and current profile. Run relevant `port/tests/` checks,
   target/package checks, TLS and code-mirror checks; save build hashes.
   Keep old executable/mirror pair and game data untouched until ready.
3. **Verify stopped processes before changing live binaries.** Use the
   complete PS5 process-list payload `tools/pskill/pslist.elf` over the
   configured payload connection (currently 192.168.0.137:9021). Require
   its `pskill: done` sentinel and no `eboot.bin` or
   `rpcs3ps5-launch.elf` entries. This payload is configured as a listing
   helper; inspect any altered tool/flags before invoking. Independently
   recheck immediately before activation. If the title or launcher is
   running, DO NOT overwrite or rename their live files. Returning to
   PS5 Home using Chiaki does not terminate either process. Try the
   normal UI close flow only if safely possible and in user-authorized
   scope; otherwise ask for a clean exit. No forced termination by default.
4. **Stage and verify deployment.** Use the current, game's guarded
   installer (not a generic bulk FTP overwrite). Pin archive checksums,
   stage both `eboot.bin` and `rpcs3ps5-text.bin`, independently reread
   staged artifacts (ELF load/TLS may differ from a signed SELF's raw
   bytes), preserve a complete prior matched pair, and activate only
   after all checks. Recheck process list before the swap and validate
   both installed files/backups afterward. Do not alter saves, caches,
   config or patches unless explicitly part of the approved experiment.
   On failed transfer or unexpected stage disappearance, stop/recover
   with validated backups; do not mix build variants.
5. **Start the game via Chiaki where supported.** Read
   `../chiaki-ng/AGENTS.md`; capture a current PS5 screen and use the
   helper's one-shot `ps_hold`, D-pad, `cross`, `circle`, `options` and
   bounded left-stick controls to reach
   the correct tile and game. Screenshot after meaningful transitions.
   These tools require a running visible Chiaki Remote Play session; they
   do not start Remote Play. X/Circle are implemented but have not yet
   been validated live. Do not guess through unknown menus or launch
   unrelated tiles. If setting up the test scene cannot be automated,
   request user input for only that step, then resume.
6. **Capture from the console, not from the Chiaki overlay.** For GTA IV
   `NPUB30702`, `tools/gta4-scheduler-ab.py capture` measures log-based
   FPS/frame-time data. Verify runtime configuration, compiled gate,
   settings and patches; mark runs invalid on new SPU compilation,
   unexpected speed, log restart or missing markers. Compare matched
   stationary/warmed scenes and A/B/A controls. Chiaki is for visual
   correctness/navigation; Remote Play overhead requires matched
   conditions before comparison to no-stream FPS baselines.
7. **Record the outcome** in relevant `game research/` files, with
   attempt/results JSON and log paths, build hashes, backups, active
   variant, observed screen/boot state, performance values, failures,
   rollback, and exact next action. Preserve negative/inconclusive runs.

## Completed GTA IV patch 0064 A/B/A (historical example; verify latest state)

- Research: `game research/GTA-IV-MFC-meter-experiment-20261030.md`,
  `game research/GTA-IV-performance-audit-20261030.md`, and
  `results/gta4-mfc-meter-20261030/builds.json`.
- Latest verified installation after final capture (2026-10-31): matched
  **gate0 control**, helper probes0; GTA IV was still running outdoors.
  Gate1 candidate is retained as a PS5 staged pair. A/B/A means:
  original gate0 **23.42 FPS**, candidate gate1 **24.925 FPS**, return
  gate0 **27.54 FPS**, two valid 45s runs in each phase; no new SPU
  compilations. No supported speedup claim due to Remote Play/scene
  and reboot/time drift. Do not revert to gate1 as an optimization.
- Guarded deployment: `tools/deploy-gta4-mfc0064.py` with
  `stage`, `activate`, `status`, `rollback`, and explicit
  `--variant candidate` or `--variant control`. It performs independent
  stopped-process checks and paired artifact readbacks.
- Historical capture command: `tools/gta4-scheduler-ab.py capture`
  with `--session results/gta4-mfc-meter-20261030 --mode B`,
  a fresh `--label`, `--expected-resolution 150`, and
  `--expected-mfc-meter-gate 0` for installed gate0 or `1` for
  gate1. Repeated `--expected-tuning` values were
  `rsx_fifo_yield=0`, `spu_insert_select=0`,
  `spu_narrow_ls_store=0`, `spu_narrow_ls_check=0`.
  **Do not repeat this completed experiment by default.**
- Expected other conditions: scheduler RPCS3 Scheduler, SPU Mega,
  XFloat Approximate, 100% clocks, 60 FPS limit, Performance Report OFF.
  Each recorded phase has two 45-second warmed outdoor captures.
- Results and caveats: `results/gta4-mfc-meter-20261030/comparison-0064-aba.json`
  and the current game research handoff. Never claim an MFC gate1
  performance gain from these measurements; Remote Play and visual scene
  differences impair causal comparability.

## Latest verified GTA IV follow-up — patch0065 diagnostic (2026-10-31)

Patch0065 was selected in `port/rpcs3-latest.json` (patch count65),
implemented as sampled RSX CPU method-loop counters, compiled with
local MFC gate0/probe1 and verified in a complete PS5 build.
Two valid 45s stationary **indoor apartment** runs (Chiaki ON) found
305,225 sampled method-bearing run_FIFO calls, 636,064 loop words
and 418,484 direct handler calls (2.08392 and 1.37107 per sample),
no new SPU compilations. This is diagnostic, not an FPS gain:
the indoor scene reaches the 60FPS cap and is not the former outdoor
baseline. See `game research/GTA-IV-RSX-methodwords-20261031.md` and
`results/gta4-rsx-words-20261031/rsx0065-indoor-combined.json`.

**Current installed build:** restored patch0064 matched gate0
control. Independent native ELF load/TLS and code-mirror hash
verification PASS after guarded patch0065 rollback. The patch0065
pair is staged at `.rsx0065-stage`; older gate1 patch0064 stage
still present. Console process list complete and title/launcher
**both stopped**. Next work should measure RSX method/register
class distribution or exclusive dispatch CPU time, not blindly
repeat unsuccessful MFC or FIFO-yield candidates. Never swap
live executables before fresh process-list checks.

## Console tools and addresses

- FTP (deployment/logs): `192.168.0.137:2121`,
  title root `/data/homebrew/PPSA99303` (confirm before changes).
- Process-list payload: `tools/pskill/pslist.elf` via port `9021`.
- Chiaki Windows side: `../chiaki-ng/mcp-bridge/`; controller disabled
  by default. Only launch its opt-in single-action helper for a
  user-authorized test action. See sibling README for the exact commands.
- Do not commit generated screenshots, private console data, signed
  artifacts, account credentials or benchmark caches without an
  explicit appropriate request.


## Latest GTA IV patch0066 RSX method-class diagnostic (2026-10-31)

After completed negative MFC gate0064 A/B/A and RSX method-word
diagnostic0065, a diagnostic-only patch0066 sampled 1/512
method-bearing FIFO invocations and classified actual register
offsets in 256-byte buckets. Two valid 45s GTA IV **indoor**
captures found 660,003 sampled words/435,865 direct handlers
with zero new SPU compilations. Top 12 buckets cover 98.77%.
The 0x1700–0x17FF band had 107,352 words but only 62 direct
handlers; 0x1800–0x18FF had 124,359 words/116,211 handlers;
0x1600–0x16FF had 83,651/83,651, and 0x1A00–0x1AFF
69,730/69,730. gcm_enums.h maps these ranges to vertex array
format/offset, draw and texture-related registers, but no
individual hot register or exclusive CPU cost is yet measured.
Indoor workload hit the 60 FPS cap: **no optimization or outdoor
FPS gain is claimed**.

Patch0066 was built, validated, safely deployed/tested and
**rolled back**. Exact patch0064 **gate0 control currently live**;
independent full ELF load/TLS + mirror SHA256 verified. Complete
PS5 process listing shows both game and launcher **closed**.
Diagnostic0066 remains in `.rsx0066-stage`, 0065 in
`.rsx0065-stage`, and MFC gate1 in `.mfc0064-candidate-stage`.
Never touch the live executable until independently re-verifying
both processes are stopped. Detailed handoff:
`KB-RPCS3/game research/GTA-IV-RSX-methodclasses-20261031.md`
and `KB-RPCS3/results/gta4-rsx-classes-20261031/`.
Next: exact 0x1700-range register frequency/value-change samples
or narrowly sampled **exclusive** CPU handler costs for draw,
vertex and texture bands. Do not repeat the negative MFC/Yield
experiments or infer CPU bottleneck from traffic counts alone.


## External fork audit: no GTA IV FPS speedup found (2026-10-31)

Read `game research/GTA-IV-lavavex-forks-CPU-audit-20261031.md` before considering code from `lavavex/rpcs3-PS5` or its forks. The wrapper contains scripts while real CPU code is in `lavavex/rpcs3:ps5`, based on an older upstream revision. Ten identifiable public direct wrapper forks were screened: there is no supported GTA IV FPS optimization to cherry-pick. KB's current `-march=znver2 -O3` and newer RPCS3 PPU-cache/RSX state-decode improvements are already present. Consider lavavex's thread CPU-time overlay only as separately validated diagnostic instrumentation; do **not** transplant v0ltfault's firmware-7.40 always-RWX JIT pool as a generic optimization, nor the std::mutex self-notify fix into our PS5 `USE_FUTEX` path. jmelovich's device-size `ENOTTY` correction may be useful for other games but is not a GTA IV CPU improvement. Review-only phase: no console files, executable, source or caches changed. Keep exact installed patch0064 gate0 baseline and saved staging; require full independent process checks before future deployment.


## Latest completed patch0067 GTA IV CPU-time diagnostic (2026-10-31)

Lavavex/rpcs3 commit 5e0e0e6 inspired a measurement-only follow-up. Do NOT cherry-pick its overlay directly: KB PS5 Utilities/Thread.cpp documents pthread_getcpuclockid(other) returns the calling thread clock. KB patch0067 reuses already-verified SIGUSR1 self-reported CLOCK_THREAD_CPUTIME_ID samples and groups ALL registered host workers, avoiding new guest hot-path probes. Name groups PPU[...], SPU[...], main rsx::thread and OTHER (includes compile/offload workers). Each core equivalent is 100% of ONE logical host CPU thread, NOT a physical CPU core or an individual guest frame.

Patch0067 source is selected (manifest patch count67), built, deployed, and tested twice in stationary GTA IV NPUB30702 indoor apartment (Chiaki ON, scheduler B/150%, 0 new SPU compilations). Two valid 45s runs, 24 exact CPU-report windows: PPU **1.565**, SPU **3.855**, main RSX **0.554**, OTHER **0.083**, all registered worker total **6.049** logical CPU equivalents; indoor FPS **59.95** at 60 cap. CPU utilization is NOT proof of the frame critical path or an FPS improvement; older outdoor top14 logs were parsed separately as truncated lower bounds.

**Installed console is restored original patch0064 gate0 matched control, NOT patch0067.** Independent full ELF load/TLS and exact mirror SHA256 PASS after guarded rollback; both title and launcher independently checked CLOSED. Patch0067 pair retained in .ps5cpu0067-stage; previous patch0065/0066 and gate1 stage preserved. Never touch live files without fresh completed process checks. Read KB-RPCS3/game research/GTA-IV-PS5-thread-CPU-groups-20261031.md and KB-RPCS3/results/gta4-ps5cpu-20261031/ps5cpu0067-indoor-combined.json. Next: uncapped matched outdoor CPU attribution paired with frame wait/dependency evidence, not optimization by aggregate SPU occupancy.


## Latest GTA IV outdoor CPU-time test after patch0067 — 2026-10-31

Four valid 45s GTA IV NPUB30702 outdoor runs, two original gate0 and two patch0067 diagnostic, all scheduler B, 150%, MFC gate0/helper probes0, tuning0 and zero new SPU compilations. Control FPS 26.77/29.35, mean 28.06; diagnostic FPS 28.20/29.32, mean 28.76. Same hydrant/lamppost *physical block*, but camera, exact Niko position, sunlight/time, traffic and reboot differ: **do not claim a +0.70 FPS improvement**. Exact patch0067 outdoor CPU group means (logical host core equivalents): SPU **5.4435**, PPU **2.2925**, main RSX **0.9215**, OTHER **0.0845** across 24 grouped CPU reports. Control top14 group estimates are lower bounds. High aggregate SPU occupancy and a near-busy RSX main thread do not prove frame critical path.

**Current PS5:** original patch0064 matched gate0 executable/mirror RESTORED with independent ELF load/TLS + mirror SHA256 readback PASS; complete process list confirms GTA IV and launcher CLOSED. Patch0067 diagnostic remains staged at .ps5cpu0067-stage and 0065/0066 + MFC gate1 stage retained. Source patch profile count67 does not mean patch0067 is live. The original control pair is live. Read KB-RPCS3/results/gta4-ps5cpu-20261031/ps5cpu0067-outdoor-control-vs-diagnostic-20261031.json and KB-RPCS3/game research/GTA-IV-PS5-thread-CPU-groups-20261031.md before any further test. Next work: per-frame wait/dependency or accurate RSX/SPU critical-path profiling in an identical uncapped outdoor view; repeat independent process checks before live binary changes.

## Native host TLS guest-state fast-path feasibility (2026-10-31)

Read `game research/GTA-IV-native-TLS-guest-fastpath-feasibility-20261031.md` before attempting native TLS guest-state optimization. User requested caching active guest state in host Native TLS. An **offline actual PS5 target compiler test** confirmed native TLS is supported (`R_X86_64_GOTTPOFF` and FS access), with correct host-thread isolation/context-switch behavior. But generated code used **9 instructions vs 2** for guest PPU r13 and **11 vs 3** for SPU local-store byte when accessing via a newly cached host TLS pointer rather than the direct context/local-store pointer already provided by the JIT. The host's `thread_ctrl::get_current()` **already uses** native `thread_local` storage. Do not insert a redundant TLS access into guest PPU `m_thread`/`m_base`, SPU `m_thread`/`m_lsptr`, or guest r13. Only consider a targeted host-side helper cache after identifying an expensive pre-existing lookup and proving the TLS version cheaper, with switch/unbind correctness. New files are standalone `port/tests/*native-guest-tls*` probe+validator, **no runtime source patch, build, deployment or FPS gain claim**. Original installed gate0 state untouched.


## SPU guest-context lookup audit (2026-10-31)

Read `game research/GTA-IV-SPU-context-lookup-audit-20261031.md` before introducing new host TLS caches. Source review found a repeated current-SPU lookup in `rpcs3/Emu/Cell/SPUThread.cpp:6094` (reservation-wait callback), but `cpu_thread::get_current()` ALREADY reads native TLS, without a hash-map or mutex. A more expensive `idm::get_unlocked` target-SPU lookup occurs in the RAW-SPU DMA/MMIO branch at `SPUThread.cpp:2187`, and in PPU raw-SPU MMIO helpers, but GTA IV log confirms `sys_spu_initialize(max_usable_spu=6, max_raw_spu=0)` and ordinary group SPUs use direct group pointers. `sys_event_port_send` has an id-manager global-reader-lock lookup for event-port objects, but its GTA IV hotness is not measured. No demonstrated GTA IV SPU hot path needs a second native TLS cache. Next justified measure: sampled lost-reservation wait/notify callback costs or event-port lookup frequency, not speculative TLS changes. Source/profile count67 and previously verified installed gate0 pair unchanged; no live PS5 actions performed in this audit.

## Latest patch0068 GTA IV SPU reservation callback & wait timing (2026-10-31)

**Completed diagnostic only:** Patch0068 instruments the already-native-TLS SPU reservation callback and atomic_wait + notify paths. Exact invocation counts and 1/128 per-host-worker sampled CLOCK_MONOTONIC wall / CLOCK_THREAD_CPUTIME_ID CPU. Two valid stationary OUTDOOR GTA IV NPUB30702 45s captures, scheduler B/150%, MFC gate0/helper probes0, Chiaki ON, 0 new SPU compilations, mean 27.36 FPS. Across full timed intervals (92.754s): **453056 callbacks**, **342418 atomic waits**, **115436 callback notify_all**, zero post-wait special notifications. Sampled callback **3.141us elapsed/1.431us CPU**; atomic wait **114.410us elapsed/9.627us CPU**; notify **3.013us elapsed/1.397us CPU**. Metrics NEST and sample phase biases possible; not proof of frame-critical-path latency or FPS gain. The existing guest-current SPU lookup ALREADY uses native TLS. Next: sample which producer/reservation is awaited and correlate with frame completion; do not shorten waits or bypass correct synchronization.

**PS5 now:** original patch0064 **gate0 matched control restored**, independently read back ELF PT_LOAD/TLS and exact mirror SHA256 e48a5c75cc3357d7f51474d1ded457e4d27e221c15fde446023538d8f48eda7b PASS after guarded rollback; complete post-rollback process list found title and launcher BOTH CLOSED. Patch0068 in .spuwait0068-stage, earlier 0067/0066/0065 and gate1 stages preserved. Source profile patch count68 is NOT installed title. Saves/config/caches untouched. Always repeat full independent process check before swap. Read KB-RPCS3/game research/GTA-IV-SPU-reservation-wait-timing-20261031.md and KB-RPCS3/results/gta4-spu-reswait-20261031/spuwait0068-outdoor-combined.json. Patch and tests are in KB-RPCS3/port/rpcs3-latest-patches/0068-PS5-sample-SPU-reservation-wait-callback-CPU-wall-time.patch, port/tests/check-ps5-spu-reswait.py, and parser companion.

## Latest GTA IV patch0069 SPU reservation-page/writer-source probe (2026-10-31)

**Completed:** patch0069 4KiB guest reservation page and notifier-caller-class sampling built/tested/PS5 deployed twice outdoors and SAFELY ROLLED BACK. Two valid stationary 45s GTA IV NPUB30702 captures, zero new SPU compiles, mean 27.775FPS (28.77 / 26.78). 23 complete 4s intervals: 2449 sampled SPU wait returns (period128), 2279 sampled successful notifications, overflow0. Guest page 0x017F7000 accounts for 2429/2449 = 99.18% of sampled waits, 2421 changed flags and 8 cleared reservations; 256 sampled PPU-thread and 1689 SPU-thread successful notifications at that page. Other 20 wait samples at 0x017F8000. Calling guest thread class does NOT establish the guest data writer or which notification woke the SPU. FPS vs raw sampled wait count over 4s positive +0.663; after normalizing by estimated displayed frames +0.115. Not proof of FPS bottleneck or optimization. Next: identify 128-byte reservation line within page and actual PPU/SPU writer PC/guest thread ID and compare to synchronized frame progress, without modifying guest synchronization.

**PS5 current:** exact original patch0064 gate0 matched executable/mirror restored, independent complete ELF PT_LOAD/PT_TLS and code mirror SHA256 e48a5c75cc3357d7f51474d1ded457e4d27e221c15fde446023538d8f48eda7b PASS. Independent FULL process list confirms game and launcher STOPPED. One earlier attempted close checked and found game STILL RUNNING; no file swap was attempted then. Correct close via KB-RPCS3 Options followed by full process list PASS; guarded rollback and independent verification complete. Patch0069 candidate in .spuwake0069-stage, earlier 0068/0067/0066/0065 and gate1 stages preserved. Source manifest patch count69 is NOT live title. No user saves/config/caches altered. See KB-RPCS3/game research/GTA-IV-SPU-reservation-page-attribution-20261031.md, KB-RPCS3/results/gta4-spu-wakeup-20261031/spuwake0069-outdoor-combined.json, source patch KB-RPCS3/port/rpcs3-latest-patches/0069-PS5-sample-SPU-reservation-page-wait-outcomes-and-producer.patch, and port/tests/check-ps5-spu-wakeup0069.py.

## Current focus: CPU_OPTIMIZATION_PLAN.md (2026-10-31)

User explicitly paused GTA IV-specific development and switched to the general CPU optimisation roadmap. Follow KB-RPCS3/CPU_OPTIMIZATION_PLAN.md and its new CPU_OPTIMIZATION_WORKLOG.md. **Section 1 is active; offline code-generation checkpoint complete.** Test: KB-RPCS3/port/tests/check-spu-insert-select-codegen.py, result: KB-RPCS3/results/cpu-plan-spu-insert-select-codegen-20261031.json. Isolated LLVM19 PS5 znver2 IR insert vs select gave u8/u16/u32/u64 16,384 functional-oracle PASS comparisons, and 3 stack-memory instructions default vs 0 select (6 vs 8-9 total instructions). **Actual RPCS3 JIT uses LLVM22.1.8**: offline LLVM19 lowering cannot establish guest hot-code speedup or justify changing spu_insert_select=0 default. Next general task: accurately rank actual guest SPU JIT function hashes/PCs with opt-in profiling, compare real LLVM22 Zen2 generated code and correctness before cross-game A/B/A. Keep experimental narrow LS stores OFF and ensure native TLS and profiling-on/off overhead checks later per plan. No new PS5 deployments, emulator-core edits, patches, game tests or configuration changes for this CPU-plan checkpoint. Console last independently verified prior turn: original gate0 pair installed, game/launcher stopped; not independently checked during this offline work.

## Current task focus — CPU_OPTIMIZATION_PLAN.md Section 1, patch0070 (2026-10-31)

**User asked to PAUSE GTA IV-specific development.** General PS5/RPCS3 CPU optimisation is now the focus. Read `CPU_OPTIMIZATION_PLAN.md` and `CPU_OPTIMIZATION_WORKLOG.md` before any SPU changes. Generic guest SPU JIT hot-function profiling tooling is prepared in reversible patch `port/rpcs3-latest-patches/0070-PS5-opt-in-SPU-JIT-hot-function-sampler.patch`, **default OFF**, source profile patch count70. It reuses the existing SIGUSR1 profiler, rotates top busy SPU execution workers, samples 200 times/5ms around every 8s, records candidate guest JIT hash/offsets, and disables automatic JIT dumps for the new mode. Parser `tools/ps5-spu-hotjit.py`; bounded offline ELF64 cached LLVM object inspector `tools/ps5-spu-jit-cache-inspect.py`. Tests `port/tests/check-ps5-spu-hotjit0070.py`, parser test and cache-inspector test all pass. Both standard OFF and separately archived ON diagnostic variants passed full PS5 builds/9 package checks/128B native TLS and mirrored executable text verification; diagnostic archive `/home/callum/work/cpu-plan-hotjit0070-diagnostic-20261031/` SHA256 evidence `results/cpu-plan-hotjit0070-20261031/manifest.json`. Standard source header reverted OFF and WSL title build restored OFF. **No PS5 deployment, game run or settings/saves/cache changes this turn.** Last verified installed console executable remains original patch0064 gate0 pair from prior turn; processes previously closed, but not rechecked in this offline-only turn.

**No actual hot guest JIT function ranking or real LLVM22 object disassembly has yet been obtained**, because no non-GTA-IV workload was selected or run. Existing `ps5_jit_lookup` uses a heuristic nearest entry within 256KiB; candidate ranks require exact cached LLVM22 ELF symbol confirmation. Full RPCS3 backend is LLVM22.1.8; a standalone offline LLVM22 emitter attempt failed to link due host C++ ABI mismatch, removed incomplete helper files; previous isolated LLVM19 result is not actual LLVM22 guest output. Next milestone: use representative other-game SPU load, safely and explicitly deploy opt-in ON image if appropriate after fresh independent process stops, rank guest JIT hash/offset samples, inspect exact matching LLVM22 cached object symbols, compare insertion OFF/ON codegen and measure profiler overhead and A/B/A correctness/FPS before any default optimisation. Do NOT restart GTA IV work by default.

## CPU_OPTIMIZATION_PLAN.md Section 2, patch0071 offline RSX/Vulkan wait checkpoint (2026-10-31)

User explicitly paused GTA IV studies and asked to continue the general CPU plan. Read `KB-RPCS3/CPU_OPTIMIZATION_PLAN.md`, `CPU_OPTIMIZATION_WORKLOG.md`, and `CPU_OPTIMIZATION_SECTION2_WAIT_AUDIT_20261031.md`. Section 2 source audit identified: Vulkan event wait unbounded-spin (`vk_event_spin_us=-1`) by default; zero-timeout Vulkan fence status polling; RSX DMA optional atomic bounded wait (default `rsx_dma_wait_us=0`); and misleading zero-valued RADV wait counters because title uses weak fallback storage. A `PS5 WAITS` RADV zero does NOT establish driver wait absence.

New reversible patch `port/rpcs3-latest-patches/0071-PS5-opt-in-bounded-Vulkan-fence-wait.patch` adds `ps5_vk_fence_sleep.h`, **PS5_VK_FENCE_TIMED_WAIT=0 default**. Diagnostic-only ON makes zero-timeout `vk::wait_for_fence` poll 64 times and then use bounded `vkWaitForFences(...,100000ns)`; timeout retries, success finishes, device errors propagate; no other GPU or guest sync changes. Actual extracted Vulkan event/fence wait source compiled/tested with Linux mocked Vulkan status + timed producer, errors, retries, trace pairing. Existing RSX DMA completion/callback/fault/stop/tuning regression test also passed. Exact source patch reverse/forward, Clang C++20 default-off/diagnostic-on gate tests PASS. Two complete native PS5 builds (OFF/ON) passed signed ELF PT_LOAD/PT_TLS and exact text mirror check, nine package tests. ON diagnostic archived **OFFLINE, NEVER DEPLOYED** `/home/callum/work/cpu-plan-vk-fence0071-diagnostic-20261031/`, SHA256 in `results/cpu-plan-rsx-waits0071-20261031/manifest.json`. Source header and full local build restored **OFF**, reverified matching initial OFF signed executable/mirror hashes. Source patch manifest count71 is NOT the live PS5 installation. Last verified console state from preceding turn: original patch0064 gate0 pair, both title and launcher closed; console NOT checked/touched during this offline work. No saves/config/cache touched; no FPS, frame-tail, GPU wait latency or actual device-loss benefits yet. Require representative non-GTA-IV game and guarded A/B/A before enabling any wait candidate.

## CPU_OPTIMIZATION_PLAN.md Section 3 topology audit / patch0072 (2026-10-31)

User paused GTA IV-specific testing and asked to work sequentially through KB-RPCS3/CPU_OPTIMIZATION_PLAN.md. **Section 3 offline audit DONE; actual PS5 physical SMT map NOT verified.** Details: KB-RPCS3/CPU_OPTIMIZATION_SECTION3_TOPOLOGY_AUDIT_20261031.md and CPU_OPTIMIZATION_WORKLOG.md; result KB-RPCS3/results/cpu-plan-topology0072-20261031/manifest.json.

Current PS5 `Utilities/Thread.cpp` scheduling assumes `kPs5Sibling=1`: 0/1, 2/3 adjacent CPU IDs are siblings. Historical logs showed allowed logical CPUs `0x1fff`, existing SPU mask `0x555` and PPU/RSX mask `0x1aaa`. **These show legacy policy, not actual SMT grouping or accepted OS affinities.** `ps5_apply_mask` ignores `pthread_setaffinity_np` result in opt-in `spu_hot_cpu` rebalancer; `spu_hot_cpu=-1` default, CPU12 is NOT yet verified sibling-free. Do not change affinity defaults without evidence.

Reversible patch `port/rpcs3-latest-patches/0072-PS5-opt-in-CPU-topology-and-affinity-readback.patch`, source profile patch count72, adds **default OFF** `PS5_CPU_TOPOLOGY_PROBE=0`. Explicit diagnostic ON runs one-shot on WATCHDOG ONLY, saves affinity, checks per-allowed-CPU pthread_setaffinity_np/getaffinity_np and AMD CPUID 0x8000001E APIC/core/node/thread counts, restores full original watchdog mask, logs all errors. It does not pin guest SPU/PPU/RSX workers. Parser `tools/ps5-cpu-topology.py` with synthetic 13-CPU adjacent/nonadjacent, singleton, errors/fail-restore tests passed; hosted C++20 true affinity probe and patch exact reverse/replay passed. PS5 SDK needed FreeBSD `pthread_np.h` and `cpuset_t`, fixed after first ON native compile failure.

Both complete native PS5 normal OFF and diagnostic ON builds passed 9 package checks, native PT_TLS128/15136/32, exact PT_LOAD/mirror equality; ON archived **OFFLINE NEVER DEPLOYED** `/home/callum/work/cpu-plan-topology0072-diagnostic-20261031/`. Default source header restored OFF and normal title rebuilt with identical initial OFF SHA256. **No console deployment or reads, no game run, no saves/config/caches touched, no FPS improvement claimed.** Installed console last independently checked previous turn remains patch0064 gate0 pair, both game/launcher then stopped. Next hardware check when appropriate: safely execute one-shot diagnostic and verify actual CPUID topology, OS acceptance and restoration; then measure guest worker masks/migration, later non-GTA-IV scheduler A/B/A before enabling any affinity tuning.

## CPU_OPTIMIZATION_PLAN.md Section 4, patch0073 (2026-10-31)

**User explicitly paused GTA IV-specific experiments.** General Section 4 offline audit completed. Read KB-RPCS3/CPU_OPTIMIZATION_SECTION4_JIT_CONTENTION_AUDIT_20261031.md and CPU_OPTIMIZATION_WORKLOG.md, manifest KB-RPCS3/results/cpu-plan-jit-workers0073-20261031/manifest.json. PPU LLVM's `g_cfg.core.llvm_threads=10` does **not** directly limit SPU compilation: SPU initial-cache `SPU Worker ` pool uses `get_max_threads()`, while live SPU `SPUW.` pool is 4 workers with 13 allowed logical CPUs, independent of Vulkan shader compilation. SPU cache uses title-associated guest instruction cache with size/bounds, optional legacy CRC16, sort/unique and runtime duplicate block waits. Optional CRC and filename alone do NOT prove full revision-valid cache.

Reversible patch `port/rpcs3-latest-patches/0073-PS5-opt-in-cap-live-SPU-LLVM-compile-workers.patch` introduces `PS5_SPU_LIVE_JIT_WORKER_CAP=0` **normal OFF**, diagnostic cap2 for `SPUW.` live runtime **4→2** at 13 CPUs only. No PPU startup/SPU cache/shader compile count, guest emulation logic or cache keys changed; not adaptive. Exact source patch reverse/forward and C++20 caps 0/1/2/4/32 tests PASS. Native PS5 OFF and ON builds passed full title and 9 package checks, native TLS128/15136/32 and ELF PT_LOAD/mirror equality. ON archived **OFFLINE NEVER DEPLOYED** at `/home/callum/work/cpu-plan-jit0073-cap2-diagnostic-20261031/`, signed executable SHA256 af4ee9369f022b1c8963c341019f6d58b4ef89ffd9d71fc2df053bee58635690; code mirror 7f66e09ecad2678b81ba1bf442a9e2184117284e8e1bcf697c08cfa33aec27c6. Source gate restored OFF and complete local normal title rebuilt, OFF signed executable 039a2e99ac33f21f7ca2d6e6da0610d9b3718963ee789931b393f72a5effcc22, mirror 91a6e9a59a0426549dd37758d1ef818a75294d1b328d3b536ba4b344e2f599f2, matching first OFF exactly. Selected source patch count **73**, not live PS5 title.

**No console access/deployment, game tests or cache/config/save modifications; no FPS improvement claim.** Last independently verified on-console title remains original patch0064 gate0 and game/launcher then stopped; not rechecked in this offline task. Acceptance needs non-GTA-IV cold/warm test with actual active live SPUW compilation, compare cap0/cap2 in A/B/A, startup, p95/p99, compilation latency and CPU group occupancy, ensure no deadlock/regression and roll back. Next offline Section 5 native TLS and production diagnostic overhead.

## CPU_OPTIMIZATION_PLAN.md Section 5 release CPU profiling / native TLS, patch0074 (2026-10-31)

User paused GTA IV-specific work and asked to complete CPU plan Section5 offline. Full audit: `KB-RPCS3/CPU_OPTIMIZATION_SECTION5_TLS_AND_PROFILING_AUDIT_20261031.md`, worklog `CPU_OPTIMIZATION_WORKLOG.md` and SHA256/evidence `results/cpu-plan-profile0074-20261031/manifest.json`. **Source profile patch count74 is NOT installed console title.**

New reversible `port/rpcs3-latest-patches/0074-PS5-default-off-production-CPU-profiling.patch` (eight source/header files) adds **PS5_RELEASE_PROFILE_ACTIVE=0** normal. OFF prevents SIGUSR1 registration/4s CPU snapshots, verbose FPS/RSX/wait/CPU reports, SPU reservation scope/wakeup, worker activity, RSX method/class counters and JIT function-name registry allocations in regular game play. Existing main-thread SIGUSR2 watchdog, heartbeat, live tuning refresh, JIT guest semantics, native TLS and caches are **unchanged**. Diagnostics `=1` opt-in restores all previous reports; `PS5_SPU_HOTJIT_ACTIVE` remains independently OFF unless explicitly set. **Normal OFF no longer emits PS5 FPS/CPU logs; historical log FPS measurement tooling requires a profiling ON build and careful observer-effect comparison.** Opt-in experimental `spu_hot_cpu` requires profiling ON; normal mode warns once and does not alter affinity when it is selected (otherwise it would rely on absent CPU samples).

Full patch source reverse/forward replay, Clang19 C++20 host runtime ON/OFF diagnostic sample correctness tests PASS. Actual PS5-target Znver2 O3 sample reservation function compiled as **2 host instructions OFF vs 67 ON** (static instruction count only, no FPS claim). Real PS5 compiler produced both native ELF TLS relocations and emulated `__emutls_get_address` mode, host C++20 TLS alignment/init/thread isolation/destructors PASS; PS5 compiler max explicit thread_local alignment **32B**. Existing native guest TLS prototype isolation and direct JIT param comparisons PASS. PS5 title converter PT_TLS validation and exact ELF/code mirror pass. Crucial: **no native-vs-emulated on-console performance or TLS thread-init/destructor test**, full fallback PS5 build/run not tested here; fallback `PS5_NATIVE_TLS=OFF` recipe remains unchanged.

Native full PS5 OFF and ON builds both passed 9 package checks, PT_LOAD/PT_TLS full mirror. OFF signed eboot SHA256 755d783f6a30dd8df975df042ec612c7281fa64bb87c26d6bc5baa7ae9ec935f, mirror 28090ff0915b5dc50e62acc17e808441f9ed667caff163f82870b0323e5e450b, PT_TLS128/15088/32. Diagnostic ON signed eboot 98b483516ff4e1c3a64239502d92c3f989a8917f595ea415a3027b002a8300f2, mirror 5ddd5722c548368c0d837caabd14bcc670b75f338f10604a10983c69d8510634, PT_TLS128/15136/32. OFF at `/home/callum/work/cpu-plan-profile0074-release-off-20261031/`, ON at `/home/callum/work/cpu-plan-profile0074-diagnostics-on-20261031/`; both OFFLINE ONLY, neither deployed. After ON diagnostic compile source header restored OFF, full title rebuilt, exact initial OFF hashes verified. **No PS5 connection/deployment, game run, cache/save/config change.** Last independently verified installed title original patch0064 gate0 pair, processes previously stopped but no new check. Sections 1–5 now have offline checkpoints, but performance acceptance (A/B/A in non-GTA-IV work, FPS tails and profiler observer effect) remains pending. Do not promote other unmeasured experimental optimisations automatically.


## Latest console deployment � patch0074 release (2026-10-31)

User selected and authorised latest patch74 safe-default release. **Now installed and independently verified on PS5**, superseding prior patch0064-live/offline-only notes. Experimental CPU-plan options remain OFF, production profiling OFF, native TLS retained. Exact patch0064 gate0 backup pair retained at `.before-cpuplan0074-release-20261031`; both backup and live ELF load/TLS + mirrors independently read back PASS. Final complete process listing: game/launcher CLOSED. No game launched or settings/saves/caches altered; performance and TLS lifecycle acceptance pending user testing. Full state, hashes, logs and rollback: `game research/CPU-plan-patch0074-user-testing-20261031.md` and `results/cpu-plan-release0074-deployment-20261031/installed.json`. Fresh process checks required before any later swap.


## Latest console state - combined five-option patch74 experiment (2026-10-31)

User explicitly authorised all five experimental options. Combined native build is now LIVE: SPU insert/select1, Vulkan fence timed-wait1, topology observer1, live SPU compiler cap2 and hot-JIT profiler1 (requires production profiling ON). Fresh full independent installed/backup ELF load+TLS and mirror checks PASS; exact new tuning file readback PASS; final process listing title/launcher CLOSED. Prior safe-default patch74 pair preserved as `.before-cpuplan0074-combined-20261031`; original patch0064 backup remains. Source default gates restored OFF, current build output experimental. No game launched/performance measured; saves/per-game configs/caches untouched. See `game research/CPU-plan-patch0074-user-testing-20261031.md` latest section and `results/cpu-plan-combined0074-20261031/installed.json`. Rollback requires restoring prior tuning absence as well as the paired binaries, with fresh process checks. Next: user gameplay test; actual topology/JIT samples and performance acceptance pending.

## Latest patch75 MihawkGen pacing fix — 2026-10-31

Deferred real-frame presentation fix is installed and independently verified, archive `/home/callum/work/framegen0075-pacing-fix-verified-20261031/`. Original patch75 rollback pair preserved at `.before-framegen0075-pacing-20261031`; all older stages/backups retained. Host, ThreadSanitizer, native build/package, exact live+backup ELF/TLS/mirror checks PASS. Previous combined CPU options retained; global settings/tuning unchanged. Frontend subsequently launched, then console navigation stopped on unexpected GPU settings screen while user testing. Current title/launcher process state not rechecked after boot: never reuse earlier CLOSED checks. No agent gameplay FPS acceptance or matched OFF/ON result. User reports fast-camera-turn artifacts; colour-only model has no high-motion/cut rejection, separate from fixed caller-blocking pacing. Read latest `game research/PS5-MihawkGen-integration-20261031.md` and `results/framegen0075-pacing-fix-20261031/installed-verification.json` before further work. Do not change console settings or controls during user testing.

## Latest installed framegen Adaptive local guard — 2026-10-31

User authorised install after closing game. Patch76 local tile guard is now LIVE; full native/package checks and independent live+backup ELF PT_LOAD/PT_TLS plus exact code mirror SHA256 PASS. Archive /home/callum/work/framegen0076-local-guard-20261031; previous Adaptive matched pair .before-framegen0076-local-guard-20261031 preserved. Global mode remains Adaptive; global/per-game/tuning exact unchanged. Source gate defaults restoredOFF; compiled prior combined CPU experiments retained. Final independent complete listing confirms game/launcher CLOSED; repeat checks after any launch. No gameplay/artifact/FPS acceptance yet. See game research/PS5-MihawkGen-integration-20261031.md latest section and results/framegen-local-guard-20261031/installed-verification.json. Next user rotating-camera test; rollback guarded tools/deploy-framegen0075.py rollback --variant local-guard only with fresh stopped-process checks, then independent pair readback.
