#!/usr/bin/env python3
"""Host compile/run smoke test for isolated PS5 SPU/RSX worker counters."""
from pathlib import Path
import subprocess
import tempfile
import textwrap

UPSTREAM = Path("/home/callum/work/rpcs3-latest/rpcs3")
HEADER = UPSTREAM / "Emu/RSX/ps5_worker_activity.h"


def main():
    if not HEADER.exists():
        raise FileNotFoundError(HEADER)
    with tempfile.TemporaryDirectory(prefix="ps5-worker-test-") as temp:
        root = Path(temp)
        (root / "util").mkdir()
        (root / "util/tsc.hpp").write_text(textwrap.dedent("""\
            #pragma once
            #include <cstdint>
            #include <atomic>
            namespace utils {
              inline std::atomic<std::uint64_t> tick{1000000};
              inline std::uint64_t get_tsc() { return tick.fetch_add(5000); }
            }
            """))
        (root / "test.cpp").write_text(textwrap.dedent(f"""\
            #define __PROSPERO__
            #include "{HEADER}"
            #include <cassert>
            using namespace ps5_worker_activity;
            int main() {{
              auto* first = register_spu(0x2000100);
              auto* second = register_spu(0x3000100);
              assert(first && second && first != second);
              assert(register_spu(0x2000100) == first);
              assert(register_spu(0) == nullptr);
              for (int i=0; i<10; ++i) record(first,stage::spu_gateway,utils::get_tsc());
              record(first,stage::spu_cpu_work,utils::get_tsc());
              record(second,stage::spu_gateway,utils::get_tsc());
              record_rsx(stage::rsx_fifo_running,utils::get_tsc());
              record_rsx(stage::rsx_fifo_empty,utils::get_tsc());
              const auto first_gateway = take(first->stats[0]);
              assert(first_gateway.sampled == 10);
              assert(first_gateway.total_tsc == 50000);
              assert(first_gateway.max_tsc == 5000);
              assert(take(first->stats[0]).sampled == 0);
              assert(take(first->stats[1]).sampled == 1);
              assert(take(second->stats[0]).sampled == 1);
              assert(take(rsx[static_cast<unsigned>(stage::rsx_fifo_running)]).sampled == 1);
              assert(take(rsx[static_cast<unsigned>(stage::rsx_fifo_empty)]).sampled == 1);
              for (unsigned i=0; i<62; ++i) assert(register_spu(0x5000000+i));
              assert(register_spu(0x6000000) == nullptr);
              assert(slot_overflow == 1);
              return 0;
            }}
            """))
        exe = root / "test"
        subprocess.run(["g++", "-std=c++20", "-O2", "-Wall", "-Wextra",
                        "-I", str(root), str(root / "test.cpp"),
                        "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("PASS: 64 SPU-ID slots, no allocation on zero ID, sampled gateway/CPU-work/RSX timing, atomic exchange, overflow reporting")


if __name__ == "__main__":
    main()
