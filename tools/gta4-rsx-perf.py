#!/usr/bin/env python3
"""Summarise PS5-only RSX CPU diagnostic windows from RPCS3.log.

PS5 PERF data are aggregated across multiple threads and reset when reported.
FIFO samples cover approximately one in 128 RSX FIFO loop iterations; this
is not an exact active/idle percentage. Vulkan timings are CPU side only;
vk_submit is nested within vk_close, so sums are not additive.
"""
import argparse
import json
from pathlib import Path
import re
import statistics

STAGE = re.compile(
    r"PS5 PERF: window (?P<window>\d+) ms"
    r" \| FIFO sampled running (?P<running_calls>\d+) calls (?P<running_us>\d+) us"
    r" idle (?P<idle_calls>\d+) calls (?P<idle_us>\d+) us"
    r" \| vertex (?P<vertex_calls>\d+) calls (?P<vertex_us>\d+) us"
    r" \| index (?P<index_calls>\d+) calls (?P<index_kib>\d+) KiB (?P<index_us>\d+) us"
    r" \| dma_sync (?P<dma_calls>\d+) calls (?P<dma_us>\d+) us"
    r" \| vk_close (?P<vk_close_calls>\d+) calls (?P<vk_close_us>\d+) us"
    r" \| vk_submit (?P<vk_submit_calls>\d+) calls (?P<vk_submit_us>\d+) us"
)
# Patch 0057: sampled first-read FIFO categories and GLOBAL batched clock/yield counts.
FIFO2 = re.compile(
    r"PS5 FIFO2: window (?P<window>\d+) ms"
    r" \| method (?P<method_calls>\d+) calls (?P<method_us>\d+) us"
    r" \| nop (?P<nop_calls>\d+) calls (?P<nop_us>\d+) us"
    r" \| empty (?P<empty_calls>\d+) calls (?P<empty_us>\d+) us"
    r" \| busy (?P<busy_calls>\d+) calls (?P<busy_us>\d+) us"
    r" \| self_jump (?P<self_jump_calls>\d+) calls (?P<self_jump_us>\d+) us"
    r" \| other_flow (?P<other_flow_calls>\d+) calls (?P<other_flow_us>\d+) us"
)
CLOCK2 = re.compile(
    r"PS5 CLOCK2: window (?P<window>\d+) ms"
    r" \| clock_calls (?P<clock_calls>\d+)"
    r" \| yield_spin (?P<yield_spin>\d+)"
    r" \| yield_os (?P<yield_os>\d+)"
    r" \| yield_sleep (?P<yield_sleep>\d+)"
)
FIFO_KINDS = ("method", "nop", "empty", "busy", "self_jump", "other_flow")


def parse_fifo2(text):
    return [{k: int(v) for k, v in m.groupdict().items()} for m in FIFO2.finditer(text)]


def parse_clock2(text):
    return [{k: int(v) for k, v in m.groupdict().items()} for m in CLOCK2.finditer(text)]


def extended_summary(fifo, clocks):
    if not fifo or len(fifo) != len(clocks) or any(a["window"] != b["window"] for a, b in zip(fifo, clocks)):
        raise ValueError("Incomplete or mismatched FIFO2/CLOCK2 diagnostic windows")
    seconds = sum(x["window"] for x in fifo) / 1000
    if seconds <= 0:
        raise ValueError("Zero FIFO2 window duration")
    kinds = {
        kind: {"sampled_calls_per_second": round(sum(x[kind + "_calls"] for x in fifo) / seconds, 2),
               "sampled_cpu_ms_per_second": round(sum(x[kind + "_us"] for x in fifo) / (1000 * seconds), 3)}
        for kind in FIFO_KINDS
    }
    clocks_per_s = {
        key: round(sum(x[key] for x in clocks) / seconds, 1)
        for key in ("clock_calls", "yield_spin", "yield_os", "yield_sleep")
    }
    return {"fifo_first_read_sample_1_in_128": kinds,
            "clock_global_batched_calls_per_second": clocks_per_s}


