# CPU optimisation plan — Section 4 JIT compilation contention audit

**Date:** 31 October 2026  
**Status:** Offline source audit, reversible default-OFF experiment, host tests, and native PS5 OFF/ON builds complete. **No live compilation contention, cold/warm duration, FPS, or p95/p99 benefit has been measured.** GTA IV-specific work remains paused.

## 1. Separate compilation systems — don't conflate the worker limits

| Workload | Source | Current PS5 source behavior | Experimental impact |
| --- | --- | --- | --- |
| PPU LLVM compilation | `rpcs3/Emu/Cell/PPUThread.cpp`: `jit_core_allocator` / module queue | `apply_defaults_values()` sets `g_cfg.core.llvm_threads=10`. Semaphore and module queue limit further constrain running work; CPU count, module size and memory requirements also matter. | **None.** Do not change `llvm_threads` based on SPU runtime observations. |
| SPU initial cache recompiler / preload | `SPUCommonRecompiler.cpp`: `spu_cache::initialize` | Thread group `SPU Worker `, count `min(rpcs3::utils::get_max_threads(), pending programs)`; builds cached SPU functions during loading. | **None.** Loading-screen throughput remains unchanged. |
| SPU live runtime recompilation | `SPUCommonRecompiler.cpp`: `spu_llvm` and `spu_llvm_worker` | Separate `SPUW.` thread pool. Worker count 1 below six logical CPUs, 2 for 6–11, `hc-12+3` for 12+; with 13 allowed logical CPUs this calculates **4 live workers**. | **Only this pool**, with an opt-in cap of 2 for a future comparison. |
| Vulkan shader compilation | `rpcs3/ps5/ps5_frontend.cpp`: `shader_mode::async_recompiler` | Asynchronous shader compilation; separate from LLVM CPU worker setting and SPUW pool. | **None**. |

The first-stage `llvm_threads=10` is not the runtime SPU worker count. In particular, lowering it is not a general fix for SPU compiler interference. The live pool already prioritizes candidate programs using a sample-count map and can enqueue many programs concurrently; changing worker concurrency can reduce competition or slow the first call to a previously unseen block. The latter is a correctness/performance regression risk that deserves a cold-vs-warm workload test.

## 2. Guest JIT cache re-use and safe invalidation audit

`SPUCommonRecompiler.cpp` implements an SPU **program** cache under the PPU title-specific cache directory named `spu-<block-size>-v1-tane.dat`. It reads records containing guest address, size and an optional CRC16; it rejects address/size combinations exceeding `SPU_LS_SIZE`, skips invalid CRC records when a CRC is present, and deduplicates equivalent programs after loading. The absence of a CRC can be accepted for legacy compatibility, so this format should **not** be characterized as a complete proof of integrity. The cache file records guest instruction data, not a fully validated, version-specific native executable. We have not performed a full review of all PPU/SPU/Vulkan cache invalidation paths and must not assume that naming alone guarantees revision safety.

Runtime compilation in `SPULLVMRecompiler.cpp` uses `spu_runtime::add_empty` to deduplicate identical guest SPU programs; if the entry differs only by the requested start within an identical block, callers can wait for an existing compiled instance. Hashes are derived from the instruction data. No duplicate elimination, cache keys, record compatibility or native code semantics were altered by patch 0073.

**Not yet established:** exact per-game cold/warm cache hit rates, revision invalidation across all LLVM/backend/settings combinations, or whether shader compilation dominates specific frame stalls. Do not delete caches merely to produce a benchmark unless the user explicitly authorizes an isolated disposable test profile.

## 3. Patch 0073 — *live* SPU worker concurrency cap, default OFF

Reversible patch `port/rpcs3-latest-patches/0073-PS5-opt-in-cap-live-SPU-LLVM-compile-workers.patch` adds `rpcs3/Emu/Cell/ps5_spu_live_compile_workers.h` with **`PS5_SPU_LIVE_JIT_WORKER_CAP=0` by default**.

