#!/usr/bin/env python3
"""Summarise recent PS5 SPU JIT profiler samples from saved GTA IV logs.

Uses only reports in the last --seconds before the final PS5 FPS line in
each log snapshot. Profiles sample *one thread* for about two seconds,
not a simultaneous per-frame critical path. Top-function reports list
only the hottest functions/offsets, so summed hits are lower bounds.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re

TIME = re.compile(r"\b(\d+):(\d+):(\d+\.\d+) ")
JIT = re.compile(r"SPU code (\d+) of (\d+) samples:")
FN = re.compile(r"(spu-[0-9a-f]+-__spu-0x[0-9a-f]+-[A-Za-z0-9]+):(\d+)(?:\[([^\]]*)\])?")
OFF = re.compile(r"\+([0-9a-f]+):(\d+)")
IP = re.compile(r"\b(?:sys@)?([0-9a-f]+):(\d+)")


def timestamp(line):
    m = TIME.search(line)
    return 3600 * int(m[1]) + 60 * int(m[2]) + float(m[3]) if m else None


def analyse(path, seconds):
    lines = path.read_text("utf-8", errors="replace").splitlines()
    fps = [(timestamp(line), line) for line in lines if "PS5 FPS:" in line]
    fps = [(t, line) for t, line in fps if t is not None]
    if not fps:
        raise ValueError(f"{path}: no FPS markers found")
    end = fps[-1][0]
    start = end - seconds
    group = defaultdict(lambda: {"reports": 0, "jit": 0, "samples": 0,
                                  "functions": Counter(), "offsets": defaultdict(Counter)})
    rsx_ips = Counter()
    for line in lines:
        if "PS5 PROFILE " not in line:
            continue
        t = timestamp(line)
        if t is None or not start <= t <= end + 1:
            continue
        name = line.split("PS5 PROFILE ", 1)[1].split(": system code:", 1)[0]
        category = ("RSX" if name == "rsx::thread" else
                    "SPU primary" if "PrimaryCellSpursKernel" in name else
                    "SPU secondary" if "SecondaryCellSpursKernel" in name else "Other")
        info = group[category]
        info["reports"] += 1
        m = JIT.search(line)
        if m:
            info["jit"] += int(m[1])
            info["samples"] += int(m[2])
            jet = line.split(" | SPU code ", 1)[1].split(" | ", 1)[0]
            for func in FN.finditer(jet):
                name = func[1]
                info["functions"][name] += int(func[2])
                for off, hits in OFF.findall(func[3] or ""):
                    info["offsets"][name][off] += int(hits)
        if category == "RSX" and " | 400 samples:" in line:
            ips = line.split(" | 400 samples:", 1)[1]
            for address, hits in IP.findall(ips):
                rsx_ips[address] += int(hits)
    return {
        "file": str(path), "last_seconds": seconds,
        "groups": {
            kind: {
                "reports": info["reports"],
                "sampled_jit_instruction_pointers": info["jit"],
                "sampled_total": info["samples"],
                "jit_fraction": round(info["jit"] / info["samples"], 3) if info["samples"] else None,
                "top_functions": [
                    {"function": n, "listed_hits": hits,
                     "top_listed_offsets": info["offsets"][n].most_common(5)}
                    for n, hits in info["functions"].most_common(8)]
            }
            for kind, info in group.items()
        },
        "top_rsx_addresses": rsx_ips.most_common(10),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("logs", nargs="+", type=Path)
    p.add_argument("--seconds", type=float, default=50)
    p.add_argument("--output", type=Path)
    a = p.parse_args()
    data = [analyse(path, a.seconds) for path in a.logs]
    out = json.dumps(data, indent=2)
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(out + "\n", encoding="utf-8")
        print(f"Saved {a.output}")
    for entry in data:
        print(f"\n{entry['file']}")
        for kind, info in entry["groups"].items():
            print(f"  {kind}: {info['reports']} reports; JIT {info['sampled_jit_instruction_pointers']}/"
                  f"{info['sampled_total']} sampled IPs")
            for fn in info["top_functions"][:4]:
                offsets = " ".join(f"+{off}:{count}" for off, count in fn["top_listed_offsets"][:3])
                print(f"    {fn['function'].split('-__')[0]}: {fn['listed_hits']} (listed), {offsets}")
        if entry["top_rsx_addresses"]:
            print(f"  RSX listed addresses: {entry['top_rsx_addresses'][:6]}")


if __name__ == "__main__":
    main()
