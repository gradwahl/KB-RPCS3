#!/usr/bin/env python3
"""Compare same-code GTA IV profiler-OFF 150%/100% resolution captures.

The comparison measures host frame-flip reporting, NOT actual GPU frame
completion, and does not prove the GPU is the only limiting resource.
Run from the KB-RPCS3 workspace; do not modify console files here.
"""
import argparse
import json
import re
import statistics
from pathlib import Path

BASELINE = ("B-profiler-off-0058-run1", "B-profiler-off-0058-run2")
REDUCED = ("B-resolution100-off-0058-run1", "B-resolution100-off-0058-run3")  # Run 2 excluded: 180 newly compiled SPU blocks
REVERSE = ("B-resolution150-return-0058-run1", "B-resolution150-return-0058-run2")

FPS_PATTERN = re.compile(
    r"PS5 FPS: (?P<fps>[\d.]+) \| frame p50 (?P<p50>[\d.]+)"
    r" p95 (?P<p95>[\d.]+) p99 (?P<p99>[\d.]+) ms,"
    r" 1% low (?P<low>[\d.]+)"
)
TIME_PATTERN = re.compile(r"\b(\d+):(\d{2}):(\d{2})\.(\d+)")


def stamp(line):
    match = TIME_PATTERN.search(line)
    if not match:
        raise ValueError("Missing report timestamp: " + line[:90])
    h, m, s, fraction = match.groups()
    return int(h) * 3600 + int(m) * 60 + int(s) + int(fraction) / 10**len(fraction)


def read_capture(root, label, resolution):
    meta = json.loads((root / (label + ".json")).read_text(encoding="utf8"))
    log = (root / (label + ".log")).read_text(encoding="utf8", errors="replace")
    if not meta["valid"] or meta["new_spu_compilations"] != 0:
        raise ValueError(label + ": invalid benchmark or SPU compilation occurred")
    if meta["mode"] != "B" or meta["resolution_scale"] != str(resolution) or meta["seconds"] != 45:
        raise ValueError(label + ": scheduler, scale or capture length mismatch")
    if any(tag in log for tag in ("PS5 PERF:", "PS5 FIFO2:", "PS5 CLOCK2:", "PS5 PROFILE ")):
        raise ValueError(label + ": diagnostics ON; not a clean profiler-OFF comparison")
    lines = [line for line in log.splitlines() if "PS5 FPS:" in line]
    n = meta["windows"]
    if n < 5 or len(lines) <= n:
        raise ValueError(label + ": insufficient FPS reporting windows")
    window = lines[-n - 1:]
    events = [(stamp(line), FPS_PATTERN.search(line)) for line in window]
    if any(match is None for _, match in events):
        raise ValueError(label + ": unable to parse FPS frame statistics")
    intervals = [events[i][0] - events[i - 1][0] for i in range(1, len(events))]
    if any(x <= 0 or x > 10 for x in intervals):
        raise ValueError(label + ": invalid report timing or log restart")
    data = [
        {k: float(v) for k, v in match.groupdict().items()}
        for _, match in events[1:]
    ]
    elapsed = sum(intervals)
    # Report-interval weighted FPS; still not a pooled per-frame measurement.
    weighted = sum(x * entry["fps"] for x, entry in zip(intervals, data)) / elapsed
    return {
        "name": label,
        "resolution": resolution,
        "valid": True,
        "new_spu_compilations": 0,
        "capture_seconds": meta["seconds"],
        "report_windows": n,
        "report_span_seconds": round(elapsed, 2),
        "fps_window_mean": meta["mean_window_fps"],
        "fps_time_weighted": round(weighted, 3),
        "fps_report_min": min(entry["fps"] for entry in data),
        "fps_report_max": max(entry["fps"] for entry in data),
        "p50_ms_window_mean": meta["mean_window_p50_ms"],
        "p95_ms_window_mean": meta["mean_window_p95_ms"],
        "p99_ms_window_mean": meta["mean_window_p99_ms"],
        "one_percent_low_window_mean": meta["mean_window_one_percent_low_fps"],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--capture-dir", type=Path, default=Path("results/gta4-scheduler-20261030"))
    p.add_argument("--output", type=Path, default=Path("results/gta4-resolution-20261030/resolution-compare.json"))
    p.add_argument("--allow-partial", action="store_true", help="Summarise existing captures while awaiting the remaining ones")
    args = p.parse_args()
    series = [
        ("baseline_150", 150, BASELINE),
        ("reduced_100", 100, REDUCED),
        ("return_150", 150, REVERSE),
    ]
    result = {
        "test": "Top-down rendering-scale experiment; same 0058 profiler-OFF executable",
        "controls": "RPCS3 Scheduler B, Mega SPU, Approximate XFloat, 100% clocks, 60 FPS cap, identical game patches, experimental SPU flags off",
        "caveats": [
            "150% vs 100% corresponds to 2.25x pixel count, but only pixel-related rendering work is expected to scale with area",
            "Host RSX frame flips are not a guarantee of completed GPU frames; direction is a screening test, not a GPU time measurement",
            "Changing resolution requires a new game launch; game state and world activity may drift, so confirm with return-to-150 captures",
            "These are reporting-interval-weighted FPS windows, not pooled individual-frame percentiles",
            "A small FPS change is consistent with CPU/synchronisation limitation but cannot rule out a partly GPU-bound pipeline",
        ],
        "series": {},
    }
    for group, resolution, names in series:
        found = []
        for name in names:
            path = args.capture_dir / (name + ".json")
            if not path.exists() and (args.allow_partial or group == "return_150"):
                continue
            found.append(read_capture(args.capture_dir, name, resolution))
        if found:
            result["series"][group] = {
                "captures": found,
                "mean_fps_time_weighted": round(statistics.mean(c["fps_time_weighted"] for c in found), 3),
                "mean_p95_ms": round(statistics.mean(c["p95_ms_window_mean"] for c in found), 3),
            }
            print(f"{group}: {len(found)} captures, mean FPS {result['series'][group]['mean_fps_time_weighted']}")
        elif not args.allow_partial and group != "return_150":
            raise ValueError("Missing mandatory " + group + " captures")
    if "baseline_150" in result["series"] and "reduced_100" in result["series"]:
        base = result["series"]["baseline_150"]["mean_fps_time_weighted"]
        reduced = result["series"]["reduced_100"]["mean_fps_time_weighted"]
        result["delta_100_minus_150_fps"] = round(reduced - base, 3)
        result["delta_100_vs_150_percent"] = round(100 * (reduced / base - 1), 2)
        print(f"100% - 150%: {reduced - base:+.3f} FPS ({100 * (reduced / base - 1):+.2f}%)")
    if "return_150" in result["series"]:
        print("Return-to-150 control is available; examine whether FPS reverted.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf8")
    print("Saved", args.output)


if __name__ == "__main__":
    main()
