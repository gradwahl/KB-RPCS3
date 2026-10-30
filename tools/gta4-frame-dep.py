#!/usr/bin/env python3
"""Summarise the sparse PS5 CPU frame-event timeline from one GTA IV capture.

CPU TSC intervals do NOT provide GPU execution timestamps or establish
PPU/SPU/RSX dependencies. Event epochs are sampled at guest display-queue
boundaries (one in 32) and may contain in-flight GPU work from other frames.
"""
import argparse
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

EVENTS = {
    1: "guest_queue_begin", 2: "guest_queue_end", 3: "guest_flip",
    4: "rsx_present_begin", 5: "rsx_present_end",
    6: "vk_acquire_begin", 7: "vk_acquire_end",
    8: "vk_submit_begin", 9: "vk_submit_end",
    10: "vk_present_begin", 11: "vk_present_end",
    12: "vk_fence_begin", 13: "vk_fence_end",
    14: "ppu_event_wait_begin", 15: "ppu_event_wait_end",
    16: "ppu_flag_wait_begin", 17: "ppu_flag_wait_end",
    18: "ppu_sema_wait_begin", 19: "ppu_sema_wait_end",
}
EVENT = re.compile(r"PS5 FRAMEDEP: seq (\d+) epoch (\d+) kind (\d+) arg (\d+) tsc (\d+)")
SUMMARY = re.compile(r"PS5 FRAMEDEP2: window (\d+) ms emitted (\d+) skipped (\d+) missed (\d+) tsc_hz (\d+) total (\d+)")
TIME = re.compile(r"\b(\d+):(\d{2}):(\d{2})\.(\d+)")
PAIRS = {1: 2, 4: 5, 6: 7, 8: 9, 10: 11, 12: 13, 14: 15, 16: 17, 18: 19}


def log_time(line):
    m = TIME.search(line)
    if m is None:
        raise ValueError("Cannot parse log time: " + line[:80])
    h, minute, sec, part = m.groups()
    return int(h) * 3600 + int(minute) * 60 + int(sec) + int(part) / 10**len(part)


def analyse(capture):
    summary = json.loads(capture.with_suffix(".json").read_text(encoding="utf8"))
    if not summary.get("valid") or summary.get("new_spu_compilations"):
        raise ValueError("Bad or compiling FPS capture: " + capture.stem)
    text = capture.with_suffix(".log").read_text(encoding="utf8", errors="replace")
    lines = text.splitlines()
    fps_lines = [x for x in lines if "PS5 FPS:" in x]
    if len(fps_lines) < summary["windows"]:
        raise ValueError("Missing FPS window data")
    ends = [log_time(x) for x in fps_lines[-summary["windows"]:]]
    # Reporter may be delayed, so include one watchdog window margin at the start.
    start, stop = min(ends) - 4.5, max(ends) + 0.5
    events, reports = [], []
    for line in lines:
        if "PS5 FRAMEDEP" not in line:
            continue
        t = log_time(line)
        if t < start or t > stop:
            continue
        if (m := EVENT.search(line)):
            pos, ep, k, arg, tsc = map(int, m.groups())
            if k not in EVENTS:
                raise ValueError("Unrecognised frame event code: " + str(k))
            events.append({"seq": pos, "epoch": ep, "kind": k, "event": EVENTS[k],
                           "arg": arg, "tsc": tsc})
        if (m := SUMMARY.search(line)):
            elapsed, emitted, skipped, missed, freq, total = map(int, m.groups())
            reports.append({"seconds": elapsed / 1000, "emitted": emitted,
                            "skipped": skipped, "missed": missed,
                            "freq_hz": freq, "cumulative_events": total})
    if not reports:
        raise ValueError("No FRAMEDEP2 report during capture")
    freq = {x["freq_hz"] for x in reports}
    if len(freq) != 1 or min(freq) <= 0:
        raise ValueError("Inconsistent or invalid TSC frequency")
    hz = next(iter(freq))
    if len(events) < 8:
        raise ValueError("No usable sampled frame events")
    events.sort(key=lambda r: r["tsc"])
    counts = Counter(x["event"] for x in events)
    starts = defaultdict(list)
    spans = defaultdict(list)
    thread_wait_spans = defaultdict(list)
    unpaired = Counter()
    for event in events:
        k = event["kind"]
        # Scope pairing stays within an epoch and a guest thread identifier;
        # vk_submit/fence may span threads, so these are only indicative intervals.
        key = (event["epoch"], k, event["arg"] if k in (14, 16, 18) else 0)
        if k in PAIRS:
            starts[key].append(event)
        elif k - 1 in PAIRS:
            prior = starts[(event["epoch"], k - 1,
                            event["arg"] if k in (15, 17, 19) else 0)]
            if not prior:
                unpaired[event["event"]] += 1
                continue
            earlier = prior.pop()
            if event["tsc"] > earlier["tsc"]:
                ms = (event["tsc"] - earlier["tsc"]) * 1000 / hz
                spans[EVENTS[k - 1].replace("_begin", "")].append(ms)
                if k in (15, 17, 19):
                    thread_wait_spans[(event["arg"], EVENTS[k - 1].replace("_begin", ""))].append(ms)
    durations = {}
    for name, samples in spans.items():
        durations[name] = {
            "n": len(samples),
            "mean_ms": round(statistics.mean(samples), 3),
            "p95_estimate_ms": round(sorted(samples)[min(len(samples) - 1, int(len(samples) * 0.95))], 3),
            "max_ms": round(max(samples), 3),
        }
    thread_waits = {}
    for (ppu_id, kind), samples in sorted(thread_wait_spans.items()):
        thread_waits.setdefault(f"0x{ppu_id:08x}", {})[kind] = {
            "n": len(samples),
            "mean_ms": round(statistics.mean(samples), 3),
            "max_ms": round(max(samples), 3),
            "observed_total_ms": round(sum(samples), 3),
        }
    return {
        "capture": capture.name, "fps": summary["mean_window_fps"],
        "capture_seconds": summary["seconds"],
        "scale": summary["resolution_scale"],
        "sampling": "1 of 32 guest display queue epochs; overlapping async work; sample spans are CPU wall-clock only",
        "events": len(events),
        "epochs": len({x["epoch"] for x in events}),
        "event_counts": dict(counts),
        "paired_cpu_durations": durations,
        "ppu_waits_by_thread_id": thread_waits,
        "unpaired_end_events": dict(unpaired),
        "buffer_skips": sum(x["skipped"] for x in reports),
        "buffer_misses": sum(x["missed"] for x in reports),
        "tsc_hz": hz,
        "first_event_tsc": events[0]["tsc"],
        "last_event_tsc": events[-1]["tsc"],
        "limitations": [
            "Guest queue epochs are not precise frame IDs for asynchronous RSX/Vulkan work",
            "Fence wait is host wait/CPU idle duration, not GPU execution duration",
            "Events are drained every ~4s; capture boundaries may include a few events outside the exact 45s window",
            "PPU waits sampled only when a blocking branch is entered and duration exceeds 500us",
            "Unmatched begin/end pairs are omitted from duration summaries",
            "No actual SPU job execution timings or GPU timestamp queries are captured yet",
        ],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("capture", type=Path, help="Capture stem, .json or .log")
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    capture = args.capture.with_suffix("")
    result = analyse(capture)
    output = args.output or capture.with_name(capture.name + "-framedep").with_suffix(".json")
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf8")
    print(json.dumps({k: v for k, v in result.items()
                      if k not in ("limitations",)}, indent=2))
    print("Saved", output)


if __name__ == "__main__":
    main()
