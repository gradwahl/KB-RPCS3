#!/usr/bin/env python3
"""Synthetic exact-format validation for sampled RSX method-work log parser."""
from __future__ import annotations
from pathlib import Path
import importlib.util
import json
import tempfile

root = Path(__file__).resolve().parents[2]
module_path = root / "tools/gta4-rsx-words.py"
spec = importlib.util.spec_from_file_location("gta4_rsx_words", module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

with tempfile.TemporaryDirectory(prefix="rsx-words-parser-") as work:
    p = Path(work) / "B-rsx0065-synthetic"
    run = {"valid": True, "mode": "B", "resolution_scale": "150",
           "new_spu_compilations": 0, "mfc_meter_mode": [["0","0"]], "windows": 5}
    p.with_suffix(".json").write_text(json.dumps(run))
    fps = [f"·! 0:01:{40+i*4:02d}.000000 SYS: PS5 FPS: 25.0 | frame p50 40.0 p95 45.0 p99 48.0 ms, 1% low 21.0" for i in range(5)]
    fps.append("·! 0:02:00.000000 SYS: PS5 FPS: 25.0 | frame p50 40.0 p95 45.0 p99 48.0 ms, 1% low 21.0")
    word_rows = [
        "·! 0:01:44.050000 SYS: PS5 RSXWORDS: every 512 method_runs 3 method_loop_words 100 handler_calls 40 flattened_skips 20 max_words_per_run 80",
        "·! 0:01:48.050000 SYS: PS5 RSXWORDS: every 512 method_runs 2 method_loop_words 18 handler_calls 10 flattened_skips 0 max_words_per_run 16",
        "·! 0:01:52.050000 SYS: PS5 RSXWORDS: every 512 method_runs 0 method_loop_words 0 handler_calls 0 flattened_skips 0 max_words_per_run 0",
        "·! 0:01:56.050000 SYS: PS5 RSXWORDS: every 512 method_runs 1 method_loop_words 5 handler_calls 5 flattened_skips 0 max_words_per_run 5",
    ]
    p.with_suffix(".log").write_text("\n".join(fps + word_rows) + "\n",encoding="utf-8")
    data = module.analyse(p)
    assert data["valid_method_work_sample"]
    assert data["sampled_method_runs"] == 6
    assert data["method_loop_words"] == 123
    assert data["direct_method_handler_calls"] == 55
    assert data["flattened_suppressed_words"] == 20
    assert data["max_loop_words_one_sampled_run"] == 80
    print("PASS: synthetic valid sampled method-run rows, totals and window bounds")
    p.with_suffix(".log").write_text(
        p.with_suffix(".log").read_text().replace("handler_calls 40 flattened_skips 20",
                                                    "handler_calls 95 flattened_skips 20"))
    try:
        module.analyse(p)
        raise AssertionError("Should reject impossible handler+skip counts")
    except ValueError as exc:
        assert "exceed" in str(exc)
    run["new_spu_compilations"]=1
    p.with_suffix(".json").write_text(json.dumps(run))
    try:
        module.analyse(p)
        raise AssertionError("Should reject SPU compilation")
    except ValueError as exc:
        assert "SPU compilation" in str(exc)
    print("PASS: invalid counts and SPU-compilation periods rejected")