The cap applies **only** when compiling for PS5 and the flag is nonzero, just after the `SPUW.` worker count calculation and before its per-worker queues and thread group are constructed. The optional two-worker diagnostic changes `4 → 2` when the title has 13 logical CPUs. Each worker still receives the original program queue task, compiles it using the same recompiler, and patches the original trampoline in the original way. The cap is restricted to 0–32, never reduces a pool to zero, and is **not adaptive**. It does **not** change PPU LLVM workers, loading-stage `SPU Worker ` precompilation, renderer shader workers, guest SPU execution, priorities, caching, program hashes, or JIT code generation.

With the flag OFF, the compiler uses the original code path. We have **not** promoted a lower worker count to a default.

**Host validation:** `port/tests/check-ps5-jit-workers0073.py` checks exact source hashes, complete patch reverse/forward replay and source isolation to the live SPU worker context. It compiles and runs Clang19 C++20 tests for caps 0, 1, 2, 4 and 32, across host logical counts 1, 5, 6, 11, 12, 13, 16 and 28. Verifies `13 → 4` with default0 and `13 → 2` with cap2, no zero workers, and no changes to boot/precompiler calculation. PASS.

## 4. Native PS5 builds and rollback

Both full native PS5 title builds passed nine package checks, native TLS and signed executable generation:

| Build | Signed executable SHA256 | Paired code mirror SHA256 |
| --- | --- | --- |
| **Default OFF**, original four-worker policy | `039a2e99ac33f21f7ca2d6e6da0610d9b3718963ee789931b393f72a5effcc22` | `91a6e9a59a0426549dd37758d1ef818a75294d1b328d3b536ba4b344e2f599f2` |
| Diagnostic **cap=2** | `af4ee9369f022b1c8963c341019f6d58b4ef89ffd9d71fc2df053bee58635690` | `7f66e09ecad2678b81ba1bf442a9e2184117284e8e1bcf697c08cfa33aec27c6` |

The cap2 diagnostic ELF's entire executable PT_LOAD was independently checked against the complete code-mirror payload and native TLS segment (template **128 bytes**, memory **15,136 bytes**, alignment **32 bytes**). Its `eboot.bin`, `eboot.elf` and mirror are archived **offline only** at `/home/callum/work/cpu-plan-jit0073-cap2-diagnostic-20261031/`.

Afterward the source header was restored to `PS5_SPU_LIVE_JIT_WORKER_CAP=0` and the title fully rebuilt. Both normal OFF hashes matched the first OFF build *exactly*. No console read/write, staging, reboot, game, save, settings or cache change was performed. The installed PS5 title remains last independently verified as original matched patch0064 gate0, not patch0073. Selected WSL patch source count is **73**.

Source originals preserved at `/home/callum/work/cpu-plan-jit-workers0073-original-20261031/`. Full machine-readable manifest: `results/cpu-plan-jit-workers0073-20261031/manifest.json`.

## 5. Next acceptance gates

Before performance adoption, a representative **non-GTA-IV** gameplay comparison must:

1. Measure **cold-start** compilation count/duration and **warmed** compilation count separately, with identical versions/settings/scene. Distinguish PPU module, SPU boot cache, SPUW live, and shader compilation counts. Do not compare unlike cache states.
2. Verify any `SPUW.` CPU use and actually new guest SPU blocks during gameplay. If the live compiler pool is idle, the cap cannot explain a frame-time improvement; skip the test or choose a demonstrably busy workload.
3. Compare default OFF (= four live workers on the observed 13 logical CPUs) to cap2 on the **same warmed gameplay route**, A/B/A or repeated matched runs. Track mean FPS, 1% lows, frame-time p50/p95/p99, SPU+PPU+RSX CPU occupancy, block compile latency and startup time.
4. Validate delayed compilation does not stall guest progress, inflate loading times, exhaust memory, lose cached code, or prevent shutdown. Compare cache hit/recompile changes across separately versioned/isolated profiles without touching live game saves.
5. Revert to OFF if there is no reproducible benefit or if any game correctness or load-time regression exceeds the accepted margin. Only then consider an **adaptive** worker policy responding to actual measured SPU execution occupancy (rather than blindly reducing a global default).

**Section 4 status:** Offline candidate implemented and validated. **The CPU contention/performance acceptance gate remains pending** until representative actual hardware tests are run. No speedup is claimed.
