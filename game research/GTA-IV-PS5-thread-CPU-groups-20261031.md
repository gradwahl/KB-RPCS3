# GTA IV NPUB30702 — PS5 CPU-time grouping, patch 0067 (2026-10-31)

<!-- latest-state:start -->
**Latest GTA IV PS5 patch0069 SPU reservation-page and producer diagnostic (2026-10-31): COMPLETE and SAFELY ROLLED BACK.** Two valid stationary outdoor 45s GTA IV NPUB30702 runs, Chiaki ON, MFC gate0/helper probes0, 150%/scheduler B/Mega SPU/XFloat Approximate/tuning0; FPS **28.77 and 26.78**, mean **27.775**, zero new SPU compilations. Across 23 complete ~4s windows, sampled 1/128 per worker/path **2,449 SPU waits**, **2,279 successful notifier transitions**, no table overflows. Of waits, **2,429 = 99.18%** on guest page **0x017F7000** (2,421 changed flag, 8 cleared reservation); 256 PPU-thread and 1,689 SPU-thread successful notifier samples hit this page. Other 20 wait samples were 0x017F8000. Notifier source is not necessarily the guest data writer or the cause of a particular wake. Raw FPS/wait-count correlation +0.663 across 4s windows; normalized by estimated displayed frames only +0.115. This strongly supports a coordination hotspot, **NOT a demonstrated frame bottleneck or FPS improvement**.

**Console NOW:** original patch0064 **gate0 matched control RESTORED** after guarded rollback. Independent full ELF PT_LOAD/TLS and exact code mirror SHA256 **e48a5c75cc3357d7f51474d1ded457e4d27e221c15fde446023538d8f48eda7b** PASS. Complete independent PS5 process listing confirms both game and launcher **CLOSED**. Patch0069 preserved in .spuwake0069-stage (ELF117439088 bytes, mirror74612497 bytes), backup slot empty; older 0068/0067/0066/0065 and gate1 stage preserved. Patch manifest count69 refers to WSL source, **not installed PS5**. No game saves/config/caches changed. Full handoff: game research/GTA-IV-SPU-reservation-page-attribution-20261031.md and results/gta4-spu-wakeup-20261031/spuwake0069-outdoor-combined.json. Next: identify exact 128B reservation line and actual PPU/SPU data-writer callsites in 0x017F7000, not speculate on TLS or atomic timeouts.
<!-- latest-state:end -->

## Why NOT cherry-pick the upstream overlay commit

