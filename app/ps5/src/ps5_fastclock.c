/*
 * RPCS3 PS5 - clock_gettime and sched_yield without a system call, bound in place of the system's by
 * tools/link-title.sh (--defsym, kept local).
 *
 * Every system call costs ~1 us on the console (with the jailbreak's kernel patches) and sched_yield ~28 us
 * (tools/syscallbench, 2026-10-07); a PC answers both in well under a microsecond. RPCS3 reads the
 * monotonic clock and yields in its wait loops all the time: the SPU threads of GTA IV spent much of their
 * samples in sched_yield and the RSX thread in clock_gettime (2026-10-08 profile).
 *
 *  - The monotonic clocks come from the invariant TSC (rdtsc, ~11 ns), anchored once to the system's
 *    monotonic clock (sceKernelClockGettime: the same clock under the name not rebound here).
 *  - sched_yield / pthread_yield spin ~2 us with pause (the caller re-checks what it waits for sooner), and
 *    in a run of calls every fourth is the real yield (scePthreadYield); after 0.5 ms of yielding the thread
 *    sleeps (~100 us) instead, leaving its core to the busy thread beside it.
 * Other clocks (realtime, CPU time) go to the system as before.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#include <stdatomic.h>
#include <stdint.h>
#include <time.h>

#define PS5_RSX_PERF_ACTIVE 0

int sceKernelClockGettime(clockid_t clock, struct timespec *ts);
uint64_t sceKernelGetTscFrequency(void);

static inline uint64_t tsc_now(void)
{
    uint32_t lo, hi;
    __asm__ volatile("rdtsc" : "=a"(lo), "=d"(hi));
    return ((uint64_t)hi << 32) | lo;
}

static inline void cpu_relax(void)
{
    __asm__ volatile("pause" ::: "memory");
}

/* 0: not yet, 1: in progress, 2: ready */
#if PS5_RSX_PERF_ACTIVE
/* Diagnostic call counts use thread-local batches to avoid an atomic
 * increment on every fast-clock call or yield. Totals may lag by up to
 * 1023 clock calls and 255 yield decisions PER THREAD at report time.
 * These are global (all RPCS3 threads), not RSX-exclusive counts. */
static _Atomic uint64_t g_stat_clock_calls, g_stat_yield_spin;
static _Atomic uint64_t g_stat_yield_os, g_stat_yield_sleep;
static _Thread_local unsigned t_clock_batch, t_yield_batch;
static _Thread_local unsigned t_spin_batch, t_os_batch, t_sleep_batch;

static inline void ps5_clock_count(void)
{
    if (++t_clock_batch == 1024) {
        t_clock_batch = 0;
        atomic_fetch_add_explicit(&g_stat_clock_calls, 1024, memory_order_relaxed);
    }
}

static inline void ps5_yield_count(unsigned type)
{
    if (type == 0) ++t_spin_batch;
    else if (type == 1) ++t_os_batch;
    else ++t_sleep_batch;
    if (++t_yield_batch == 256) {
        atomic_fetch_add_explicit(&g_stat_yield_spin, t_spin_batch, memory_order_relaxed);
        atomic_fetch_add_explicit(&g_stat_yield_os, t_os_batch, memory_order_relaxed);
        atomic_fetch_add_explicit(&g_stat_yield_sleep, t_sleep_batch, memory_order_relaxed);
        t_yield_batch = t_spin_batch = t_os_batch = t_sleep_batch = 0;
    }
}

void rpcs3ps5_fastclock_stats_take(uint64_t *clock_calls, uint64_t *spin,
                                   uint64_t *os_yield, uint64_t *sleep_calls)
{
    *clock_calls = atomic_exchange_explicit(&g_stat_clock_calls, 0, memory_order_relaxed);
    *spin = atomic_exchange_explicit(&g_stat_yield_spin, 0, memory_order_relaxed);
    *os_yield = atomic_exchange_explicit(&g_stat_yield_os, 0, memory_order_relaxed);
    *sleep_calls = atomic_exchange_explicit(&g_stat_yield_sleep, 0, memory_order_relaxed);
}

#endif // PS5_RSX_PERF_ACTIVE
static atomic_int g_state;
static uint64_t g_base_tsc, g_base_ns, g_freq;

