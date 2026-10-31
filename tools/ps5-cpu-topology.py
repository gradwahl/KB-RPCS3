#!/usr/bin/env python3
"""Validate opt-in PS5 topology logs, never guess SMT sibling mapping.

The CPUID 0x8000001E AMD-reported (node,core) grouping is evidence only
when every allowed logical CPU was individually pinned, read back by OS
and queried with supported vendor/leaf. Missing data => UNKNOWN.

This parser does not claim physical contention or throughput, nor
treat the scheduler's configured masks as independent topology proof.
"""
from __future__ import annotations
from collections import defaultdict
from pathlib import Path
import argparse,json,re

CPU=re.compile(r"PS5 TOPO CPU: index (\d+) set_rc (-?\d+) get_rc (-?\d+) mask 0x([0-9a-fA-F]+) x2apic (\d+) core (\d+) node (\d+) tpc (\d+) valid (\d+)")
SUMMARY=re.compile(r"PS5 TOPO SUMMARY: allowed 0x([0-9a-fA-F]+) amd_leaf (\d+) initial_rc (-?\d+) restore_rc (-?\d+) attempts (\d+) succeeded (\d+) truncated (\d+)")


def analyze(text:str)->dict:
    sm=list(SUMMARY.finditer(text))
    if not sm:
        return {"status":"NO_DATA","reason":"No diagnostic topology summary; default OFF or no probe result"}
    if len(sm)!=1:
        return {"status":"AMBIGUOUS","reason":"Multiple topology summaries; provide one bounded capture"}
    h=sm[0]
    allowed,leaf,initial,restore,attempts,succeeded,truncated = [int(h[i],16) if i==1 else int(h[i]) for i in range(1,8)]
    cpus=[]
    for m in CPU.finditer(text[:h.start()]):
        vals=list(map(int,m.groups()[:3]))+[int(m[4],16)]+list(map(int,m.groups()[4:]))
        cpu,sr,gr,mask,apic,core,node,tpc,valid=vals
        cpus.append(dict(cpu=cpu,set_rc=sr,get_rc=gr,readback_mask=mask,apic_id=apic,
                         core_id=core,node_id=node,advertised_threads=tpc,valid=bool(valid)))
    issues=[]
    allowed_ids=[i for i in range(64) if allowed & (1<<i)]
    if initial:issues.append(f"initial pthread_getaffinity_np failed {initial}")
    if restore:issues.append(f"watchdog affinity RESTORE FAILED {restore}; safety failure")
    if truncated:issues.append("CPU set contains IDs >=64; this u64 log is incomplete")
    if not leaf:issues.append("AMD CPUID 0x8000001E unsupported; cannot determine siblings")
    if len(cpus)!=len(allowed_ids) or attempts!=len(allowed_ids):
        issues.append("CPU rows/attempt count do not cover full reported affinity mask")
    if len({v["cpu"] for v in cpus})!=len(cpus):
        issues.append("Repeated CPU ID / duplicate sample")
    if {v["cpu"] for v in cpus}!={*allowed_ids}:
        issues.append("Sample CPU IDs differ from process allowed IDs")
    for c in cpus:
        if (c["set_rc"],c["get_rc"])!=(0,0) or c["readback_mask"] != 1<<c["cpu"]:
            issues.append(f"CPU {c['cpu']} pin/readback failed")
        if not c["valid"] or c["advertised_threads"]<1:
            issues.append(f"CPU {c['cpu']} lacks valid extended AMD core identity")
    if succeeded!=len(cpus):
        issues.append("successful CPUID sample count != emitted CPU rows")
    if len({c["apic_id"] for c in cpus})!=len(cpus) and leaf:
        issues.append("Extended APIC IDs not unique")
    groups=defaultdict(list)
    for c in cpus:
        if c["valid"]:
            groups[(c["node_id"],c["core_id"])].append(c["cpu"])
    for k,ids in groups.items():
        matching=[c for c in cpus if (c["node_id"],c["core_id"])==k]
        tpcs={c["advertised_threads"] for c in matching}
        if len(tpcs)!=1 or len(ids)>min(tpcs):
            issues.append(f"core identity {k} inconsistent with advertised threads-per-core")
    complete=not issues
    pairs=sorted([sorted(v) for v in groups.values() if len(v)==2])
    singletons=sorted(v[0] for v in groups.values() if len(v)==1)
    # Hypothesis: logical CPUs 0/1, 2/3, ... are siblings.
    presumed=sorted([[i,i+1] for i in range(0,64,2) if i in allowed_ids and i+1 in allowed_ids])
    actual=pairs
    groupings=[{"node":k[0],"core":k[1],"cpus":sorted(v)} for k,v in sorted(groups.items())]
    return {
        "status":"COMPLETE" if complete else "UNVERIFIED",
        "allowed_mask":f"0x{allowed:x}","cpus":cpus,
        "cpuid_amd_8000001e_supported":bool(leaf),
        "restore_ok":restore==0,
        "issues":issues,
        "cpuid_reported_core_groups":groupings if complete else [],
        "cpuid_reported_pairs":pairs if complete else [],
        "cpuid_reported_singletons":singletons if complete else [],
        "assumed_adjacent_pairs":presumed,
        "adjacent_hypothesis_matches_cpuid":(actual==presumed and len(groups)>0) if complete else None,
        "limitations":[
            "Do not infer actual PS5 SMT topology from scheduler mask 0x555 / 0x1aaa alone.",
            "This validates AMD CPUID-reported core groups plus OS pin/readback; it cannot independently prove physical core resource sharing or affinity persistence for guest threads.",
            "When any CPU lacks readback, CPUID support, restoration, or unique IDs, result is UNVERIFIED and no groups are promoted.",
            "To verify actual guest PPU/SPU/RSX pinning, separately sample each registered worker's applied affinity and migrations, then do controlled scheduler FPS/CPU comparisons."
        ]
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("log",type=Path)
    p.add_argument("--output",type=Path)
    args=p.parse_args()
    result=analyze(args.log.read_text("utf8",errors="replace"))
    if args.output:
        if args.output.exists():raise FileExistsError(args.output)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))


if __name__=="__main__":main()
