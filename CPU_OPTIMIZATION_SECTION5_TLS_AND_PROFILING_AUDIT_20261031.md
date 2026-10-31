# CPU optimisation plan — Section 5 native TLS and production profiling audit

**Date:** 31 October 2026  
**Scope:** General KB-RPCS3 PS5 release profiling and thread-local state, *not GTA IV-specific work*.  
**Status:** Offline source audit, reversible patch, native/emulated-target compiler tests, hosted lifecycle tests and full PS5 normal/diagnostic builds **passed**. The actual PS5 TLS lifecycle, profiler-on/off FPS impact and native-vs-emulated TLS performance **have not been benchmarked on the console**.

## 1. What was expensive in normal builds

Before patch 0074, the PS5 watchdog's recurring 4-second reporting path included:

- `ps5_thread_cpu_report()`: sending **SIGUSR1 to every registered RPCS3 host thread**, sleeping for 30 ms, collecting thread CPU snapshots and printing `PS5 CPU` totals. Every thread registered an atomic CPU slot and signal handler on creation, removed it at exit, and could receive this signal during compilation or emulation.
- Periodic `PS5 FPS`, `PS5 TIMING`, `SPUWAIT`, `SPUWAKEPAGE`, `SPUCOVER`, `WORKER`, `mprotect`, `WAITS`, `CLOCK` and other diagnostic log records.
- **Hot-path counters still enabled despite no explicit JIT profiler session:** SPU reservation callbacks entered an atomic-counting scope and periodically sampled two clocks; SPU reservation-wakeup events sampled thread-local phases and a bounded atomic per-page table; SPU/RSX worker-activity probes recorded gateway/CPU stages; and RSX method-loop and register-class histograms compiled with both flags **ON by default**.
- During actual SPU JIT compilation, `ps5_jit_name()` recorded every guest function in a `std::map` under a mutex, regardless of whether a sampled JIT profile was requested.

The SIGUSR1 sampling and method histograms are *profiling* mechanisms, not part of the guest emulation correctness path. Nonetheless, removing a probe is a source/assembly-level overhead reduction only; we must still benchmark real games to establish any frame-time or CPU-time improvement.

**Safety distinction:** The watchdog's **SIGUSR2 main-thread hang stack dump**, 20-second heartbeat rule, thread lifetime, initial tuning refresh, periodic live tuning reload and one-time tuning-change notifications remain intact. The native host TLS implementation and PPU/SPU LLVM execution entry pointers are unchanged.

## 2. Reversible patch 0074: one global release diagnostics gate

Source patch: `port/rpcs3-latest-patches/0074-PS5-default-off-production-CPU-profiling.patch`  
New header: `rpcs3/ps5/ps5_release_profile.h`  
Switch: **`PS5_RELEASE_PROFILE_ACTIVE=0` by default**; compiling **`=1`** restores the heavy diagnostic path, with the existing `PS5_SPU_HOTJIT_ACTIVE` flag separately controlling the 200-SIGUSR1 JIT sampler.

Files affected (seven existing files and one new gate header): `rpcs3/ps5/ps5_frontend.cpp`, `Utilities/Thread.cpp`, `rpcs3/Emu/RSX/ps5_rsx_words.h`, `rpcs3/Emu/RSX/ps5_worker_activity.h`, `rpcs3/Emu/Cell/ps5_spu_reswait.h`, `rpcs3/Emu/Cell/ps5_spu_wakeup.h`, and `rpcs3/Emu/Cell/SPULLVMRecompiler.cpp`.

### Normal build (OFF)

