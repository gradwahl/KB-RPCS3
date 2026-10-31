#!/usr/bin/env python3
"""Parse patch0063 native LLVM helper snapshots and cumulative sampled counters.

Outside a measured helper is unresolved, not proof of pure guest JIT time.
"""
import argparse
from collections import Counter, defaultdict
import importlib.util
import json
from pathlib import Path
import re

spec = importlib.util.spec_from_file_location('worker_activity', Path(__file__).with_name('gta4-worker-activity.py'))
worker_activity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker_activity)
KINDS = dict(enumerate(('rdch', 'wrch', 'mfc_cmd', 'channel_wait', 'rchcnt',
                        'events', 'read_dec', 'list_unstall', 'stop', 'queued_mfc')))
LIVE = re.compile(r'PS5 SPUHELP: v1 id 0x([0-9a-fA-F]+) active ([01]) stable ([01]) kind (\d+) arg (\d+) age_us ([\d.]+) nested (\d+)')
STATS = re.compile(r'PS5 SPUHELPSTAT: v1 id 0x([0-9a-fA-F]+) kind (\d+) entries (\d+) returns (\d+) escapes (\d+) normal_n (\d+) normal_sum_us ([\d.]+) normal_max_us ([\d.]+) escape_n (\d+) escape_sum_us ([\d.]+) escape_max_us ([\d.]+)')


def analyse(stem):
    base = worker_activity.analyse(stem)
    start, stop = base['capture_log_window_seconds']
    live = defaultdict(list)
    stats = defaultdict(list)
    text = stem.with_suffix('.log').read_text(encoding='utf8', errors='replace')
    for line in text.splitlines():
        if 'PS5 SPUHELP' not in line:
            continue
        if not start <= worker_activity.time_of(line) <= stop:
            continue
        if match := LIVE.search(line):
            guest, active, stable, kind, arg, age, nested = match.groups()
            kind = int(kind)
            if kind not in KINDS:
                raise ValueError(f'Unknown helper kind {kind}')
            live[int(guest, 16)].append({
                'active': bool(int(active)), 'stable': bool(int(stable)),
                'kind': KINDS[kind], 'arg': int(arg), 'age_us': float(age),
                'nested_suppressed_cumulative': int(nested),
            })
        elif match := STATS.search(line):
            fields = match.groups()
            guest, kind = int(fields[0], 16), int(fields[1])
            if kind not in KINDS:
                raise ValueError(f'Unknown helper kind {kind}')
            stats[(guest, kind)].append({
                'entries': int(fields[2]), 'returns': int(fields[3]), 'escapes': int(fields[4]),
                'normal_n': int(fields[5]), 'normal_sum_us': float(fields[6]),
                'normal_max_us': float(fields[7]), 'escape_n': int(fields[8]),
                'escape_sum_us': float(fields[9]), 'escape_max_us': float(fields[10]),
            })
    summaries = {}
    for guest in sorted(set(live) | {guest for guest, _ in stats}):
        observed = live[guest]
        phases = Counter('unstable' if not row['stable'] else
                         row['kind'] if row['active'] else 'outside_measured_helpers'
                         for row in observed)
        helpers = {}
        for (worker, kind), rows in sorted(stats.items()):
            if worker != guest:
                continue
            first, last = rows[0], rows[-1]
            keys = ('entries', 'returns', 'escapes', 'normal_n', 'normal_sum_us',
                    'escape_n', 'escape_sum_us')
            delta = {key: last[key] - first[key] for key in keys}
            if any(value < 0 for value in delta.values()):
                raise ValueError('Helper counters reset inside measurement window')
            helpers[KINDS[kind]] = {
                'reports': len(rows), 'last_cumulative': last,
                'delta_between_reports': delta,
                'normal_sample_mean_us_between_reports': (
                    delta['normal_sum_us'] / delta['normal_n'] if delta['normal_n'] else None),
                'escape_sample_mean_us_between_reports': (
                    delta['escape_sum_us'] / delta['escape_n'] if delta['escape_n'] else None),
                'sampling': 'first outer invocation, then every 1024th per kind',
            }
        summaries[f'0x{guest:08x}'] = {
            'live_reports': len(observed), 'phase_observations': dict(phases),
            'last_live_snapshot': observed[-1] if observed else None,
            'maximum_observed_active_age_us': max(
                (row['age_us'] for row in observed if row['stable'] and row['active']), default=0),
            'helpers': helpers,
        }
    return {
        'capture': stem.name, 'fps_time_weighted': base['fps_time_weighted'],
        'fps_window_mean': base['fps_window_mean'],
        'capture_log_window_seconds': [start, stop],
        'new_spu_compilations': base['new_spu_compilations'],
        'spu_live_coverage_valid': base['spu_live_coverage_valid'],
        'registration_errors': base['spu_zero_id_registrations'] + base['worker_slot_allocation_overflow'],
        'helper_reporting_present': bool(live),
        'helper_activity_observed': bool(stats),
        'workers': summaries,
        'old_heavy_diagnostics_absent': base['old_heavy_diagnostics_absent'],
        'frame_event_tracer_disabled': base['frame_event_tracer_disabled'],
        'warning': None if live else 'No helper boundary reports: build coverage or runtime path unverified',
        'limitations': [
            'Watchdog phase counts are sparse point observations, not time fractions or CPU utilisation',
            'Outside measured helpers is unresolved: guest JIT, uninstrumented host helpers, waits and descheduling may remain',
            'Sampled durations include nested work/waits/descheduling and can span capture boundaries',
            'Use report-to-report deltas, never sum cumulative sample counters or live ages across rows',
            'Normal/escape samples are first then deterministic 1/1024, not a random sample',
            'Snapshot fields are approximate and not a transactional frame timeline',
            'Diagnostic overhead and a frame-critical causal bottleneck are not established by these counters',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    stem = args.capture.with_suffix('')
    result = analyse(stem)
    output = args.output or stem.with_name(stem.name + '-spu-helpers').with_suffix('.json')
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf8')
    print(json.dumps(result, indent=2))
    print('Saved', output)


if __name__ == '__main__':
    main()
