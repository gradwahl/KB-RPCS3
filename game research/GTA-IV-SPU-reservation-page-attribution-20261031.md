# GTA IV NPUB30702 — patch0069 SPU reservation page and notification origin (2026-10-31)

<!-- latest-state:start -->
**COMPLETED:** patch0069 built, validated, safely deployed, tested twice in stationary outdoor GTA IV, and **ROLLED BACK** with independent executable/TLS and mirror verification. Two valid 45-second outdoor captures, MFC gate0/helper probes0, scheduler B/150%, Chiaki ON, 0 new SPU compilations; FPS **28.77 / 26.78**, mean **27.775**. Over 23 complete ~4s watchdog intervals (92.763s), **2,449 sampled SPU waits**, **2,279 sampled successful producer notifications**, table overflow **0**. Of sampled waits, **2,429 (99.18%)** used guest reservation page **`0x017F7000`** (2,421 changed flag; 8 cleared reservation). That page received **256 PPU-thread** and **1,689 SPU-thread** sampled successful notification attempts (not necessarily actual writer/wakeup). Second page `0x017F8000` contained the other 20 sampled waits. Raw four-second FPS/wait-count correlation **+0.663**; after normalizing the wait count by estimated presented frames, correlation only **+0.115**. No causal frame stall demonstrated; no FPS improvement claimed.

**PS5 NOW:** exact original patch0064 **gate0 matched control restored**, downloaded ELF PT_LOAD/PT_TLS and exact mirror SHA256 **e48a5c75cc3357d7f51474d1ded457e4d27e221c15fde446023538d8f48eda7b** PASS. Independent complete process list confirms **GTA IV and launcher both CLOSED**. Patch0069 staged in `.spuwake0069-stage` (ELF 117439088, code mirror 74612497). Previous patch0068/0067/0066/0065 and MFC gate1 candidate stages retained. WSL source manifest selects patch count69, but live title is patch0064 gate0. Game saves/config/caches untouched. Never swap executable/mirror while processes run.
<!-- latest-state:end -->

## Why and what was measured

The patch0068 outdoor SPU timing experiment showed ~3,692 atomic waits/sec and that timed atomic-wait **elapsed 114.410 µs versus only 9.627 µs host-thread CPU time** per sampled call. That was consistent with waiting/descheduling but did not identify the wait's dependency. Patch0069 tracks which guest reservation pages appear in those SPU waits and the types of host guest threads performing successful notification transitions, without changing guest SPU logic, memory or wait operations.

- Source: `port/rpcs3-latest-patches/0069-PS5-sample-SPU-reservation-page-wait-outcomes-and-producer.patch`, extending patch0068. New `rpcs3/Emu/Cell/ps5_spu_wakeup.h`, edits to SPUThread.cpp, vm.cpp and ps5_frontend.cpp.
- For *every 128th invocation per host worker* on the SPU atomic-wait path, record the full 4 KiB guest page index (`raddr >> 12`), whether the notifier wait flag changed after returning, whether `this->raddr` was cleared, or whether neither happened. No additional clocks on the sampled wait; patch0068's original wall/CPU timing remains unchanged.
- For *every 128th successful odd-to-even notification transition*, record the page and whether the caller of `vm::reservation_notifier_notify` is a guest PPU, guest SPU or other host thread. **This source classification identifies the notifying thread, not necessarily the thread that wrote the data or the specific wake responsible for the wait return.** No guest page bytes were read or written by the probe.
- Fixed 256-slot bounded open-addressing atomic page table (8 probes max); no logging, locks or allocation on guest/renderer worker paths. Up to eight hottest pages by **cumulative sampled waits** are logged by the watchdog per existing ~4s FPS/CPU window, along with global sampled wait/notifier/overflow counters. Low-ranked or notification-only pages can be omitted from the top8 page rows even with zero overflow.
- These are 1/128 **sampled event counts, not exact execution totals**. Per-worker phase can alias deterministic workloads. Cumulative page rows are compared between consecutive *complete top8 snapshots* to obtain the interval; no startup totals leak into warmed capture analysis. The 4s FPS/CPU reports are window-level concurrent activity, not aligned causal guest-frame traces.
- The existing `PS5 CPU:` full-thread group measurement is used for coarse PPU/SPU/main-RSX occupancy in the same reports. The previous `ps5_frame_trace.h` per-frame tracer remains disabled; no unsupported per-frame causal claim.

## On-console outdoor results

Game: GTA IV NPUB30702. Niko positioned stationary outside on the sidewalk near the yellow awning and hydrant, Chiaki remote play ON. Compiled MFC gate0/helper probes0; scheduler B/150% resolution, Mega SPU, XFloat Approximate, clocks100%, cap60 (outdoor FPS below cap), no experiment tuning flags. Both 45s run validators passed and **zero new SPU compilations**.

