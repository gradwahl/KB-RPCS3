#!/usr/bin/env python3
"""Summarise PS5 SPU / RSX completed samples and patch0062 live SPU coverage.

Counts and durations are partial, sampled intervals, not complete per-frame
costs. SPU gateway is inclusive of helper/channel blocking. CPU-work samples
overlap gateway samples. RSX FIFO state is post-call, not individual method
classification. No GPU timestamps, guest SPU job IDs or frame DAG are measured.
"""
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

STAGES = {
    ("spu", 0): ("spu_gateway", 256),
    ("spu", 1): ("spu_cpu_work", 1024),
    ("rsx", 2): ("rsx_fifo_running", 512),
    ("rsx", 3): ("rsx_fifo_nop", 512),
    ("rsx", 4): ("rsx_fifo_empty", 512),
    ("rsx", 5): ("rsx_fifo_spinning", 512),
    ("rsx", 6): ("rsx_fifo_other", 512),
}
ROW = re.compile(r"PS5 WORKER: group (spu|rsx) id 0x([0-9a-fA-F]+) kind (\d+) sample_n (\d+) avg_us ([\d.]+) max_us ([\d.]+) sampled_sum_us ([\d.]+)")
LOSS = re.compile(r"PS5 WORKER2: lost_spu_slot_allocations (\d+)")
COVER = re.compile(r"PS5 SPUCOVER: v2 id 0x([0-9a-fA-F]+) tasks (\d+) jit_tasks (\d+) gateway_entries (\d+) gateway_returns (\d+) gateway_active ([01]) gateway_age_us ([\d.]+) cpu_work_entries (\d+) cpu_work_sample_active ([01]) cpu_work_sample_age_us ([\d.]+) cpu_work_abandoned (\d+)")
ZERO_ID = re.compile(r"PS5 SPUCOVER2: zero_id_registrations (\d+)")
TIME = re.compile(r"\b(\d+):(\d{2}):(\d{2})\.(\d+)")
OLD = ("PS5 PERF:", "PS5 FIFO2:", "PS5 CLOCK2:", "PS5 PROFILE ")


def time_of(line):
    m = TIME.search(line)
    if not m:
        raise ValueError("Missing log timestamp: " + line[:90])
    h, minute, second, frac = m.groups()
    return int(h) * 3600 + int(minute) * 60 + int(second) + int(frac) / 10**len(frac)


