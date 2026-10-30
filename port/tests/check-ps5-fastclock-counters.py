#!/usr/bin/env python3
"""Compile and exercise the PS5 fastclock diagnostic counters with stub OS calls.

No PS5 hardware needed. Checks batched clock calls and the three yield
branches count correctly, without altering timekeeping/yield semantics.
"""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "app/ps5/src/ps5_fastclock.c"

HARNESS = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <time.h>

uint64_t sceKernelGetTscFrequency(void) { return 1596300000ULL; }
int sceKernelClockGettime(clockid_t which, struct timespec *out)
{
    return clock_gettime(which, out);
}
int scePthreadYield(void) { return 0; }
int sceKernelUsleep(unsigned int us) { (void)us; return 0; }

int rpcs3ps5_clock_gettime(clockid_t clock, struct timespec *);
int rpcs3ps5_sched_yield(void);
void rpcs3ps5_fastclock_stats_take(uint64_t *, uint64_t *, uint64_t *, uint64_t *);

int main(void)
{
    struct timespec ts;
    for (int i = 0; i < 2300; ++i) {
        assert(rpcs3ps5_clock_gettime(CLOCK_MONOTONIC, &ts) == 0);
        assert(ts.tv_nsec >= 0 && ts.tv_nsec < 1000000000L);
    }
    for (int i = 0; i < 1024; ++i)
        assert(rpcs3ps5_sched_yield() == 0);

    uint64_t clocks = 0, spin = 0, os = 0, sleep = 0;
    rpcs3ps5_fastclock_stats_take(&clocks, &spin, &os, &sleep);
    assert(clocks == 2048); /* 1024 batched; 252 pending locally */
    assert(spin + os + sleep == 1024); /* 4 complete 256 batches */
    assert(spin + os + sleep > 0);

    rpcs3ps5_fastclock_stats_take(&clocks, &spin, &os, &sleep);
    assert(clocks == 0 && spin == 0 && os == 0 && sleep == 0);
}
'''

def main():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp)
        harness = target / "clock-harness.c"
        binary = target / "clock-harness"
        harness.write_text(HARNESS, encoding="utf8")
        subprocess.run(
            ["clang-19", "-std=c11", "-D_GNU_SOURCE", "-O2",
             str(SOURCE), str(harness), "-o", str(binary)],
            check=True,
        )
        subprocess.run([str(binary)], check=True)
        print("PASS: 2300 clocks -> 2048 batched; 1024 yields categorized; reset verified")

if __name__ == "__main__":
    main()
