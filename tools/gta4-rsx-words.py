#!/usr/bin/env python3
"""Summarize sampled PS5 RSX method-loop counts during one GTA IV capture.

This is sampled *CPU-side method-bearing run_FIFO* activity, not GPU command
counts, complete RSX workload, critical-path duration or a speedup claim.
Each row covers an approximate watchdog reporting window, not a frame.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re

TIMESTAMP = re.compile(r"\b(\d+):(\d{2}):(\d{2})\.(\d+)")
WORD = re.compile(
    r"PS5 RSXWORDS: every (\d+) method_runs (\d+) "
    r"method_loop_words (\d+) handler_calls (\d+) "
    r"flattened_skips (\d+) max_words_per_run (\d+)")
FPS = re.compile(r"PS5 FPS: ([\d.]+)")


def timestamp(line: str) -> float:
    m = TIMESTAMP.search(line)
    if not m:
        raise ValueError("Missing source log timestamp")
    h, minute, second, frac = m.groups()
    return int(h) * 3600 + int(minute) * 60 + int(second) + int(frac) / 10**len(frac)


def analyse(stem: Path) -> dict:
    run = json.loads(stem.with_suffix(".json").read_text(encoding="utf-8"))
    if not run["valid"] or run["mode"] != "B" or run["resolution_scale"] != "150":
        raise ValueError("Requires valid scheduler B, 150% capture")
    if run.get("new_spu_compilations"):
        raise ValueError("Reject capture containing new SPU compilation")
    if run.get("mfc_meter_mode") != [["0", "0"]]:
        raise ValueError("Requires MFC gate0/helper_probes0")
    text = stem.with_suffix(".log").read_text(encoding="utf-8", errors="replace")
    fps = [line for line in text.splitlines() if FPS.search(line)]
    n = run["windows"]
    if n < 4 or len(fps) < n + 1:
        raise ValueError("Insufficient FPS timestamps")
    start = timestamp(fps[-n-1])
    stop = timestamp(fps[-1]) + .5
    rows = []
    for line in text.splitlines():
        if "PS5 RSXWORDS:" not in line:
            continue
        t = timestamp(line)
        if not start <= t <= stop:
            continue
        m = WORD.search(line)
        if not m:
            raise ValueError("Unrecognized RSXWORDS row syntax")
        rate, sampled, words, handled, skipped, maximum = map(int, m.groups())
        if rate != 512:
            raise ValueError("Unexpected method-bearing sampling rate")
        if words < handled + skipped:
            raise ValueError("Method callbacks + suppressed words exceed loop iterations")
        if (sampled == 0 and (words or handled or skipped or maximum)) or (sampled and maximum > words):
            raise ValueError("Invalid sampled count or max words")
        if maximum > 0 and (sampled == 0 or maximum < 1):
            raise ValueError("Invalid maximum")
        rows.append({"time_s": t, "sampled_method_runs": sampled,
                     "method_loop_words": words, "handler_calls": handled,
                     "flattened_skips": skipped, "max_words_in_run": maximum})
    total = lambda key: sum(row[key] for row in rows)
    samples = total("sampled_method_runs")
    words = total("method_loop_words")
    handled = total("handler_calls")
    skipped = total("flattened_skips")
    if not rows:
        raise ValueError("No RSXWORDS reports in measurement window")
    return {
        "capture": stem.name,
        "compiled_mfc_gate": 0, "compiled_helper_probes": 0,
        "method_probe_sampling_rate": "1/512 method-bearing run_FIFO calls",
        "capture_window_s": [start, stop],
        "watchdog_rows": len(rows),
        "rows_with_sampled_method_work": sum(r["sampled_method_runs"] > 0 for r in rows),
        "sampled_method_runs": samples,
        "method_loop_words": words,
        "direct_method_handler_calls": handled,
        "flattened_suppressed_words": skipped,
        "max_loop_words_one_sampled_run": max(r["max_words_in_run"] for r in rows),
        "mean_loop_words_per_sampled_run": round(words/samples, 4) if samples else None,
        "mean_direct_handler_calls_per_sampled_run": round(handled/samples, 4) if samples else None,
        "fraction_sampled_words_with_direct_method_handler": round(handled/words, 4) if words else None,
        "estimated_method_bearing_calls": samples*512 if samples else None,
        "valid_method_work_sample": samples > 0,
        "note": "1/512 periodic sampling may be phase-biased; not all guest packets or GPU work; cannot claim FPS improvement. Watchdog interval boundaries approximate.",
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path, help="Capture stem, .log or .json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    stem = args.capture.with_suffix("")
    result = analyse(stem)
    out = args.output or stem.with_name(stem.name + "-rsx-words").with_suffix(".json")
    if out.exists():
        raise SystemExit("Existing summary; refusing overwrite: " + str(out))
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k != "rows"}, indent=2))
    print("Saved", out)


if __name__ == "__main__":
    main()
