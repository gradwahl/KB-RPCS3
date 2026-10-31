#!/usr/bin/env python3
"""Parse patch0068 cumulative PS5 SPU reservation callback / wait timing.

Read only valid 45-second GTA IV capture pairs. Reports are cumulative
since boot, not window-reset; use deltas between first and last complete
reports in the capture. Timings are from 1/128 sampled invocations.
Callback, atomic_wait and nested notification costs MUST NOT be summed.
"""
from pathlib import Path
import argparse,json,re,statistics
EVENTS=("callback","atomic_wait","callback_notify","post_wait_notify")
STAMP=re.compile(r"(\d+):(\d\d):(\d\d)\.(\d+)")
FPS=re.compile(r"PS5 FPS: ([\d.]+)")
MARKER=re.compile(r"PS5 SPUWAIT: v1 event ([0-3]) period 128 calls (\d+) samples (\d+) wall_ns (\d+) cpu_ns (\d+) wall_max_ns (\d+)")
def timestamp(s):
 m=STAMP.search(s)
 if not m:raise ValueError("invalid timestamp")
 a,b,c,d=m.groups()
 return int(a)*3600+int(b)*60+int(c)+int(d)/10**len(d)
def parse_capture(stem:Path):
 info=json.loads(stem.with_suffix(".json").read_text("utf8"))
 if not info.get("valid") or info.get("new_spu_compilations")!=0 or info.get("mfc_meter_mode")!=[["0","0"]]:
  raise ValueError("invalid capture, compiled MFC mode, or new SPU compilation")
 lines=stem.with_suffix(".log").read_text("utf8",errors="replace").splitlines()
 fps=[(timestamp(line),line) for line in lines if FPS.search(line)]
 n=int(info["windows"])
 if len(fps)<n+1:raise ValueError("incomplete FPS boundaries")
 start=fps[-n-1][0];stop=fps[-1][0]+.5
 # The four watchdog lines have distinct microsecond timestamps. They
 # form an ordered event 0,1,2,3 group, never four identical stamps.
 complete=[]
 pending={}
 group_time=None
 for line in lines:
  m=MARKER.search(line)
  if not m:continue
  t=timestamp(line)
  if not start<=t<=stop:continue
  vals=tuple(map(int,m.groups()))
  eid=vals[0];seq=vals[1:]
  if seq[1]>seq[0]:raise ValueError("sample count exceeds exact calls")
  if eid==0:
   pending={};group_time=t
  if group_time is None or t-group_time>1 or eid in pending:continue
  pending[eid]=seq
  if len(pending)==4:
   complete.append((group_time,pending.copy()))
   pending={};group_time=None
 if len(complete)<2:raise ValueError("fewer than two full cumulative report groups")
 prev=complete[0][1];final=complete[-1][1]
 result={}
 for i,name in enumerate(EVENTS):
  first=prev[i];last=final[i]
  if any(x<y for x,y in zip(last,first)):raise ValueError("cumulative counter regressed")
  delta=[b-a for a,b in zip(first,last)]
  calls,samples,wall_ns,cpu_ns,_=delta
  result[name]={"exact_calls":calls,"timed_samples":samples,
      "sampled_wall_ns":wall_ns,"sampled_thread_cpu_ns":cpu_ns,
      "wall_us_per_timed_call":round(wall_ns/samples/1000,3) if samples else None,
      "cpu_us_per_timed_call":round(cpu_ns/samples/1000,3) if samples else None,
      "sampled_wall_over_cpu_ratio":round(wall_ns/max(cpu_ns,1),3) if samples else None,
      "cumulative_max_wall_us":round(last[4]/1000,3),
      "report_window_seconds":round(complete[-1][0]-complete[0][0],3)}
 return {"capture":stem.name,"valid":True,"fps_mean":info["mean_window_fps"],
   "cpu_report_group_count":len(complete),"sample_period":128,
   "measurement":"timed sample invocation wall and host thread CPU time; nested metrics overlap",
   "limits":"timing sampled 1/128 per host worker and event, phase bias; counts exact; clocks have overhead; cumulative max is not window max; no per-frame or GPU attribution",
   "events":result}
def main():
 p=argparse.ArgumentParser()
 p.add_argument("capture",type=Path,nargs="+")
 p.add_argument("--output",type=Path)
 a=p.parse_args()
 caps=[parse_capture(Path(x).with_suffix("")) for x in a.capture]
 out={"valid":all(x["valid"] for x in caps),"captures":caps}
 if a.output:
  if a.output.exists():raise SystemExit("refusing to overwrite existing result")
  a.output.parent.mkdir(parents=True,exist_ok=True)
  a.output.write_text(json.dumps(out,indent=2)+"\n",encoding="utf8")
 print(json.dumps(out,indent=2)[:20000])
if __name__=="__main__":main()
