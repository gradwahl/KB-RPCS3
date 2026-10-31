#!/usr/bin/env python3
"""Synthetic HOTJIT parser tests: individual workers, unsymbolized, corrupt."""
from pathlib import Path
import importlib.util
p=Path(__file__).resolve().parents[2]/"tools/ps5-spu-hotjit.py"
spec=importlib.util.spec_from_file_location("spu_hotjit_parser",p)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
log="""
0:00:00.000 SYS: PS5 SPU HOTJIT: SPU[0x1000000] worker: system code: 0x10:1 | SPU code 60 of 200 samples: spu-12345-__spu-0x12345-AAA:40[+2a:10 +f:3] spu-23456-__spu-0x23456-BBB:18[+3b:6] | 200 samples: x
0:00:04.000 SYS: PS5 SPU HOTJIT: SPU[0x2000000] worker: system code: | SPU code 20 of 200 samples: spu-12345-__spu-0x12345-AAA:10[+2a:5] spu-fffff-__spu-0xfffff-CCC:9[+0:2] | 200 samples: y
0:00:08.000 SYS: PS5 SPU HOTJIT: no active SPU execution thread
0:00:12.000 SYS: PS5 SPU HOTJIT: SPU[0x2000000] worker: system code: | SPU code 90 of 200 samples: spu-12345-__spu-0x12345-AAA:100[+2a:5] | 200 samples: y
0:00:16.000 SYS: PS5 SPU HOTJIT: nonsense
"""
r=mod.parse_text(log,"test")
assert r["valid_reports"]==2 and r["no_spu_reports"]==1 and r["malformed_reports"]==2
assert r["all_signal_samples"]==400 and r["candidate_spu_jit_samples"]==80
assert r["non_jit_samples"]==320 and r["listed_top12_spu_jit_hits"]==77
assert r["rank"][0]["function"]=="spu-12345-__spu-0x12345-AAA" and r["rank"][0]["listed_hits"]==50
assert r["rank"][0]["top_offsets"][0]=={"offset":"0x2a","hits":15}
assert len(r["workers"])==2
assert len(r["limitations"]) >= 4 and "CANDIDATES" in " ".join(r["limitations"])
r2=mod.parse_text("some unrelated text","none")
assert r2["valid_reports"]==0 and r2["rank"]==[] and r2["listed_fraction_of_candidate_jit_samples"] is None
print("PASS generic HOTJIT name/hash/offset ranking, non-JIT samples, invalid log exclusion, empty output")