def analyse(stem):
    m = json.loads(stem.with_suffix(".json").read_text(encoding="utf8"))
    text = stem.with_suffix(".log").read_text(encoding="utf8", errors="replace")
    if not m["valid"] or m["mode"] != "B" or m["resolution_scale"] != "150":
        raise ValueError("Not a matched 150% scheduler-B capture")
    if m["new_spu_compilations"]:
        raise ValueError("Compilation-contaminated run")
    lines = text.splitlines()
    fps = [l for l in lines if "PS5 FPS:" in l]
    if len(fps) < m["windows"] + 1:
        raise ValueError("Insufficient FPS reporting windows")
    recent = fps[-m["windows"]-1:]
    bounds = [time_of(l) for l in recent]
    start, stop = bounds[0], bounds[-1] + 0.5
    durations = [bounds[i+1]-bounds[i] for i in range(len(bounds)-1)]
    values = [float(re.search(r"PS5 FPS: ([\d.]+)",l).group(1)) for l in recent[1:]]
    weighted = sum(a*b for a,b in zip(durations,values))/sum(durations)
    groups = defaultdict(lambda: defaultdict(list))
    found = 0
    lost = 0
    coverage_rows = defaultdict(list)
    zero_ids = 0
    v2 = bool(COVER.search(text))
    for line in lines:
        if "PS5 WORKER" not in line and "PS5 SPUCOVER" not in line:
            continue
        t = time_of(line)
        if not start <= t <= stop:
            continue
        if (match := ROW.search(line)):
            group, ppu, code, samples, avg, maximum, sample_sum = match.groups()
            key = (group, int(code))
            if key not in STAGES:
                raise ValueError(f"Unknown worker group/kind: {key}")
            samples = int(samples)
            if samples == 0:
                continue
            observed = {"samples": samples, "avg_us": float(avg),
                        "max_us": float(maximum), "sum_us": float(sample_sum)}
            groups[group][(int(ppu,16), int(code))].append(observed)
            found += 1
        elif (match := LOSS.search(line)):
            lost += int(match.group(1))
        elif (match := COVER.search(line)):
            fields = match.groups()
            coverage_rows[int(fields[0], 16)].append({
                "tasks": int(fields[1]), "jit_tasks": int(fields[2]),
                "gateway_entries": int(fields[3]), "gateway_returns": int(fields[4]),
                "gateway_active": bool(int(fields[5])), "gateway_age_us": float(fields[6]),
                "cpu_work_entries": int(fields[7]), "cpu_work_sample_active": bool(int(fields[8])),
                "cpu_work_sample_age_us": float(fields[9]), "cpu_work_abandoned": int(fields[10]),
            })
        elif (match := ZERO_ID.search(line)):
            zero_ids += int(match.group(1))
    if found == 0 and not coverage_rows:
        raise ValueError("No PS5 WORKER or SPUCOVER reports in FPS measurement window")
    summaries = {"spu": {}, "rsx": {}}
    for group, entries in groups.items():
        for (worker, code), rows in sorted(entries.items()):
            samples = sum(x["samples"] for x in rows)
            total = sum(x["sum_us"] for x in rows)
            label, rate = STAGES[(group,code)]
            if v2 and group == "spu" and code == 0:
                rate = 1  # 0062 times every gateway, not every 256th return.
            stats = {
                "sampled_calls": samples,
                "sample_probability": f"1/{rate}",
                "mean_sampled_cpu_us": round(total/samples,3),
                "max_sampled_cpu_us": round(max(x["max_us"] for x in rows),3),
                "sampled_total_cpu_us": round(total,3),
                "watchdog_reports": len(rows),
            }
            if group == "spu":
                summaries["spu"].setdefault(f"0x{worker:08x}",{})[label] = stats
            else:
                summaries["rsx"][label] = stats
    # Sampled time in RSX FIFO calls only; excludes local/backend tasks,
    # and does NOT represent the entire RSX host thread's time.
    rsx = summaries["rsx"]
    total_rsx = sum(v["sampled_total_cpu_us"] for v in rsx.values())
    if total_rsx:
        for v in rsx.values():
            v["share_of_sampled_fifo_cpu_time_percent"] = round(
                100*v["sampled_total_cpu_us"]/total_rsx,2)
    coverage = {}
    for worker, rows in sorted(coverage_rows.items()):
        first, last = rows[0], rows[-1]
        coverage[f"0x{worker:08x}"] = {
            "reports": len(rows), "last": last,
            "gateway_entries_delta_between_reports": last["gateway_entries"] - first["gateway_entries"],
            "gateway_returns_delta_between_reports": last["gateway_returns"] - first["gateway_returns"],
            "cpu_work_entries_delta_between_reports": last["cpu_work_entries"] - first["cpu_work_entries"],
            "gateway_active_observations": sum(r["gateway_active"] for r in rows),
            "max_gateway_age_us": max(r["gateway_age_us"] for r in rows),
            "max_cpu_work_sample_age_us": max(r["cpu_work_sample_age_us"] for r in rows),
        }
    live_valid = any(r["last"]["gateway_entries"] or r["last"]["cpu_work_entries"]
                     for r in coverage.values()) and not zero_ids and not lost
    warning = None
    if not summaries["spu"]:
        warning = ("No completed SPU interval samples; live gateway/cpu_work coverage is available. "
                   "Live age includes JIT/helpers/waits and is not productive CPU time."
                   if live_valid else
                   "No completed SPU samples or confirmed live execution coverage; do not infer idle SPUs")
    return {
        "capture": stem.name,
        "capture_log_window_seconds": [start, stop],
        "fps_window_mean": m["mean_window_fps"],
        "fps_time_weighted": round(weighted,3),
        "new_spu_compilations": 0,
        "worker_report_count": found,
        "worker_slot_allocation_overflow": lost,
        "worker_activity": summaries,
        "rsx_measurement_valid": bool(summaries["rsx"]),
        "spu_measurement_valid": bool(summaries["spu"]),
        "spu_completed_timing_valid": bool(summaries["spu"]),
        "spu_live_coverage_valid": live_valid,
        "spu_coverage": coverage,
        "spu_zero_id_registrations": zero_ids,
        "spu_measurement_warning": warning,
        "old_heavy_diagnostics_absent": all(z not in text for z in OLD),
        "frame_event_tracer_disabled": "PS5 FRAMEDEP:" not in text,
        "limitations": [
            "Per-invocation CPU wall-clock samples are NOT total worker duty cycle or completed-frame time",
            "SPU JIT gateway includes nested guest helpers, stalls and spin; SPU CPU-work can overlap gateway",
            "RSX post-FIFO state reports are a classification of run_FIFO invocations, not GPU method counts",
            "RSX sampled CPU fraction excludes rendering/driver tasks outside run_FIFO, and can have sampling bias",
            "No Vulkan GPU completion timestamp, SPU guest-job duration or frame critical-path dependency graph",
            "Coverage fields are cumulative/approximate snapshots; never sum live ages or cumulative counters across windows",
            "CPU-work counts accepted pending-work calls, not all guest SPU instruction execution",
            "FPS comparison requires a same-scene profiler-off control with tracing disabled",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture",type=Path)
    parser.add_argument("--output",type=Path)
    args = parser.parse_args()
    stem = args.capture.with_suffix("")
    result = analyse(stem)
    output = args.output or stem.with_name(stem.name + "-worker-activity").with_suffix(".json")
    output.write_text(json.dumps(result,indent=2)+"\n",encoding="utf8")
    print(json.dumps(result,indent=2))
    print("Saved",output)


if __name__ == "__main__":
    main()