LABEL = {
    "vertex": "vertex data preparation",
    "index": "index conversion",
    "dma": "DMA synchronisation",
    "vk_close": "Vulkan close+submit (CPU)",
    "vk_submit": "Vulkan queue submit (CPU, nested)",
}


def parse(text):
    return [{k: int(v) for k, v in match.groupdict().items()}
            for match in STAGE.finditer(text)]


def summary(rows):
    if not rows:
        raise ValueError("No PS5 PERF windows. Build 0056 is required.")
    result = {"windows": len(rows)}
    for part in ("running", "idle", "vertex", "index", "dma", "vk_close", "vk_submit"):
        calls_key = f"{part}_calls"
        us_key = f"{part}_us"
        result[part] = {
            "mean_calls_per_window": round(statistics.mean(r[calls_key] for r in rows), 2),
            "mean_cpu_ms_per_s": round(statistics.mean(
                r[us_key] / r["window"] for r in rows), 3)
        }
    result["index"]["mean_source_kib_per_s"] = round(statistics.mean(
        1000 * r["index_kib"] / r["window"] for r in rows), 2)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("logs", type=Path, nargs="+")
    p.add_argument("--output", type=Path)
    p.add_argument("--capture-only", action="store_true",
                   help="Use only the windows recorded by the matching capture JSON")
    args = p.parse_args()
    all_results = []
    for name in args.logs:
        log_text = name.read_text(encoding="utf8", errors="replace")
        rows = parse(log_text)
        fifo = parse_fifo2(log_text)
        clocks = parse_clock2(log_text)
        if not rows:
            print(f"{name}: no PS5 PERF windows (not a diagnostic build)")
            continue
        if args.capture_only:
            capture_file = name.with_suffix(".json")
            capture = json.loads(capture_file.read_text(encoding="utf8"))
            if not capture["valid"]:
                raise ValueError(f"{capture_file} is not a valid FPS capture")
            count = capture["windows"]
            if count <= 0 or count > len(rows):
                raise ValueError(f"{name}: expected {count} PS5 PERF windows, found {len(rows)}")
            rows = rows[-count:]
            if fifo or clocks:
                if len(fifo) < count or len(clocks) < count:
                    raise ValueError(f"{name}: missing PS5 FIFO2/CLOCK2 windows")
                fifo = fifo[-count:]
                clocks = clocks[-count:]
        report = summary(rows)
        if fifo or clocks:
            if len(fifo) != len(rows) or len(clocks) != len(rows):
                raise ValueError(f"{name}: extended counters mismatch")
            report.update(extended_summary(fifo, clocks))
        if args.capture_only:
            report["capture_fps"] = capture["mean_window_fps"]
            report["capture_valid"] = capture["valid"]
        all_results.append({"file": str(name), **report})
        print(f"\n{name}: {report['windows']} windows")
        print("  FIFO time values are SAMPLED only. No real GPU timing is reported.")
        for key in ("running", "idle", "vertex", "index", "dma", "vk_close", "vk_submit"):
            print(f"  {key}: {report[key]['mean_calls_per_window']:.1f} calls/window,"
                  f" {report[key]['mean_cpu_ms_per_s']:.3f} ms CPU time per second")
        if "fifo_first_read_sample_1_in_128" in report:
            print("  FIFO first-read 1/128 sample rates (not all guest commands):")
            for kind, stat in report["fifo_first_read_sample_1_in_128"].items():
                print(f"    {kind}: {stat['sampled_calls_per_second']:.2f} calls/s,"
                      f" {stat['sampled_cpu_ms_per_second']:.3f} sampled ms/s")
            print("  CLOCK global batched calls/s:",
                  report["clock_global_batched_calls_per_second"])
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(all_results, indent=2) + "\n", encoding="utf8")
        print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