Lavavex measured `CLOCK_THREAD_CPUTIME_ID` and `pthread_getcpuclockid()` on its PS5 console and changed the performance overlay to derive PPU/SPU/RSX CPU usage from `thread_ctrl::get_cycles()`. The [commit](https://github.com/lavavex/rpcs3/commit/5e0e0e613d218e2450b8b3c8adab4576286ca92c) includes a four-line formula: `group_ns * 100 / (elapsed_ms * 1e6 * logical_cpu_count)`.

**Crucial platform discrepancy:** the current KB WSL core `Utilities/Thread.cpp` documents a live console finding: `pthread_getcpuclockid(other_thread)` returns the caller's clock ID 14, so another worker's CPU time cannot reliably be read directly. Thus blindly applying the overlay patch to this build risks incorrect results, not improved profiling.

The KB current code already has a signal-based monitor in `Utilities/Thread.cpp`: the watchdog sends `SIGUSR1` to registered RPCS3 workers; each thread saves its own `CLOCK_THREAD_CPUTIME_ID` value in an atomic slot. `ps5_thread_cpu_report(window_ns, top=14)` computes per-thread deltas every ~4 seconds but only *prints* 14 hottest worker details, while total covers all registered workers.

**Patch0067** extends that existing monitor (no new signals) to classify and sum the *same measured per-thread nanosecond deltas* across **all registered workers**, not just top14. Categories: names prefixed `PPU[`, names prefixed `SPU[`, the exact main `rsx::thread`, and all others (including any RSX helper/offloader if their ownership is unverified). Append to the existing `PS5 CPU:` log `group_ns window <ns> ppu <ns> spu <ns> rsx_main <ns> other <ns> threads_ppu <count> ...`. This is cumulative host CPU time during a sample window, **not GPU time or critical-path frame time**. Counts include registered RPCS3 workers only, not all PS5 kernel/driver threads.

## Historical GTA IV evidence — valid captures, existing logs only

Script `tools/gta4-cpu-groups.py`, results `results/gta4-rsx-classes-20261031/ps5cpu0067-historical-top14-estimates.json`, analyzed **six previously completed** captures. It uses each capture's validated FPS window boundaries rather than averaging whole emulation sessions, rejects new SPU compilations, and labels old-logger group counts `top14_lower_bound`.

| Scenario (two 45s runs) | Mean FPS | Total host CPU (one-core %) | PPU top-14 lower bound | SPU top-14 lower bound | Main RSX top-14 lower bound |
| --- | ---: | ---: | ---: | ---: | ---: |
| Initial outdoor patch0064 gate0 control | 23.42 | ~894% | ~235% (2.35 cores) | ~552% (5.52) | ~89% (0.89) |
| Return outdoor patch0064 gate0 control | 27.54 | ~877% | ~222% (2.22) | ~545% (5.45) | ~92% (0.92) |
| Indoor patch0066 diagnostic gate0, 60FPS cap | ~60 | ~599% | ~147% (1.47) | ~379% (3.79) | ~54% (0.54) |

**Interpretation:** substantial SPU aggregate CPU load; main RSX and PPU workers also busy. CPU occupancy is not proof which thread gates frame completion. The ~23.4 vs ~27.5 outdoor drift is already marked inconclusive due to scene/camera/Chiaki/boot state differences. The indoor 60FPS-capped diagnostic is not comparable as an FPS baseline. Legacy group counts omit lower-ranked workers and round individual integer percentages. Exact all-registered-worker group sums require running the new patch0067 build on console.

## Patch, verification and plans

- Patch `port/rpcs3-latest-patches/0067-PS5-report-exact-PPU-SPU-RSX-main-host-CPU-time.patch` changes `Utilities/Thread.cpp` only within PS5 monitor and adds isolated `rpcs3/ps5/ps5_cpu_groups.h`. Original `Utilities/Thread.cpp` archived at `/home/callum/work/ps5cpu0067-original-20261031/`.
- Full reversible source diff test PASS, native Clang++19 and GCC C++20 classification tests PASS: `port/tests/check-ps5-cpu-groups.py`.
- New/historical parser tests PASS: `port/tests/check-ps5-cpugroups-parser.py`. It strictly separates `exact` reports from `top14_lower_bound`.
- Script `tools/gta4-cpu-groups.py` deliberately does **not** assert that 100% means one *physical* Zen2 core: on the console CPU accounting is one hardware/logical CPU clock. To express a share of 16 possible hardware threads, divide the printed one-core percentages by 16, **only after verifying logical count**.
- Future diagnostics should show the individual most active PPU and SPU threads and four group totals, including OTHER for graphics/driver/offload and background RPCS3 threads. This can improve *where to inspect*, not prove a speedup.
- Next host phase: complete build, native PS5 ELF/TLS and pair code-mirror checks; archive exact hashes. Only then independent process check, guarded two-file deployment; establish same GTA IV scene; take two valid stationary 45s samples. If scene is indoors, record CPU attribution but no outdoor FPS-speedup inference. Close both, safe rollback, independent code verification and research handoff.


## Patch0067 PS5 CPU-time grouping: on-console results and safe return (2026-10-31)

Lavavex commit https://github.com/lavavex/rpcs3/commit/5e0e0e613d218e2450b8b3c8adab4576286ca92c adds PPU/SPU/RSX CPU time to its performance overlay via thread_ctrl::get_cycles(). On KB's tested PS5, pthread_getcpuclockid(target) returns the calling thread's clock, so directly backporting it would risk bogus data. The current KB Utilities/Thread.cpp has a signal-based monitor: send SIGUSR1 to every registered RPCS3 worker, and each worker reports its own CLOCK_THREAD_CPUTIME_ID nanoseconds. Patch0067 reuses SAME snapshots (no extra signals) and aggregates ALL worker deltas into PPU, SPU, exact main rsx::thread, OTHER. Other includes SPU JIT compilation worker pool, graphics helpers and miscellaneous RPCS3 host threads, so avoid assuming that OTHER is idle CPU or that main-RSX is complete graphics-driver time. Percent is of one logical host hardware thread, not a physical core or game frame.

Source patch: port/rpcs3-latest-patches/0067-PS5-report-exact-PPU-SPU-RSX-main-host-CPU-time.patch. Source original /home/callum/work/ps5cpu0067-original-20261031. Reversible patch replay PASS; GCC and Clang++19 C++20 tests PASS (port/tests/check-ps5-cpu-groups.py); synthetic legacy/exact parser tests PASS (port/tests/check-ps5-cpugroups-parser.py). Full PS5 build, TLS 128/15104/alignment32, ELF vs code-mirror full byte equality, all nine package checks PASS. Archived pair/hashes at /home/callum/work/ps5cpu0067-groups-20261031. Guarded stage/readback/activate verified no title or launcher processes, retained prior full gate0 pair, matched ELF load and TLS, code mirror SHA256. Loaded GTA IV normally via Chiaki and warmed SPU compilation before captures.

| GTA IV apartment measurement (logical-core equivalents) | Run1 | Run2 | Mean |
| --- | ---: | ---: | ---: |
| PPU | 1.577 | 1.552 | **1.565** |
| SPU | 3.883 | 3.827 | **3.855** |
| Main RSX | 0.557 | 0.550 | **0.554** |
| Other RPCS3 host threads | 0.083 | 0.082 | **0.083** |
| All registered host threads | 6.093 | 6.005 | **6.049** |
| FPS (60 cap) | 59.94 | 59.96 | **59.95** |

Each capture had 45s, 11 FPS windows and 12 valid exact CPU time reports; both had zero new SPU compilations. Captures/logs and per-run parsed JSON are in results/gta4-ps5cpu-20261031/; combined result is ps5cpu0067-indoor-combined.json. The 60 cap prevents FPS inference. CPU time over parallel workers cannot distinguish which wait or worker gated frame delivery. Out-of-registry driver/kernel tasks are excluded.

**Previously captured historical GTA IV CPU lower bounds (top14-only reports):** initial outdoor control ~23.42 FPS and total ~8.94 logical cores, printed PPU ~2.35/SPU ~5.52/main RSX ~0.89; return outdoor gate0 control ~27.54 FPS, total ~8.77, top14 PPU ~2.22/SPU ~5.45/main RSX ~0.92. Historical JSON: results/gta4-rsx-classes-20261031/ps5cpu0067-historical-top14-estimates.json. These older group values omit smaller workers and have integer rounding; differing outdoor scenes/Remote Play/boot state confound FPS attribution. The SPU group being busier is NOT itself evidence it controls the FPS.

**Rollback:** Chiaki Games Home, selected KB-RPCS3, Options, Close Game. Complete independent process list verified title/launcher stopped, guarded rollback exit0. Independent download confirmed restored original ELF PT_LOAD and PT_TLS and exact original mirror SHA256; the title files now have original gate0 sizes (ELF 117434056 bytes; mirror 74605201 bytes). Both diagnostic stage files remain (0067 ELF 117438656 bytes; mirror 74608465 bytes). Final process list after rollback again confirms both processes closed. No user game data or config changed.

**Next:** measure exact CPU groups in *uncapped, matched outdoor gameplay* with stable controls, and pair with PPU/SPU/RSX wait or per-frame critical-path evidence before making any performance optimization.



## Patch0067 matched-area outdoor CPU experiment, completed 2026-10-31

User positioned GTA IV Niko beside the hydrant/lamppost outdoors. Two 45s gate0 controls were captured in that exact user-set viewpoint; both passed 11 FPS reporting windows, gate0/helper probes0 and zero new SPU compilations. The PS5 title and launcher were stopped via Chiaki Home > KB-RPCS3 Options > Close Game, independently process-checked, and the staged patch0067 paired executable/mirror activated with guarded full SHA256 and ELF/TLS readback. The game rebooted into the apartment, and bounded Chiaki movement returned Niko to the same block; new viewpoint, precise Niko position, daylight and traffic were different. Both 45s patch0067 outdoor diagnostic runs passed, with 12 exact all-registered-thread CPU reports each and zero new SPU compiles.

| Phase | Run 1 FPS | Run 2 FPS | Mean FPS | PPU host cores | SPU host cores | Main RSX host cores |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Original gate0 control, top14 group LOWER BOUNDS | 26.77 | 29.35 | **28.06** | 2.2815 | 5.5300 | 0.9425 |
| Patch0067 exact all-worker groups | 28.20 | 29.32 | **28.76** | 2.2925 | 5.4435 | 0.9215 |

Original gate0 total CPU ~8.937 logical host cores; patch0067 total ~8.737, OTHER ~0.0845. Control group sums omit registered workers outside top 14, but its overall total includes all registered workers. Patch0067 exact group counts include all registered workers, not kernel/driver threads outside the registry. Six guest SPU threads consume ~5.44 cores total and the main RSX worker ~0.92 of one logical host core. Summed CPU time does NOT say which thread waits on another or gates the next frame. Neither phase was FPS capped in the outdoor street. The control samples themselves differed by 2.58FPS. Nominal +0.70FPS diagnostic phase difference is NOT an optimization result: changed camera/position/traffic/lighting, load/boot conditions and sampling order make it noncausal.

After capture, game closed normally via Chiaki; independent full PS5 process list confirmed no title or launcher. Guarded patch0067 rollback exit0; independently downloaded restored exact gate0 executable ELF load/TLS and code mirror exact SHA256 verification PASS. Patch0067 remains staged; old gate1 and diagnostic stages remain intact; no game data/config/cache changes.

Data: results/gta4-ps5cpu-20261031/ps5cpu0067-outdoor-control-vs-diagnostic-20261031.json, four individual FPS/log files, ps5cpu0067-outdoor-control-groups.json and ps5cpu0067-outdoor-run1-groups.json / ps5cpu0067-outdoor-run2-groups.json. Next capture PPU/SPU/RSX per-frame dependency and waits in a same-angle outdoor test before any source-code optimization.


## Patch0068 SPU reservation-wait timings, completed 2026-10-31

Two stationary outdoor GTA IV 45s diagnostic captures passed, zero new SPU compiles, mean27.36FPS. Patch0068 exact invocation counts during the complete watchdog intervals: 453056 reservation callbacks (~4885/s), 342418 atomic waits (~3692/s), 115436 nested notify_all calls (~1245/s). Timed 1/128 samples separate CLOCK_MONOTONIC and CLOCK_THREAD_CPUTIME_ID: callback 3.141us wall/1.431us worker CPU; atomic wait 114.410us wall/9.627us worker CPU; notification 3.013us wall/1.397us worker CPU. Nested metrics cannot be summed as exclusive costs; samples include clock overhead and phase bias. Waiting time is predominantly non-running time, **not proof it limits FPS**. Native TLS lookup is already cheap. See GTA-IV-SPU-reservation-wait-timing-20261031.md. Guarded diagnostic rollback and independently verified original patch0064 gate0 ELF PT_LOAD/TLS + exact mirror SHA256 PASS, both processes CLOSED; 0068 retained in .spuwait0068-stage, no user configs or saves changed. Source patch count68 is NOT installed.


## Patch0069: sampled SPU reservation page and notification origin (2026-10-31)

After completed patch0068 elapsed-vs-CPU wait measurement, patch0069 measured which 4KiB guest page receives sampled SPU waits and which guest thread class initiates successful notification transitions. Two valid 45s stationary **outdoor** captures, FPS28.77 / 26.78, zero new SPU compiles. 1/128 per-host-worker/path samples: 2449 wait returns, 2279 successful notifier transitions; 0 table overflow. 2429 SPU wait samples (**99.18%**) on guest page **0x017F7000**; changed notifier flag2421, cleared reservation8; 256 PPU-origin and 1689 SPU-origin successful notify samples on same page. Other 20 wait samples on 0x017F8000. Note global notifier samples also include pages not in top8 wait list. Notification caller is not necessarily guest data writer or actual wake cause. Per-4s window wait count correlated positively with FPS (+0.663), but per-estimated-frame-normalized counts only weakly (+0.115). **No FPS speedup or actual frame-gating dependency is proven.** Next identify exact 128B line and guest data writer/callsites. Original patch0064 gate0 installed and independently ELF/TLS + mirror hash verified after guard rollback; game and launcher CLOSED; patch0069 safely staged. See GTA-IV-SPU-reservation-page-attribution-20261031.md.