- **No per-thread SIGUSR1 registration or teardown, CPU snapshot loop, or 4-second detailed performance logging.** The watchdog still wakes normally to check the heartbeat and reload tuning.
- `ps5_spu_reswait::scope` becomes an empty diagnostic scope; `ps5_spu_wakeup` stops incrementing per-thread sampled phases and atomic wakeup attribution counters; `ps5_worker_activity::register_spu` returns null, and all its guest-side callsites have null guards; the RSX direct recorder exits immediately.
- `PS5_RSX_WORDS_ACTIVE` and `PS5_RSX_CLASS_ACTIVE` now default to the common global diagnostics switch (OFF), eliminating their normally active sampled method-loop and register-bucket counters.
- `ps5_jit_name` is not called in the normal JIT compile path, avoiding its map insert and mutex acquisition. **No native guest JIT machine code, cache key or execution pointer changes.**
- The optional `spu_hot_cpu` scheduler setting relied on snapshots from the SIGUSR1 monitor. With diagnostics OFF it now explicitly warns once if requested and **does not** perform an unverified affinity change. To experiment with it, build with diagnostics ON. This is a behavior change only to an explicitly opt-in experimental mode, not its default (already OFF).

### Diagnostic build (ON)

- Re-enables the previous 4-second CPU, FPS, SPU and RSX debug reporting and probe semantics. Existing JIT sampling stays independently controlled by its own compile-time option.
- **This costs extra CPU** and should be used only for data collection. Do not compare an ON run's FPS uncritically to an OFF run without accounting for the observer effect. ON is *not* the same as enabling the SPU HOTJIT sampler, which remains OFF by default.
- JIT binary dumps remain opt-in through the separate RSX profiler flag; the default SPU HOTJIT diagnostics deliberately do not emit arbitrary executable JIT .bin files.

**Operational caveat:** Normal release no longer prints `PS5 FPS` and `PS5 CPU` records required by older log-based benchmark scripts. Use the separately built diagnostic variant when these measurements are needed, then restore release OFF. Do not mistake missing counters for zero game activity.

## 3. TLS target, initialization and fallback checks

The current WSL core build uses **`-march=znver2 -fno-emulated-tls -ftls-model=initial-exec`**; the PS5 title's `PS5_NATIVE_TLS:BOOL=ON`. Native TLS is used as host thread-local state, not as PS3 guest TLS memory, and does not replace directly passed JIT thread/local-store pointers.

Checks run offline:

- `port/tests/check-ps5-native-guest-tls-fastpath.py`: actual PS5-target compiler produced true ELF TLS with `R_X86_64_GOTTPOFF`, and hosted thread-guest-context isolation/switch/unbind tests passed. Existing source-level comparison was **9 vs 2** instructions for native TLS versus directly passed r13, and **11 vs 3** for LS byte read; no argument for replacing existing JIT pointers.
- **New** `port/tests/check-ps5-native-emulated-tls-modes.py` and `port/tests/ps5-native-vs-emulated-tls.cpp`: using the actual PS5-target Clang with true/native mode and **`-femulated-tls`** separately, validate TLS versus `__emutls_get_address` relocations. A host C++20 counterpart in both modes passes nonzero initial TLS values, thread isolation, constructor/destructor lifetime and alignment. The actual PS5 target rejects **64-byte TLS alignment** (maximum **32**), so the check was corrected to use `alignas(32)`. A hosted pass does **not** prove the PS5 loader correctly initializes each thread or releases TLS on exit.
- Both complete PS5 title builds invoked `app/ps5/tools/check-native-tls.py`, which checks the converted ELF's PT_TLS address, file/memory sizes, alignment, template bytes and writable file-backed PT_LOAD; also independently compared *every byte* of executable PT_LOAD to the title code mirror. No hardware thread-lifetime tests were done.

The **emulated-TLS fallback remains present** through the existing `PS5_NATIVE_TLS=OFF` title option and the `port/rpcs3-build.sh` no-extra-flags build recipe documented in `WSL_BUILD.md`. Neither recipe nor fallback source was removed or rewritten. The emulated-TLS **complete PS5 title was not rebuilt or run this turn**, so current full-title fallback correctness and relative performance remain unverified. Do **not** remove the emulated path simply because cross-compiled objects and hosted tests pass.

## 4. Direct PS5 machine-code evidence

`port/tests/check-ps5-release-probe-codegen.py` cross-compiles the **real header APIs** for SPU reservation waiting and page-notification sampling using the actual PS5 Prospero Clang with `-O3 -march=znver2` in both diagnostic modes. The deliberately small function `ps5_probe_guest_reservation` is:

