# GTA IV NPUB30702 — patch 0068 SPU reservation-wait timing (2026-10-31)

<!-- latest-state:start -->
**Latest GTA IV PS5 patch0069 SPU reservation-page and producer diagnostic (2026-10-31): COMPLETE and SAFELY ROLLED BACK.** Two valid stationary outdoor 45s GTA IV NPUB30702 runs, Chiaki ON, MFC gate0/helper probes0, 150%/scheduler B/Mega SPU/XFloat Approximate/tuning0; FPS **28.77 and 26.78**, mean **27.775**, zero new SPU compilations. Across 23 complete ~4s windows, sampled 1/128 per worker/path **2,449 SPU waits**, **2,279 successful notifier transitions**, no table overflows. Of waits, **2,429 = 99.18%** on guest page **0x017F7000** (2,421 changed flag, 8 cleared reservation); 256 PPU-thread and 1,689 SPU-thread successful notifier samples hit this page. Other 20 wait samples were 0x017F8000. Notifier source is not necessarily the guest data writer or the cause of a particular wake. Raw FPS/wait-count correlation +0.663 across 4s windows; normalized by estimated displayed frames only +0.115. This strongly supports a coordination hotspot, **NOT a demonstrated frame bottleneck or FPS improvement**.

**Console NOW:** original patch0064 **gate0 matched control RESTORED** after guarded rollback. Independent full ELF PT_LOAD/TLS and exact code mirror SHA256 **e48a5c75cc3357d7f51474d1ded457e4d27e221c15fde446023538d8f48eda7b** PASS. Complete independent PS5 process listing confirms both game and launcher **CLOSED**. Patch0069 preserved in .spuwake0069-stage (ELF117439088 bytes, mirror74612497 bytes), backup slot empty; older 0068/0067/0066/0065 and gate1 stage preserved. Patch manifest count69 refers to WSL source, **not installed PS5**. No game saves/config/caches changed. Full handoff: game research/GTA-IV-SPU-reservation-page-attribution-20261031.md and results/gta4-spu-wakeup-20261031/spuwake0069-outdoor-combined.json. Next: identify exact 128B reservation line and actual PPU/SPU data-writer callsites in 0x017F7000, not speculate on TLS or atomic timeouts.
<!-- latest-state:end -->

## Objective and methodology

The previous guest-state audit found that `cpu_thread::get_current()` in the callback in `rpcs3/Emu/Cell/SPUThread.cpp` already uses host-native TLS, and that trying to cache a second copy is unlikely to be a speedup. Patch0068 therefore **measured the surrounding work**: callback execution, the encompassing atomic wait, the callback's `lv2_obj::notify_all`, and the post-wait `vm::reservation_notifier_notify`.

New source `port/rpcs3-latest-patches/0068-PS5-sample-SPU-reservation-wait-callback-CPU-wall-time.patch` modifies only PS5 diagnostic clauses in `rpcs3/Emu/Cell/SPUThread.cpp` and watchdog reporting in `rpcs3/ps5/ps5_frontend.cpp`; new header `rpcs3/Emu/Cell/ps5_spu_reswait.h`.

- For each of four events, an exact relaxed-atomic invocation count; only 1/128 calls per host thread/event timed using `CLOCK_MONOTONIC` and the *calling host thread's own* `CLOCK_THREAD_CPUTIME_ID`.
- No additional signals, guest behavior changes, allocation, locks or clock calls for 127/128 invocations. Sampled invocations include measurement overhead; cumulative counters reported every ~4s by the existing watchdog in the `PS5 SPUWAIT: v1 event ...` format.
- Times are **not exclusive**: callback encompasses its inner notification, and atomic_wait encompasses any callbacks and blocking. **Never add or subtract them as if independent, or infer wall wait equals busy CPU execution.**
- Snapshot counters are cumulative; parsing compares first and final complete 4-event groups within the warmed FPS-scoped log window to avoid startup contamination.
- 1/128 periodic timing may phase-alias with repetitive SPU work; CPU-time clock precision and the two selected clocks' overhead may influence very short callback samples. Counts remain exact.
- Four event IDs: 0 callback, 1 atomic_wait, 2 callback_notify, 3 post_wait_notify.

## Validated on-console captures

Settings scheduler B (RPCS3 Scheduler), 150% resolution, Mega SPU, XFloat Approximate, 100% clocks, 60 FPS cap (outdoor was ~27 FPS, not capped), all tuning flags0, Performance Report OFF, Chiaki remote play ON; stationary Niko on the outdoor hydrant/yellow-awning street. The console log verified `PS5 MFCMETER: gate 0 helper_probes 0`. Both captures passed FPS-window validators and **zero** new SPU compilations.

| Measure | Run 1 | Run 2 | Combined |
| --- | ---: | ---: | ---: |
| FPS (mean of windows) | 27.13 | 27.59 | **27.36** |
| Complete four-event CPU reports | 12 | 13 | **25** |
| Measured report interval | 44.359 s | 48.395 s | **92.754 s** |
| Callback calls (exact) | 217,316 | 235,740 | **453,056** |
| Atomic waits (exact) | 148,149 | 194,269 | **342,418** |
| Callback notifications (exact) | 71,012 | 44,424 | **115,436** |
| Post-wait notifications (exact) | 0 | 0 | **0** |

The complete watchdog intervals are not necessarily the exact nominal 45 s capture duration; the second run's FPS-scoped report interval spans ~48.4 s. Rates should use the measured durations, as the JSON does.

