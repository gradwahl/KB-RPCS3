#!/usr/bin/env python3
"""Check helper point observations and cumulative sample delta interpretation."""
import importlib.util
import json
from pathlib import Path
import tempfile

script = Path(__file__).resolve().parents[2] / 'tools/gta4-spu-helpers.py'
spec = importlib.util.spec_from_file_location('helpers', script)
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)

with tempfile.TemporaryDirectory(prefix='helper-parser-') as temp:
    stem = Path(temp) / 'capture'
    stem.with_suffix('.json').write_text(json.dumps({
        'valid': True, 'mode': 'B', 'resolution_scale': '150',
        'new_spu_compilations': 0, 'windows': 4, 'mean_window_fps': 25.0,
    }))
    fps = [f'00:00:{t:02d}.000 SYS: PS5 FPS: 25.0' for t in (0, 4, 8, 12, 16)]
    cover = [f'00:00:{t:02d}.000 SYS: PS5 SPUCOVER: v2 id 0x100 tasks 1 jit_tasks 1 '
             f'gateway_entries 1 gateway_returns 0 gateway_active 1 gateway_age_us {t * 1000000}.0 '
             'cpu_work_entries 0 cpu_work_sample_active 0 cpu_work_sample_age_us 0.0 cpu_work_abandoned 0'
             for t in (4, 8, 12, 16)]

    def live(t, active, stable, kind, age):
        return (f'00:00:{t:02d}.000 SYS: PS5 SPUHELP: v1 id 0x100 active {active} '
                f'stable {stable} kind {kind} arg 29 age_us {age}.0 nested 0')

    def stats(t, entries, normal_n, normal_sum, escapes, escape_n, escape_sum):
        return (f'00:00:{t:02d}.000 SYS: PS5 SPUHELPSTAT: v1 id 0x100 kind 0 entries {entries} '
                f'returns {entries - escapes} escapes {escapes} normal_n {normal_n} '
                f'normal_sum_us {normal_sum}.0 normal_max_us 10.0 '
                f'escape_n {escape_n} escape_sum_us {escape_sum}.0 escape_max_us 50.0')

    def analyse(extra):
        stem.with_suffix('.log').write_text('\n'.join(fps + cover + extra) + '\n')
        return helpers.analyse(stem)

    result = analyse([
        live(4, 1, 1, 0, 100), live(8, 0, 1, 0, 0),
        live(12, 1, 0, 0, 99999), live(16, 1, 1, 0, 9000),
        stats(4, 1000, 1, 10, 0, 0, 0), stats(16, 3000, 3, 30, 1, 1, 50),
    ])
    assert result['helper_reporting_present'] and result['helper_activity_observed']
    assert result['spu_live_coverage_valid'] and result['fps_time_weighted'] == 25.0
    worker = result['workers']['0x00000100']
    assert worker['phase_observations'] == {'rdch': 2, 'outside_measured_helpers': 1, 'unstable': 1}
    assert worker['maximum_observed_active_age_us'] == 9000
    sample = worker['helpers']['rdch']
    assert sample['delta_between_reports']['entries'] == 2000
    assert sample['delta_between_reports']['normal_sum_us'] == 20
    assert sample['normal_sample_mean_us_between_reports'] == 10
    assert sample['escape_sample_mean_us_between_reports'] == 50
    assert sample['last_cumulative']['normal_sum_us'] == 30

    # A long live helper needs no completed samples to be visible.
    result = analyse([live(16, 1, 1, 3, 90000000)])
    assert result['helper_reporting_present'] and not result['helper_activity_observed']
    assert result['workers']['0x00000100']['phase_observations'] == {'channel_wait': 1}

    # A legacy/coverage-only log is not silently classified as pure JIT.
    result = analyse([])
    assert not result['helper_reporting_present'] and result['warning']
    assert result['workers'] == {}
    result = analyse([stats(16, 20, 1, 10, 0, 0, 0)])
    assert result['workers']['0x00000100']['helpers']['rdch']['normal_sample_mean_us_between_reports'] is None

    for bad in ([live(16, 1, 1, 99, 0)],
                [stats(4, 30, 3, 30, 0, 0, 0), stats(16, 20, 2, 20, 0, 0, 0)]):
        try:
            analyse(bad)
        except ValueError:
            pass
        else:
            raise AssertionError('Unknown kind or counter reset accepted')

print('PASS: sparse helper/outside/unstable observations, live-only coverage, cumulative sample deltas, normal/escape separation, legacy/missing data and reset guards')
