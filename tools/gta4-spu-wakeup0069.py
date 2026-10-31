#!/usr/bin/env python3
"""Patch0069 sampled reservation page, wake outcome and notifier analysis.

Events in SPUWAKEPAGE are 1/128 SAMPLED; never call these exact totals.
All page counters are cumulative across entire game session and top8 is
ranked by cumulative wait samples, which censors omitted pages.
Compute interval differences ONLY between adjacent reports with that
page present at both endpoints. Group-level sample counters are exact
numbers of sampled *events*, not exact calls.
"""
from __future__ import annotations
import argparse,json,math,re,statistics
from pathlib import Path
FPS=re.compile(r"PS5 FPS:\s*([\d.]+)")
CPU=re.compile(r"group_ns window (\d+) ppu (\d+) spu (\d+) rsx_main (\d+) other (\d+)")
HEAD=re.compile(r"PS5 SPUWAKE2: period 128 sample_waits (\d+) sample_producers (\d+) overflow (\d+) slots 256")
PAGE=re.compile(r"PS5 SPUWAKEPAGE: rank (\d+) page 0x([0-9a-fA-F]{8}) waits (\d+) changed (\d+) cleared (\d+) unchanged (\d+) producer_ppu (\d+) producer_spu (\d+) producer_other (\d+)")
TIME=re.compile(r"(\d+):(\d\d):(\d\d)\.(\d+)")
def stamp(s):
 m=TIME.search(s)
 if not m:raise ValueError("timestamp missing")
 a,b,c,d=m.groups()
 return int(a)*3600+int(b)*60+int(c)+int(d)/10**len(d)
def correlation(a,b):
 if len(a)<5 or len(a)!=len(b):return None
 mx=statistics.mean(a);my=statistics.mean(b)
 sx=sum((x-mx)**2 for x in a);sy=sum((y-my)**2 for y in b)
 if sx<=0 or sy<=0:return None
 return round(sum((x-mx)*(y-my) for x,y in zip(a,b))/math.sqrt(sx*sy),3)
def parse(stem:Path):
 meta=json.loads(stem.with_suffix(".json").read_text("utf8"))
 assert meta["valid"] and meta["mfc_meter_mode"]==[["0","0"]] and meta["new_spu_compilations"]==0
 raw=stem.with_suffix(".log").read_text("utf8",errors="replace").splitlines()
 fps=[(stamp(line),float(FPS.search(line)[1])) for line in raw if FPS.search(line)]
 windows=int(meta["windows"])
 assert len(fps)>=windows+1 and windows>=10
 start=fps[-windows-1][0];end=fps[-1][0]+1
 frames=[(t,v) for t,v in fps if start<=t<=end]
 cpus=[]
 for line in raw:
  if "PS5 CPU:" not in line:continue
  m=CPU.search(line)
  if not m:continue
  t=stamp(line)
  if not start<=t<=end:continue
  vals=list(map(int,m.groups()))
  win,ppu,spu,rsx,other=vals
  if win:cpus.append((t,{k:round(v/win,3) for k,v in zip(("ppu","spu","rsx_main","other"),(ppu,spu,rsx,other))}))
 groups=[]
 for line in raw:
  h=HEAD.search(line)
  if h:
   t=stamp(line)
   if not start<=t<=end:continue
   calls=tuple(map(int,h.groups()))
   groups.append({"t":t,"waits":calls[0],"producers":calls[1],"overflow":calls[2],"pages":{}})
   continue
  p=PAGE.search(line)
  if p and groups:
   t=stamp(line)
   group=groups[-1]
   if t-group["t"]>1.0:continue
   a=p.groups()
   pg=int(a[1],16);values=list(map(int,a[2:]))
   assert int(a[0])<=8
   group["pages"][pg]={"waits":values[0],"changed":values[1],"cleared":values[2],"unchanged":values[3],
                      "ppu":values[4],"spu":values[5],"other":values[6]}
 if len(groups)<2:raise ValueError("not enough SPUWAKE2 watchdog windows")
 intervals=[]
 pages={}
 for prev,curr in zip(groups,groups[1:]):
  if curr["t"]<=prev["t"]:continue
  fields=("waits","producers","overflow")
  d={k:curr[k]-prev[k] for k in fields}
  if any(v<0 for v in d.values()):raise ValueError("regressing sampled counters")
  # Match the nearest FPS entry *before* the watchdog group, up to 4s.
  fp=[(abs(curr["t"]-t),v) for t,v in frames if t<=curr["t"] and curr["t"]-t<=4]
  dfps=min(fp)[1] if fp else None
  cp=[(abs(curr["t"]-t),v) for t,v in cpus if t<=curr["t"] and curr["t"]-t<=4]
  dcpu=min(cp)[1] if cp else None
  inter={"duration":round(curr["t"]-prev["t"],3),"t":curr["t"],
    "sampled_waits":d["waits"],"sampled_producer_notifications":d["producers"],
    "table_overflows":d["overflow"],"fps":dfps,"host_cores":dcpu}
  intervals.append(inter)
  for page,b in curr["pages"].items():
   a=prev["pages"].get(page)
   if not a:continue
   delta={k:b[k]-a[k] for k in b}
   if any(v<0 for v in delta.values()):raise ValueError("regressing page counters")
   acc=pages.setdefault(page,{k:0 for k in delta}|{"paired_reports":0})
   for k,v in delta.items():acc[k]+=v
   acc["paired_reports"]+=1
 data={"capture":stem.name,"valid":True,"fps_mean":meta["mean_window_fps"],
   "watchdog_reports":len(groups),"report_intervals":intervals,
   "samples_between_first_last":{"waits":groups[-1]["waits"]-groups[0]["waits"],
      "producers":groups[-1]["producers"]-groups[0]["producers"],
      "overflows":groups[-1]["overflow"]-groups[0]["overflow"]},
   "pages_from_consecutive_top8_snapshots":[{"page":f"0x{k:08x}",**val} for k,val in sorted(pages.items(),key=lambda x:-x[1]["waits"])],
   "correlation_fps_vs_sampled_waits":correlation([i["sampled_waits"] for i in intervals if i["fps"] is not None],[i["fps"] for i in intervals if i["fps"] is not None]),
   "notes":"Page rows contain only pairs of consecutive TOP8 cumulative snapshots where page appeared in both. They are sampled lower coverage, not all pages; producer notification is not necessarily the data writer or sole wake source; top8 ranking is cumulative; time-window correlations descriptive, not per-frame dependency."}
 return data
def main():
 p=argparse.ArgumentParser()
 p.add_argument("captures",type=Path,nargs="+")
 p.add_argument("--output",type=Path)
 args=p.parse_args()
 rows=[parse(Path(x).with_suffix("")) for x in args.captures]
 out={"captures":rows,"valid":all(x["valid"] for x in rows)}
 if args.output:
  if args.output.exists():raise SystemExit("refusing overwrite")
  args.output.parent.mkdir(parents=True,exist_ok=True)
  args.output.write_text(json.dumps(out,indent=2)+"\n",encoding="utf8")
 print(json.dumps(out,indent=2)[:16500])
if __name__=="__main__":main()
