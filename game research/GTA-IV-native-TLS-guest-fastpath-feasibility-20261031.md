# PS5 Native TLS as a guest-state fast-access mechanism — feasibility probe

**Date:** 2026-10-31. **Status:** OFFLINE PROTOTYPE VERIFIED; **no game-source integration or console deployment**. User proposed using host native TLS to cache the current guest PPU/SPU state. We tested actual PS5 compiler output and host-thread correctness before adding any guest recompiler change.

## Source audit: paths already optimized

- Guest PPU TLS is ordinary emulated PS3 memory, allocated by `rpcs3/Emu/Cell/Modules/sys_ppu_thread_.cpp`; `sys_initialize_tls` puts the PS3 guest TLS pointer in `ppu.gpr[13]`. The guest expects the exact PS3 address, system area, byte order, and guest thread behavior. A host TLS slot cannot replace that address.
- The *PPU LLVM recompiler* in `rpcs3/Emu/Cell/PPUTranslator.cpp` already receives a guest-thread context parameter (`m_thread = getArg(1)`) and a guest memory-base pointer (`m_base = getArg(3)`). Normal `ReadMemory` uses `GetMemory(addr)` = `m_base + addr` and recognizes guest r13 as TLS-related for some MMIO checks. No host TLS lookup is required to obtain those JIT arguments.
- The *SPU LLVM recompiler* in `rpcs3/Emu/Cell/SPULLVMRecompiler.cpp` receives `m_thread = getArg(0)` and a **direct SPU local-store pointer** `m_lsptr = getArg(1)`. Guest LS loads and stores are already native x86 memory operations derived from `m_lsptr + guest LS offset`. Making those access a newly cached host TLS pointer would add a lookup.
- The host's `thread_ctrl::get_current()` in `Utilities/Thread.h` **already returns the native `thread_local thread_base* g_tls_this_thread`**. It is set/cleared in `Utilities/Thread.cpp`. The PS5 runtime's native TLS is enabled with compiler flags `-fno-emulated-tls -ftls-model=initial-exec` and the deployed title was repeatedly verified with `PT_TLS` (128-byte template, 15,104-byte mem, align 32). A second host guest-current-thread cache would duplicate this storage unless profiling identifies a different expensive path.

## Actual PS5 compiler A/B instruction-generation experiment

Source: `port/tests/ps5-native-guest-tls-assembly-probe.cpp`. Reproducible validator: `python3 port/tests/check-ps5-native-guest-tls-fastpath.py` in WSL Ubuntu-24.04. Real toolchain: `/home/callum/work/ps5-rpcs3-app/.deps/native/ps5-payload-sdk/bin/prospero-clang++` (Clang 19.1.1, target `x86_64-sie-ps5`). Flags: `-std=c++20 -O3 -march=znver2 -fno-emulated-tls -ftls-model=initial-exec`.

Two equivalent guest-access patterns were compiled into an object for PS5 and disassembled with `llvm-objdump-19 --no-show-raw-insn -dr`. The TLS variable was confirmed as a true `TLS` ELF symbol, using `R_X86_64_GOTTPOFF` and FS-segment access, *not* `__emutls_get_address`.

| Access | Direct JIT argument | Native TLS cached guest pointer |
| --- | ---: | ---: |
| Read guest PPU register r13 | **2 machine instructions** | **9 machine instructions** |
| Read one guest SPU local-store byte | **3 machine instructions** | **11 machine instructions** |

Instruction counts are **whole-function disassembly counts**, including returns and null guards in the TLS implementation; they are not latency measurements and do not directly predict FPS. However, the native TLS form plainly performs extra GOT/FS/context loads compared with already available pointer parameters. The actual direct memory operations in the RPCS3 JIT are even more optimized at call sites when the compiler retains pointers in registers. Swapping direct JIT parameters for TLS would be an unjustified performance regression risk.

Proof of native TLS **correctness** is separate from benefit: `port/tests/check-ps5-native-guest-tls-isolation.cpp` compiled and executed successfully under host Clang++19. It checks initial unbound state, different guest states bound concurrently on separate host threads, switching guest contexts on one host thread, clearing TLS to prevent stale references, and matching results with direct pointer access. This demonstrates the mechanism is feasible, **not** that it is faster or safe to install in the actual RPCS3 dispatcher without precise transition coverage.

## Decision and next eligible use

**Use host native TLS for guest-state lookup only if a particular host-side C++ helper currently performs something slower than a TLS load** (e.g. a repeated map lookup/lock or avoidable thread-context discovery) and direct guest parameters cannot reasonably reach that helper. Bind/update on every relevant guest context entry and switch, clear before destruction and worker exit, handle reentrant callbacks/signal handlers, and verify PPU/SPU cross-thread behavior. Keep the path optional, test TLS on/off and run matched outdoor GTA IV FPS and critical-path tests before adopting.

**DO NOT redirect PPU `m_thread`/`m_base`, SPU `m_thread`/`m_lsptr`, or the PS3 guest `r13` value into new host TLS by default.** Existing direct pointers are already cheaper in the measured PS5 compiler output. Our next SPU target remains the actual machine-code cost and SPU/RSX frame dependency, not replacing guest TLS.

Files introduced here are **standalone test/probe files only**; no `port/rpcs3-latest.json` patch count changed, no RPCS3 source, generated console binary, save, cache, stage or PS5 installation changed. The last independently verified console state from the preceding test was original patch0064 gate0 control installed, GTA IV and launcher stopped. Always repeat a fresh full process check before any future executable swap.
