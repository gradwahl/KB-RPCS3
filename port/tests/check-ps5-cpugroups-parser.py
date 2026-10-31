#!/usr/bin/env python3
"""Check CPU group parser with historical and exact all-worker samples."""
from pathlib import Path
import importlib.util, tempfile,json

p=Path(__file__).resolve().parents[2]/"tools/gta4-cpu-groups.py"
spec=importlib.util.spec_from_file_location("ps5_cpu_groups_parser",p)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

legacy="·! 0:02:04.000 SYS: PS5 CPU: total 450% | SPU[0x10] one 200% | PPU[0x11] main 120% | rsx::thread 80% | Pad Thread 5%"
x=mod.cpu_row(legacy)
assert x["mode"]=="top14_lower_bound" and x["group_core_pct"]=={"ppu":120,"spu":200,"rsx_main":80,"other":5}
assert x["unassigned_or_rounding_core_pct"]==45
new=("·! 0:02:08.000 SYS: PS5 CPU: total 325% | group_ns window 4000000000"
     " ppu 3200000000 spu 6400000000 rsx_main 2400000000 other 1000000000"
     " threads_ppu 3 threads_spu 7 threads_rsx_main 1 threads_other 24"
     " | SPU[0x10] one 100%")
y=mod.cpu_row(new)
assert y["mode"]=="exact" and y["group_core_pct"]=={"ppu":80,"spu":160,"rsx_main":60,"other":25}
assert y["workers"]=={"ppu":3,"spu":7,"rsx_main":1,"other":24}
with tempfile.TemporaryDirectory() as td:
    stem=Path(td)/"B-synth"
    metadata={"valid":True,"new_spu_compilations":0,"windows":2,"mean_window_fps":26.3}
    stem.with_suffix(".json").write_text(json.dumps(metadata))
    lines=[
        "·! 0:02:00.000 SYS: PS5 FPS: 26.3 | frame p50 38.0 p95 41.0 p99 43.0 ms, 1% low 22",
        "·! 0:02:04.000 SYS: PS5 FPS: 26.3 | frame p50 38.0 p95 41.0 p99 43.0 ms, 1% low 22",
        "·! 0:02:08.000 SYS: PS5 FPS: 26.3 | frame p50 38.0 p95 41.0 p99 43.0 ms, 1% low 22",
        new]
    stem.with_suffix(".log").write_text("\n".join(lines))
    result=mod.analyse(stem)
    assert result["mode"]=="exact" and result["cpu_report_count"]==1
    assert result["mean_group_core_pct"]["spu"]==160.0
    lines[3]=legacy;stem.with_suffix(".log").write_text("\n".join(lines))
    result=mod.analyse(stem)
    assert result["mode"]=="top14_lower_bound"
    assert result["mean_unassigned_or_rounding_core_pct"]==45.0
    metadata["new_spu_compilations"]=1
    stem.with_suffix(".json").write_text(json.dumps(metadata))
    try:mod.analyse(stem)
    except AssertionError:pass
    else:raise AssertionError("accepted fresh SPU compilations")
print("PASS: exact all-thread / historic top14 / window / compilation-contamination cases")
