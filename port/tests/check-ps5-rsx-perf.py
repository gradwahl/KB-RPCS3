#!/usr/bin/env python3
"""Compile/run the PS5 RSX instrumentation header on host and verify counters.

The test does not emulate the PS5 clock shim; it verifies atomic aggregation,
scope elapsed-time accumulation, counter consumption and cross-TU sharing.
"""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HEADER_DIR = Path("/home/callum/work/rpcs3-latest/rpcs3/Emu/RSX")

def main():
    assert (HEADER_DIR / "ps5_rsx_perf.h").is_file()
    with tempfile.TemporaryDirectory() as tmp:
        first = Path(tmp) / "one.cpp"
        second = Path(tmp) / "two.cpp"
        first.write_text(r'''
#include "ps5_rsx_perf.h"
#include <cassert>
#include <thread>
#include <chrono>
void add_from_other_translation_unit();
int main()
{
    using namespace ps5_rsx_perf;
    { timer measured(stage::vertex_upload, 2048); }
    add_from_other_translation_unit();
    auto x = take(stage::vertex_upload);
    assert(x.calls == 2 && x.bytes == 3072);
    assert(x.ns > 0 && x.ns < 1000000000ull);
    auto reset = take(stage::vertex_upload);
    assert(reset.calls == 0 && reset.bytes == 0 && reset.ns == 0);
    auto empty = take(stage::dma_sync);
    assert(empty.calls == 0 && empty.ns == 0);
    record(stage::fifo_running_sample, 42);
    auto fifo = take(stage::fifo_running_sample);
    assert(fifo.calls == 1 && fifo.ns == 42);
}
''')
        second.write_text(r'''
#include "ps5_rsx_perf.h"
void add_from_other_translation_unit()
{
    ps5_rsx_perf::record(ps5_rsx_perf::stage::vertex_upload, 10, 1024);
}
''')
        output = Path(tmp) / "test-perf"
        subprocess.run(["clang++-19", "-std=c++20", "-O2", "-D__PROSPERO__",
                        "-I", str(HEADER_DIR), str(first), str(second),
                        "-pthread", "-o", str(output)], check=True)
        subprocess.run([str(output)], check=True)
        print("PASS: two-TU PS5 profiling header, atomic accumulation, duration, and reset")

if __name__ == "__main__":
    main()
