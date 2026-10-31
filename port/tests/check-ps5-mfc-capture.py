#!/usr/bin/env python3
"""Prevent wrong-build or profiler-contaminated MFC timer captures."""
import importlib.util
from pathlib import Path

script = Path(__file__).resolve().parents[2] / 'tools/gta4-scheduler-ab.py'
spec = importlib.util.spec_from_file_location('capture', script)
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)
for mode in (0, 1):
    text = f'Core:\n  Enable Performance Report: false\nPS5 MFCMETER: gate {mode} helper_probes 0\n'
    assert not capture.mfc_meter_errors(text, mode)
    assert capture.mfc_meter_errors(text, 1-mode)
    assert capture.mfc_meter_errors(text.replace('helper_probes 0', 'helper_probes 1'), mode)
    assert capture.mfc_meter_errors(text.replace('Report: false', 'Report: true'), mode)
    assert capture.mfc_meter_errors(text + 'PS5 SPUHELP: v1 id 0x100\n', mode)
    assert capture.mfc_meter_errors(text + 'PS5 SPUHELPSTAT: v1 id 0x100\n', mode)
    assert not capture.mfc_meter_errors('PS5 MFCMETER: gate 9 helper_probes 1\n'+text, mode)
assert capture.mfc_meter_errors('Core:\n  Enable Performance Report: false\n', 0)
print('PASS: correct compiled mode accepted; wrong/missing mode, enabled reporting and heavy probes rejected')
