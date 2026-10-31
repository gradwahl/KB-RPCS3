#!/usr/bin/env python3
"""Check RSX class parser totals, ordering and invalid capture rejection."""
from pathlib import Path
import importlib.util
import json
import tempfile

file=Path(__file__).resolve().parents[2]/"tools/gta4-rsx-classes.py"
spec=importlib.util.spec_from_file_location("rsx_class_capture",file)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
with tempfile.TemporaryDirectory(prefix="ps5-rsx-class-parser-") as d:
    stem=Path(d)/"B-rsx0066-synthetic"
    metadata={"valid":True,"mode":"B","resolution_scale":"150","new_spu_compilations":0,
              "mfc_meter_mode":[["0","0"]],"windows":5}
    stem.with_suffix(".json").write_text(json.dumps(metadata))
    fps=[f"·! 0:01:{40+i*4:02d}.000 SYS: PS5 FPS: 25.0" for i in range(6)]
    heads=[
        "·! 0:01:44.050 SYS: PS5 RSXCLASS2: bucket_bytes 256 words 100 handlers 80 nonempty 3 top_limit 12",
        "·! 0:01:44.051 SYS: PS5 RSXCLASS: rank 1 offset 0x2000 words 60 handlers 50",
        "·! 0:01:44.052 SYS: PS5 RSXCLASS: rank 2 offset 0x1000 words 30 handlers 25",
        "·! 0:01:44.053 SYS: PS5 RSXCLASS: rank 3 offset 0x0100 words 10 handlers 5",
        "·! 0:01:48.050 SYS: PS5 RSXCLASS2: bucket_bytes 256 words 30 handlers 20 nonempty 2 top_limit 12",
        "·! 0:01:48.051 SYS: PS5 RSXCLASS: rank 1 offset 0x1000 words 20 handlers 12",
        "·! 0:01:48.052 SYS: PS5 RSXCLASS: rank 2 offset 0x2000 words 10 handlers 8",
    ]
    log=stem.with_suffix(".log")
    log.write_text("\n".join(fps+heads)+"\n",encoding="utf-8")
    out=mod.analyse(stem)
    assert out["valid"] and out["report_count"]==2
    assert out["total_sampled_loop_words"]==130 and out["total_sampled_direct_handlers"]==100
    assert out["ranked_address_bands"][0]["offset_bytes"]==0x2000
    assert out["ranked_address_bands"][1]["offset_bytes"]==0x1000
    print("PASS: two histogram windows, offset groups, rank/sum checks")
    log.write_text(log.read_text().replace("rank 2 offset 0x1000 words 30","rank 2 offset 0x1000 words 90"),encoding="utf-8")
    try:mod.analyse(stem)
    except ValueError:pass
    else:raise AssertionError("invalid unsorted/excess ranking accepted")
    metadata["new_spu_compilations"]=1
    stem.with_suffix(".json").write_text(json.dumps(metadata))
    try:mod.analyse(stem)
    except ValueError as e:assert "compilation" in str(e)
    else:raise AssertionError("compilation contamination accepted")
    print("PASS: invalid histogram and compilation contamination rejected")