| PS5-target diagnostic switch | Instructions for isolated probe |
| --- | ---: |
| 0 (release) | **2** |
| 1 (diagnostic) | **67** |

The OFF version is a minimal return stub. The ON version contains actual sample timing and counter machinery. This demonstrates effective *code elimination in an isolated hot path*, not an execution-time measurement, game workload profile, or FPS gain.

`port/tests/check-ps5-release-profile0074.py` validates exact source reversibility across all eight files, checks that watchdog SIGUSR2 and live tuning are preserved, and uses C++20 tests with the real SPU/RSX diagnostic headers under both compiled switches. OFF produced zero diagnostic counter updates; ON retained sampled counters, worker data and RSX method bucket data. **PASS**.

## 5. Full native PS5 builds, off/on, rollback

Both complete PS5 title builds and all **nine** title/package checks passed using the same RPCS3 LLVM22.1.8 native toolchain. Signed images/complete ELF/code mirrors were archived offline (no PS5 deployment):

| Mode | Signed executable SHA256 | Complete paired code-mirror SHA256 | PT_TLS |
| --- | --- | --- | --- |
| Release **OFF** | `755d783f6a30dd8df975df042ec612c7281fa64bb87c26d6bc5baa7ae9ec935f` | `28090ff0915b5dc50e62acc17e808441f9ed667caff163f82870b0323e5e450b` | template **128** / memory **15,088** / align **32** |
| Diagnostics **ON** | `98b483516ff4e1c3a64239502d92c3f989a8917f595ea415a3027b002a8300f2` | `5ddd5722c548368c0d837caabd14bcc670b75f338f10604a10983c69d8510634` | template **128** / memory **15,136** / align **32** |

The 48-byte smaller release PT_TLS memory image is consistent with removal of some diagnostic thread-local data, **not an FPS measurement**.

Archives:

- Release OFF: `/home/callum/work/cpu-plan-profile0074-release-off-20261031/`
- Diagnostics ON: `/home/callum/work/cpu-plan-profile0074-diagnostics-on-20261031/`

Following the ON build, the header was restored to **`PS5_RELEASE_PROFILE_ACTIVE=0`** and a full native title build rerun. Both signed executable/mirror hashes matched the first release-OFF build byte-for-byte. Exact source originals archived at `/home/callum/work/cpu-plan-release-profile0074-original-20261031/`; machine-readable evidence `results/cpu-plan-profile0074-20261031/manifest.json`.

**Source patch count is 74, not the installed console version.** No console connection, game load, process operation, file deployment, save, config or cache modification was performed. The last independently verified installed title remains the original patch0064 gate0 control from earlier, when both game and launcher were stopped.

## 6. Outstanding acceptance gates

1. **Native TLS correctness on console:** validate per-thread initial values, alignment and teardown under real PS5 loader/thread lifecycle, including host thread churn and cleanup; retain emulated fallback. An ELF PT_TLS check cannot establish complete runtime correctness.
2. **Native vs emulated performance:** only after both are independently correct on-console, compare matched builds and workloads; no speculative TLS FPS improvement claim.
3. **Observer-effect benchmark:** a representative non-GTA-IV game with identical scene/settings and warm cache; match release OFF against diagnostics ON, account for changed FPS-log availability and capture an independent frame-time source. Measure actual watchdog and sampling cost, frame-time p50/p95/p99, CPU occupancy, correctness, shutdown and boot time. Compare diagnostics mode **separately from** actual game optimisation candidates.
4. **Production default:** keep `PS5_RELEASE_PROFILE_ACTIVE=0`, `PS5_SPU_HOTJIT_ACTIVE=0`, experimental JIT/RSX scheduling/CPU-wait options disabled. If profiling distorts gameplay, report that fact and do not use its own CPU utilisation as definitive critical-path evidence.

**Section 5 conclusion:** The production profiling code was made default-OFF and its removal verified offline, but **the on-console performance and native/emulated TLS acceptance gates remain pending**. The entire CPU optimisation plan has an offline implementation/review checkpoint for Sections 1–5; none of the speculative performance candidates is automatically promoted to a default.
