#!/usr/bin/env python3
"""Rank opt-in PS5 SPU HOTJIT samples by actual recorded guest function hash.

Parses the existing Utilities/Thread.cpp sampler's summarized JIT hash/offset
candidates. The nearest-preceding JIT-entry lookup uses a 256 KiB heuristic;
therefore ranks are CANDIDATES, not verified symbol-size-bounded occupancy.
Do not infer guest CPU-exclusive time or FPS from the sample percentages.
"""
from __future__ import annotations
from collections import defaultdict
from pathlib import Path
import argparse
import json
import re

MARKER = re.compile(r"PS5 SPU HOTJIT:\s+(SPU\[[^\]]+\][^:]*):\s+")
REGION = re.compile(r"\|\s*SPU code\s+(\d+)\s+of\s+(\d+)\s+samples:")
END = re.compile(r"\|\s*\d+\s+samples:")
FUNCTION = re.compile(r"(spu-[0-9a-fA-F]{4,}-[^\s:\[\]]+):(\d+)(?:\[([^\]]*)\])?")
OFFSET = re.compile(r"\+([0-9a-fA-F]+):(\d+)")


def parse_text(content: str, source: str) -> dict:
    functions = defaultdict(lambda: {"listed_hits": 0, "reports": 0, "offsets": defaultdict(int)})
    workers = defaultdict(lambda: {"reports": 0, "sampled": 0, "jit_samples": 0})
    valid = 0
    excluded = 0
    no_jit = 0
    malformed = 0
    for line in content.splitlines():
        if "PS5 SPU HOTJIT:" not in line:
            continue
        if "no active SPU execution thread" in line:
            no_jit += 1
            continue
        match = MARKER.search(line)
        if not match:
            malformed += 1
            continue
        name = match.group(1)
        region = REGION.search(line, match.end())
        if not region:
            malformed += 1
            continue
        jit, total = map(int, region.groups())
        if not 0 <= jit <= total <= 4096:
            malformed += 1
            continue
        tail = line[region.end():]
        marker_end = END.search(tail)
        if marker_end:
            tail = tail[:marker_end.start()]
        found = list(FUNCTION.finditer(tail))
        listed_sum = sum(int(x.group(2)) for x in found)
        if listed_sum > jit or len({x.group(1) for x in found}) != len(found):
            malformed += 1
            continue
        valid += 1
        workers[name]["reports"] += 1
        workers[name]["sampled"] += total
        workers[name]["jit_samples"] += jit
        excluded += total - jit
        for rec in found:
            fname, hits, offsets = rec.groups()
            tally = functions[fname]
            tally["listed_hits"] += int(hits)
            tally["reports"] += 1
            for off, hits_at in OFFSET.findall(offsets or ""):
                tally["offsets"][f"0x{int(off,16):x}"] += int(hits_at)
    rank = []
    for fname, row in functions.items():
        rank.append({
            "function": fname,
            "listed_hits": row["listed_hits"],
            "reports_listed": row["reports"],
            "top_offsets": [
                {"offset": offset, "hits": count}
                for offset, count in sorted(row["offsets"].items(), key=lambda x: (-x[1], int(x[0],16)))[:8]
            ],
        })
    rank.sort(key=lambda r: (-r["listed_hits"], r["function"]))
    sampled = sum(v["sampled"] for v in workers.values())
    jit = sum(v["jit_samples"] for v in workers.values())
    listed = sum(x["listed_hits"] for x in rank)
    return {
        "source": source, "valid_reports": valid, "no_spu_reports": no_jit,
        "malformed_reports": malformed,
        "all_signal_samples": sampled,
        "candidate_spu_jit_samples": jit,
        "non_jit_samples": excluded,
        "listed_top12_spu_jit_hits": listed,
        "listed_fraction_of_candidate_jit_samples": round(listed / jit, 5) if jit else None,
        "workers": dict(workers), "rank": rank,
        "limitations": [
            "All hits are sampled asynchronous signal PCs, not exact host CPU duration, JIT instruction counts, or per-frame time.",
            "The existing PS5 lookup associates any instruction within 0x40000 after a registered SPU entry with that entry; there is no verified function size, so names are CANDIDATES until matched to real LLVM22 object symbols.",
            "The profiler only prints its top 12 functions; listed hits can be less than all candidate JIT hits.",
            "Only active SPU execution workers are selected; SPU compiler threads, PPU/RSX and unrelated host code are excluded from candidate JIT attribution.",
            "Do not combine overlapping capture logs as independent sampling intervals or claim FPS improvement from function ranks."
        ]
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("logs", type=Path, nargs="+")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    results = [parse_text(path.read_text(encoding="utf8", errors="replace"), str(path)) for path in args.logs]
    if args.output:
        if args.output.exists():
            raise FileExistsError(f"refusing to overwrite {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"captures": results}, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"captures": results}, indent=2))


if __name__ == "__main__":
    main()