| 1-in-128 sample cost | Timed calls across both captures | Mean wall per sampled call | Mean host-thread CPU per sampled call | Wall/CPU ratio |
| --- | ---: | ---: | ---: | ---: |
| Reservation callback | 3,541 | **3.141 µs** | **1.431 µs** | 2.19 |
| Atomic wait | 2,675 | **114.410 µs** | **9.627 µs** | 11.88 |
| Callback `notify_all` | 904 | **3.013 µs** | **1.397 µs** | 2.16 |
| Post-wait notifier | 0 | n/a | n/a | n/a |

Call rates across measured intervals: callback **~4,885/s**, atomic wait **~3,692/s**, callback notify **~1,245/s**. These are total counts over all sampled registered SPU workers. The zero post-wait notify event means **that one special conditional was never observed** during the scoped intervals, not that all notifications are absent.

**Interpretation:** the reservation wait callback runs thousands of times per second, but its timed CPU cost is very small. The atomic wait includes roughly twelve times as much sampled elapsed time as running CPU time, suggesting the worker is generally waiting/descheduled rather than burning the measured wall time. But it is **not proof** that waits delay frame production, or that making them shorter improves performance. GTA IV's last outdoor CPU group capture showed SPU ~5.44 logical-core equivalents in aggregate and main RSX ~0.92; much of the actual SPU CPU usage therefore lies **outside this sampled callback/wait path**. Do not insert a second TLS cache or bypass reservation synchronization.

## Build, safety and reproducibility

- Exact originals archived `/home/callum/work/ps5spuwait0068-original-20261031/` (two modified sources + SHA256 manifest), and a reversible patch stored in `port/rpcs3-latest-patches/`. `port/rpcs3-latest.json` selected patch count **68**; no existing modifications were reset/cleaned/committed.
- Host tests: `port/tests/check-ps5-spu-reswait.py` exact reverse/forward source replay, Clang++19/GCC C++20 counters, timing and host-thread phase isolation PASS. `port/tests/check-ps5-spu-reswait-parser.py` synthetic cumulative multi-event timing and invalid compilation/counter regression PASS.
- Native PS5 build `JOBS=2 bash tools/wsl-build-latest.sh`, log `/home/callum/work/ps5spuwait0068-build-20261031.log`. All nine package gates PASS, compiled MFC gate0/helper probes0. Native TLS template128/memory15120/align32 (16 bytes larger due to per-thread sampler phase slots). Exact signed/converted binaries and mirror archived `/home/callum/work/ps5spuwait0068-reservation-20261031/`; executable SHA256 `4c1a18fbfd4294a1ca951ca7d4e0aa48308ba7383fff7ddfe13e30ccfc2246ba`, code mirror SHA256 `3e3e385f0e41ac570d958439229a74c743347abd446bf49aa85b29f88f0e5275`. Original decrypted ELF's load and exact full text mirror verified.
- Exact hash-pinned guarded installer `tools/deploy-gta4-spuwait0068.py`; separate `.spuwait0068-stage` and `.before-spuwait0068-20261031` slots, independently completed stopped-game-and-launcher process checks before staging and activation, backed-up matched original gate0 pair, full readback ELF load/TLS and text code mirror before/after activation. After capture, Chiaki Games Home > KB-RPCS3 Options > Close Game, independently verified processes both stopped; guarded rollback successful and preserved new diagnostic as stage. Independently downloaded *restored* gate0 full ELF load/TLS and exact code mirror SHA256 PASS. Final process listing no game/launcher.
- Main session data `results/gta4-spu-reswait-20261031/`: `B-spuwait0068-outdoor-run[1,2].{json,log}`, parser `tools/gta4-spu-reswait.py`, results `spuwait0068-run[1,2]-timing.json`, `spuwait0068-outdoor-combined.json`, `session-info.json`. Do not overwrite.

## Recommended next experiment

Focus on **which reservation/producer or event the SPU waits for and its correlation with frame time**, preferably in the same outdoor viewpoint. Sample stable reservation address buckets or wait-return outcomes without changing synchronization or guest memory semantics. Measure both producer and consumer sides and compare timings to RSX/PPU progress. The current data **does not** support a faster TLS lookup, disabling the callback, shortening the timeout blindly, or reporting any FPS gain.


## Patch0069: sampled SPU reservation page and notification origin (2026-10-31)

After completed patch0068 elapsed-vs-CPU wait measurement, patch0069 measured which 4KiB guest page receives sampled SPU waits and which guest thread class initiates successful notification transitions. Two valid 45s stationary **outdoor** captures, FPS28.77 / 26.78, zero new SPU compiles. 1/128 per-host-worker/path samples: 2449 wait returns, 2279 successful notifier transitions; 0 table overflow. 2429 SPU wait samples (**99.18%**) on guest page **0x017F7000**; changed notifier flag2421, cleared reservation8; 256 PPU-origin and 1689 SPU-origin successful notify samples on same page. Other 20 wait samples on 0x017F8000. Note global notifier samples also include pages not in top8 wait list. Notification caller is not necessarily guest data writer or actual wake cause. Per-4s window wait count correlated positively with FPS (+0.663), but per-estimated-frame-normalized counts only weakly (+0.115). **No FPS speedup or actual frame-gating dependency is proven.** Next identify exact 128B line and guest data writer/callsites. Original patch0064 gate0 installed and independently ELF/TLS + mirror hash verified after guard rollback; game and launcher CLOSED; patch0069 safely staged. See GTA-IV-SPU-reservation-page-attribution-20261031.md.
