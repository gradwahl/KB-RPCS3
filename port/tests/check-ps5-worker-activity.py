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
            std::uint64_t enter_from_other_translation_unit(worker_slot*);
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
              assert(zero_id_registrations == 1);
              // A first, long-lived gateway is visible before ANY return.
              const auto gateway = enter_from_other_translation_unit(first);
              auto live = observe(*first);
              assert(live.tasks == 1 && live.jit_tasks == 1);
              assert(live.gateway_entries == 1 && live.gateway_returns == 0);
              assert(live.gateway_active == 1 && live.gateway_age_tsc > 0);
              assert(take(first->stats[0]).sampled == 0);
              // The very first cpu_work is sampled independently of the
              // emulator's pre-existing iteration counter, then 1/1024.
              auto work = begin_cpu_work(0x2000100);
              assert(work.slot == first && work.start != 0);
              live = observe(*first);
              assert(live.cpu_work_entries == 1 && live.cpu_work_sample_active);
              assert(live.cpu_work_sample_age_tsc > 0);
              end_cpu_work(work);
              for (int i=0; i<1023; ++i) {{
                work = begin_cpu_work(0x2000100);
                assert(work.start == 0);
                end_cpu_work(work);
              }}
              work = begin_cpu_work(0x2000100);
              assert(work.start != 0);
              end_cpu_work(work);
              assert(observe(*first).cpu_work_entries == 1025);
              assert(take(first->stats[1]).sampled == 2);
              end_gateway(first, gateway);
              live = observe(*first);
              assert(live.gateway_entries == 1 && live.gateway_returns == 1);
              assert(!live.gateway_active && live.gateway_age_tsc == 0);
              assert(take(first->stats[0]).sampled == 1);
              // Simulate g_escape bypassing end_cpu_work: the gateway
              // boundary discards the abandoned interval, never timing it
              // as completed work or leaving a permanently active probe.
              const auto next_gateway = begin_gateway(second);
              work = begin_cpu_work(0x3000100);
              assert(work.start && observe(*second).cpu_work_sample_active);
              end_gateway(second, next_gateway);
              live = observe(*second);
              assert(!live.cpu_work_sample_active && live.cpu_work_abandoned == 1);
              assert(take(second->stats[1]).sampled == 0);
              assert(begin_cpu_work(0).slot == nullptr);
              // Null slots (registration failure) never touch memory.
              begin_task(nullptr, true);
              end_gateway(nullptr, begin_gateway(nullptr));
              end_cpu_work({{}});
              return 0;
            }}
            """))
        (root / "other.cpp").write_text(textwrap.dedent(f"""\
            #define __PROSPERO__
            #include "{HEADER}"
            std::uint64_t enter_from_other_translation_unit(ps5_worker_activity::worker_slot* slot) {{
              ps5_worker_activity::begin_task(slot, true);
              return ps5_worker_activity::begin_gateway(slot);
            }}
            """))
        exe = root / "test"
        subprocess.run(["g++", "-std=c++20", "-O2", "-Wall", "-Wextra",
                        "-I", str(root), str(root / "test.cpp"), str(root / "other.cpp"),
                        "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("PASS: 64 SPU-ID slots, no allocation on zero ID, sampled gateway/CPU-work/RSX timing, atomic exchange, overflow, first/live gateway coverage, first CPU-work sample, nonlocal-escape cleanup")


if __name__ == "__main__":
    main()