| Metric | Run 1 | Run 2 | Combined |
| --- | ---: | ---: | ---: |
| FPS mean of reporting windows | 28.77 | 26.78 | **27.775** |
| 4s watchdog intervals | 11 | 12 | **23** |
| Sampled SPU waits, all pages | 1,243 | 1,206 | **2,449** |
| Successful notifier sample events, all pages | 1,156 | 1,123 | **2,279** |
| Wait samples on page `0x017F7000` | 1,233 | 1,196 | **2,429** |
| Wait samples on page `0x017F8000` | 10 | 10 | **20** |
| `0x017F7000` changed wait flag | 1,230 | 1,191 | **2,421** |
| `0x017F7000` cleared reservation | 3 | 5 | **8** |
| `0x017F7000` unchanged outcome | 0 | 0 | **0** |
| Page `0x017F7000` successful PPU notifier samples | 118 | 138 | **256** |
| Page `0x017F7000` successful SPU notifier samples | 879 | 810 | **1,689** |
| Page-table overflows | 0 | 0 | **0** |
| FPS vs *absolute sampled waits per ~4s* Pearson r | +0.274 | +0.703 | **+0.663** combined |
| FPS vs *sampled waits per estimated displayed frame* Pearson r | — | — | **+0.115** combined |

One sampled wait per frame proxy ≈ **0.951** across the combined intervals, i.e. 128x would be ~122 actual waits per displayed frame *only if* the periodic 1/128 samples were representative. **Do not treat this extrapolation as a direct count**.

The top8 wait-ranked table showed only the two wait-hot pages above. That does **not** imply all 2,279 sampled notifier events occur on those pages: 334 were associated with other pages not present in the wait-ranked top rows, not hash-table overflows. On `0x017F7000`, PPU/SPU notifier samples are both nonzero, with SPU much higher.

## Interpretation and limits

**`0x017F7000` is a high-traffic reservation page for GTA IV's SPU coordination.** It accounts for ~99.2% of sampled waits across two warmed outdoor captures. Most sampled wait returns observed changed notifier flags, with only eight reservation-cleared outcomes. This suggests a shared coordination structure, but **the contents/ownership of the page are not yet verified**. A 4 KiB bucket does not identify the exact 128-byte reservation line or PS3 object.

Neither notifications nor sampled wait-count correlations prove that this page is a **frame-gating stall**. Absolute wait counts rise when the game progresses faster; the combined positive raw correlation (+0.663) largely disappears after normalizing by estimated displayed frames (+0.115). The metric is also sampled and both FPS and wait counts depend on the speed of underlying work. Need synchronized producer/consumer dependency or per-frame timeline evidence before optimizing.

The patch contains no optimization and was not FPS A/B/A tested. FPS between patch0068 and patch0069 sessions is not a causal speedup due to traffic, camera, reboot and time drift. No timeout, guest scheduling, notifier condition or TLS mapping was modified.

## Build, testing and safe deployment

- Patch archive originals: `/home/callum/work/ps5spu0069-original-20261031/`, including SHA256 manifest. `port/tests/check-ps5-spu-wakeup0069.py` exact reverse/forward patch replay from the dirty WSL source, Clang19/GCC C++20 lock-free page table, per-host-worker 1/128 sampling, outcomes and concurrent notifier source tests PASS.
- Native PS5 build `JOBS=2 bash tools/wsl-build-latest.sh`, log `/home/callum/work/ps5spuwake0069-build-20261031.log`, 9 package checks PASS. Native TLS template128/memory15136/alignment32; full ELF executable PT_LOAD code equality to `rpcs3ps5-text.bin` verified.
- Hash-pinned archive `/home/callum/work/ps5spuwake0069-pages-20261031/`: signed executable SHA256 `63f70a354b99468dda20bcad4550c9bbc3a0a64f39d04b9c209e225920100569`, mirror SHA256 `0f7a02625b5ff5e744272689c1a0264aecc524b717fdcf1530766803c14e8815`.
- Guarded installer `tools/deploy-gta4-spuwake0069.py`, isolated `.spuwake0069-stage` and `.before-spuwake0069-20261031` slots, checks complete independent process listing before stage, activation and rollback. Both staged and activated files read back and verified, including decrypted ELF PT_LOAD/TLS and exact mirror hash.
- After captures: Chiaki PS Hold → KB-RPCS3 Options → Close Game. A first process check detected that the game was STILL RUNNING because focus had moved to a different PS5 tile; **no file mutation took place**. Navigated back to KB-RPCS3, selected Close Game, then a complete independent process listing confirmed game/launcher stopped. Guarded rollback successful. Independently downloaded restored original gate0 executable load/TLS and mirror SHA256 verified PASS. Final full process listing confirmed both stopped; diagnostic remained staged, empty backup names. No game saves/config/caches touched.
- Source profile `port/rpcs3-latest.json` now patch count **69**; live PS5 title **still original gate0**.
- Exact results: `results/gta4-spu-wakeup-20261031/B-spuwake0069-outdoor-run[1,2].log/.json`; individual parsed `spuwake0069-run[1,2]-pages.json`; combined `spuwake0069-outdoor-combined.json` and `session-info.json`. Parser `tools/gta4-spu-wakeup0069.py`.

## Next specific test

Identify **what guest object/reservation line** inside `0x017F7000` is observed by the SPUs, and which guest SPU/PPU instruction is the **actual writer**. A future default-off diagnostic could sample *128-byte reservation-line offsets*, caller guest SPU/PPU IDs and the guest callsite/PC, plus carefully bounded producer-write events. Never assume notifier source == writer, never log or modify guest memory content unnecessarily. Only then relate individual waits to guest display-queue/RSX progress through an explicitly enabled low-overhead frame timeline. Do not optimize from a page's traffic frequency alone.
