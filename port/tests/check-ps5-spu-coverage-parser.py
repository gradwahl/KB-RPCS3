#!/usr/bin/env python3
"""Prove live SPU coverage, completed samples and legacy logs stay distinct."""
import importlib.util
import json
from pathlib import Path
import tempfile

script = Path(__file__).resolve().parents[2] / 'tools/gta4-worker-activity.py'
spec = importlib.util.spec_from_file_location('activity', script)
activity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(activity)


def cover(second, returned=False):
    return (f'00:00:{second:02d}.000 SYS: PS5 SPUCOVER: v2 id 0x2000100 '
            f'tasks 1 jit_tasks 1 gateway_entries 1 gateway_returns {int(returned)} '
            f'gateway_active {int(not returned)} gateway_age_us {0 if returned else second * 1000000}.000 '
            'cpu_work_entries 0 cpu_work_sample_active 0 cpu_work_sample_age_us 0.000 cpu_work_abandoned 0')


with tempfile.TemporaryDirectory(prefix='spu-coverage-parser-') as temp:
    stem = Path(temp) / 'capture'
    stem.with_suffix('.json').write_text(json.dumps({
        'valid': True, 'mode': 'B', 'resolution_scale': '150',
        'new_spu_compilations': 0, 'windows': 4, 'mean_window_fps': 25.0,
    }))
    fps = [f'00:00:{second:02d}.000 SYS: PS5 FPS: 25.0' for second in (0, 4, 8, 12, 16)]

    def analyse(extra):
        stem.with_suffix('.log').write_text('\n'.join(fps + extra) + '\n')
        return activity.analyse(stem)

    # A gateway started before capture and never returned. No fake completed
    # duration, no requirement to reach entry 256, no summing the live ages.
    result = analyse([cover(second) for second in (4, 8, 12, 16)])
    assert result['spu_live_coverage_valid']
    assert not result['spu_completed_timing_valid']
    assert not result['spu_measurement_valid']  # legacy completed-timing flag
    assert result['worker_activity']['spu'] == {}
    worker = result['spu_coverage']['0x02000100']
    assert worker['gateway_active_observations'] == 4
    assert worker['max_gateway_age_us'] == 16000000
    assert worker['gateway_entries_delta_between_reports'] == 0
    assert worker['last']['gateway_entries'] == 1
    assert 'live gateway/cpu_work coverage is available' in result['spu_measurement_warning']

    sample = ('00:00:16.000 SYS: PS5 WORKER: group spu id 0x2000100 kind 0 '
              'sample_n 1 avg_us 2000.000 max_us 2000.000 sampled_sum_us 2000.000')
    result = analyse([cover(16, returned=True), sample])
    assert result['spu_completed_timing_valid']
    assert result['worker_activity']['spu']['0x02000100']['spu_gateway']['sample_probability'] == '1/1'
    assert not result['spu_coverage']['0x02000100']['last']['gateway_active']

    # Old captures retain their old sampling rate and no inferred live data.
    result = analyse([sample])
    assert result['spu_completed_timing_valid']
    assert not result['spu_live_coverage_valid']
    assert result['spu_coverage'] == {}
    assert result['worker_activity']['spu']['0x02000100']['spu_gateway']['sample_probability'] == '1/256'

    result = analyse([cover(16), '00:00:16.000 SYS: PS5 SPUCOVER2: zero_id_registrations 1'])
    assert result['spu_zero_id_registrations'] == 1
    assert not result['spu_live_coverage_valid']
    result = analyse([cover(16), '00:00:16.000 SYS: PS5 WORKER2: lost_spu_slot_allocations 1'])
    assert not result['spu_live_coverage_valid']

    try:
        analyse([])
    except ValueError:
        pass
    else:
        raise AssertionError('Missing coverage silently accepted')

print('PASS: live-only gateway, cumulative counts/age, completed timings, legacy sampling, zero-ID/overflow and missing-data handling')
