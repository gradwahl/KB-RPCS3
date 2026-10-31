#!/usr/bin/env python3
"""Synthetic full/partial PS5 topology parser and scheduler assumption tests."""
import importlib.util
from pathlib import Path
path=Path(__file__).resolve().parents[2]/"tools/ps5-cpu-topology.py"
spec=importlib.util.spec_from_file_location("ps5_topology",path)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def log(mapping, fail=None, leaf=1, restore=0):
    # mapping {logical CPU -> (node, core)}, synthetic full coverage.
    out=[]
    for cpu,(node,core) in sorted(mapping.items()):
        sr=22 if cpu==fail else 0
        rb=0 if sr else 1<<cpu
        valid=int(not sr and leaf)
        out.append(f"PS5 TOPO CPU: index {cpu} set_rc {sr} get_rc 0 mask 0x{rb:x} x2apic {cpu+42} core {core} node {node} tpc 2 valid {valid}")
    mask=sum(1<<cpu for cpu in mapping)
    succeeded=len(mapping)-int(fail is not None) if leaf else 0
    out.append(f"PS5 TOPO SUMMARY: allowed 0x{mask:x} amd_leaf {leaf} initial_rc 0 restore_rc {restore} attempts {len(mapping)} succeeded {succeeded} truncated 0")
    return "\n".join(out)

adj={i:(0,i//2) for i in range(13)}
v=mod.analyze(log(adj))
assert v["status"]=="COMPLETE" and v["allowed_mask"]=="0x1fff"
assert v["adjacent_hypothesis_matches_cpuid"] is True
assert v["cpuid_reported_singletons"]==[12]
assert v["cpuid_reported_pairs"]==[[i,i+1] for i in range(0,12,2)]
# Nonadjacent siblings: 0..5 paired with 6..11; 12 alone.
other={i:(0,(i%6)) if i<12 else (0,6) for i in range(13)}
v=mod.analyze(log(other))
assert v["status"]=="COMPLETE" and not v["adjacent_hypothesis_matches_cpuid"]
assert v["cpuid_reported_pairs"]==[[i,i+6] for i in range(6)]
for failure in [dict(fail=4),dict(leaf=0),dict(restore=13)]:
 v=mod.analyze(log(adj,**failure))
 assert v["status"]=="UNVERIFIED" and v["adjacent_hypothesis_matches_cpuid"] is None
 assert v["cpuid_reported_core_groups"]==[]
assert mod.analyze("no PS5 topology line")["status"]=="NO_DATA"
assert mod.analyze(log(adj)+"\n"+log(adj))["status"]=="AMBIGUOUS"
print("PASS CPU topology parser: 13 CPUs, adjacent vs nonadjacent SMT, singleton, pin failure, unsupported leaf, failed restore and ambiguous logs")
