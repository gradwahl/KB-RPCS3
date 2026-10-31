#!/usr/bin/env python3
"""Synthetic cumulative per-event reports and parser robustness tests."""
from pathlib import Path
import importlib.util,json,tempfile
path=Path(__file__).resolve().parents[2]/"tools/gta4-spu-reswait.py"
spec=importlib.util.spec_from_file_location("reswait",path)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
def report(t,idx,calls,samples,wall,cpu,maximum):
 return f"·! 0:00:{t:02d}.100 SYS: PS5 SPUWAIT: v1 event {idx} period 128 calls {calls} samples {samples} wall_ns {wall} cpu_ns {cpu} wall_max_ns {maximum}"
def log(corrupt=False):
 lines=[]
 for t in [2,6,10,14,18,22,26,30]:
  lines.append(f"·! 0:00:{t:02d}.000 SYS: PS5 FPS: 25.0 | frame")
  if t==2:continue
  for i in range(4):
   n=t//4
   lines.append(report(t,i,20*n+i,2*n,1000*n*(i+1),600*n*(i+1),150*(i+1)))
 if corrupt:
  lines[-4]=report(30,0,0,0,0,0,0)
 return "\n".join(lines)+"\n"
with tempfile.TemporaryDirectory() as d:
 stem=Path(d)/"B-test"
 stem.with_suffix(".json").write_text(json.dumps({"valid":True,"new_spu_compilations":0,"mfc_meter_mode":[["0","0"]],"windows":5,"mean_window_fps":25}))
 stem.with_suffix(".log").write_text(log())
 x=mod.parse_capture(stem)
 assert x["valid"] and x["cpu_report_group_count"]>=2
 assert x["events"]["callback"]["exact_calls"]>0
 assert x["events"]["callback_notify"]["sampled_thread_cpu_ns"]>0
 stem.with_suffix(".log").write_text(log(corrupt=True))
 try:mod.parse_capture(stem)
 except ValueError:pass
 else:raise AssertionError("accepted a counter regression")
 m=json.loads(stem.with_suffix(".json").read_text())
 m["new_spu_compilations"]=1
 stem.with_suffix(".json").write_text(json.dumps(m))
 try:mod.parse_capture(stem)
 except ValueError:pass
 else:raise AssertionError("accepted new SPU compilations")
print("PASS synthetic cumulative 1/128 interval parser, monotonic counter and compilation validation")