static int anchor(void)
{
    int expected = 0;
    if (atomic_compare_exchange_strong(&g_state, &expected, 1)) {
        struct timespec ts;
        const uint64_t freq = sceKernelGetTscFrequency();
        if (freq < 100000000ull || sceKernelClockGettime(CLOCK_MONOTONIC, &ts) != 0) {
            atomic_store(&g_state, 3); /* unusable: the system answers */
            return 0;
        }
        g_base_tsc = tsc_now();
        g_base_ns = (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
        g_freq = freq;
        atomic_store_explicit(&g_state, 2, memory_order_release);
        return 1;
    }
    while ((expected = atomic_load_explicit(&g_state, memory_order_acquire)) == 1)
        cpu_relax();
    return expected == 2;
}

static int is_monotonic(clockid_t clock)
{
    switch (clock) {
    case CLOCK_MONOTONIC:
#ifdef CLOCK_MONOTONIC_PRECISE
    case CLOCK_MONOTONIC_PRECISE:
#endif
#ifdef CLOCK_MONOTONIC_FAST
    case CLOCK_MONOTONIC_FAST:
#endif
#ifdef CLOCK_UPTIME
    case CLOCK_UPTIME:
#endif
#ifdef CLOCK_UPTIME_PRECISE
    case CLOCK_UPTIME_PRECISE:
#endif
#ifdef CLOCK_UPTIME_FAST
    case CLOCK_UPTIME_FAST:
#endif
        return 1;
    default:
        return 0;
    }
}

int rpcs3ps5_clock_gettime(clockid_t clock, struct timespec *ts)
{
#if PS5_RSX_PERF_ACTIVE
    ps5_clock_count();
#endif
    if (!ts || !is_monotonic(clock) || (atomic_load_explicit(&g_state, memory_order_acquire) != 2 && !anchor()))
        return sceKernelClockGettime(clock, ts);
    const uint64_t ticks = tsc_now() - g_base_tsc;
    const uint64_t ns = g_base_ns + (uint64_t)((unsigned __int128)ticks * 1000000000ull / g_freq);
    ts->tv_sec = (time_t)(ns / 1000000000ull);
    ts->tv_nsec = (long)(ns % 1000000000ull);
    return 0;
}

int scePthreadYield(void);

/* A thread that keeps yielding (an idle wait loop) gives its core away every fourth call: RPCS3 runs more
 * busy threads than a title has cores, and pure spinning kept the RSX threads at 100% of theirs (GTA IV,
 * 2026-10-08) */
static _Thread_local uint64_t t_last_yield, t_burst_start;
static _Thread_local unsigned t_burst;

int sceKernelUsleep(unsigned int microseconds);

int rpcs3ps5_sched_yield(void)
{
    if (atomic_load_explicit(&g_state, memory_order_acquire) != 2 && !anchor()) {
        #if PS5_RSX_PERF_ACTIVE
        ps5_yield_count(1);
        #endif
        return scePthreadYield();
    }
    const uint64_t now = tsc_now();
    if (now - t_last_yield < g_freq / 10000) { /* calls within 100 us of each other: one idle stretch */
        t_burst++;
    } else {
        t_burst = 0;
        t_burst_start = now;
    }
    /* Idle for over half a millisecond (an RSX thread with nothing to draw): really sleep, so the core's other
     * thread (often an SPU thread) runs at full speed; the console's shortest sleep is ~100 us */
    if (now - t_burst_start > g_freq / 2000) {
        #if PS5_RSX_PERF_ACTIVE
        ps5_yield_count(2);
        #endif
        sceKernelUsleep(1);
        t_last_yield = tsc_now();
        return 0;
    }
    if (t_burst % 4 == 3) {
        #if PS5_RSX_PERF_ACTIVE
        ps5_yield_count(1);
        #endif
        scePthreadYield();
        t_last_yield = tsc_now();
        return 0;
    }
    #if PS5_RSX_PERF_ACTIVE
    ps5_yield_count(0);
    #endif
    const uint64_t until = now + g_freq / 500000; /* 2 us */
    do
        cpu_relax();
    while (tsc_now() < until);
    t_last_yield = tsc_now();
    return 0;
}

int rpcs3ps5_pthread_yield(void)
{
    return rpcs3ps5_sched_yield();
}
