#!/usr/bin/env python3
"""Read historical and patch0067 PS5 CPU reports within validated 45s captures.

The old top-14 CPU text truncates smaller workers. Thus its group sums
are *lower bounds*, NOT exact all-worker totals. New "group_ns" reports
are additive all registered RPCS3 thread nanoseconds, not per-frame
critical path or GPU work. Percentage baseline is ONE logical core.
"""
from __future__ import annotations
from pathlib import Path
import argparse
import json
import re
import statistics

STAMP=re.compile(r"(\d+):(\d\d):(\d\d)\.(\d+)")
CPU=re.compile(r"PS5 CPU: total (\d+)%")
FPS=re.compile(r"PS5 FPS: ([\d.]+)")
NEW=re.compile(r"group_ns window (\d+) ppu (\d+) spu (\d+) rsx_main (\d+) other (\d+) threads_ppu (\d+) threads_spu (\d+) threads_rsx_main (\d+) threads_other (\d+)")
THREAD=re.compile(r" (\d+)%$")

def when(s:str)->float:
    m=STAMP.search(s)
    if not m:raise ValueError("missing PS5 log timestamp")
    h,mn,sec,frac=m.groups()
    return int(h)*3600+int(mn)*60+int(sec)+int(frac)/10**len(frac)
def category(name:str)->str:
    if name.startswith("PPU["):return "ppu"
    if name.startswith("SPU["):return "spu"
    if name=="rsx::thread":return "rsx_main"
    return "other"

def cpu_row(line:str):
    m=CPU.search(line)
    if not m:return None
    data=line.split("PS5 CPU: ",1)[1].split(" | ")
    total=int(m.group(1))
    exact=NEW.search(line)
    if exact:
        win,ppu,spu,rsx,other,pc,sc,rc,oc=map(int,exact.groups())
        if win<=0 or max(ppu,spu,rsx,other)>win*200 or sum((ppu,spu,rsx,other))<0:
            raise ValueError("corrupt grouped CPU window")
        return {"mode":"exact","total_pct":total,"group_core_pct":{"ppu":100*ppu/win,"spu":100*spu/win,"rsx_main":100*rsx/win,"other":100*other/win},"window_ns":win,
                "group_ns":{"ppu":ppu,"spu":spu,"rsx_main":rsx,"other":other},
                "workers":{"ppu":pc,"spu":sc,"rsx_main":rc,"other":oc}}
    group=dict.fromkeys(("ppu","spu","rsx_main","other"),0)
    for part in data[1:]:
        tail=THREAD.search(part)
        if tail:group[category(part[:tail.start()])]+=int(tail.group(1))
    return {"mode":"top14_lower_bound","total_pct":total,"group_core_pct":group,"unassigned_or_rounding_core_pct":max(0,total-sum(group.values()))}

def analyse(stem:Path):
    m=json.loads(stem.with_suffix(".json").read_text(encoding="utf8"))
    assert m["valid"] and not m["new_spu_compilations"]
    text=stem.with_suffix(".log").read_text(encoding="utf8",errors="replace")
    lines=text.splitlines()
    fps_lines=[line for line in lines if FPS.search(line)]
    n=int(m["windows"])
    if len(fps_lines)<n+1:raise ValueError("missing FPS boundaries")
    start=when(fps_lines[-n-1])
    stop=when(fps_lines[-1])+.5
    rows=[]
    for line in lines:
        if "PS5 CPU: total " not in line:continue
        t=when(line)
        if not start<=t<=stop:continue
        r=cpu_row(line)
        if r:rows.append(r)
    if not rows:raise ValueError("no CPU samples inside capture window")
    modes={r["mode"] for r in rows}
    if len(modes)!=1:raise ValueError("mixed legacy/accurate group reports")
    keys=("ppu","spu","rsx_main","other")
    avg={k:round(statistics.mean(r["group_core_pct"][k] for r in rows),2) for k in keys}
    out={"capture":stem.name,"capture_valid":True,"cpu_report_count":len(rows),
         "mode":rows[0]["mode"],"sampled_log_time_s":[start,stop],"mean_total_log_core_pct":round(statistics.mean(r["total_pct"] for r in rows),2),
         "mean_group_core_pct":avg,"mean_group_all_hw_pct_16_logical_assumed":{k:round(avg[k]/16,2) for k in keys},
         "mean_group_core_equivalents":{k:round(avg[k]/100,3) for k in keys},
         "mean_unassigned_or_rounding_core_pct":round(statistics.mean(r.get("unassigned_or_rounding_core_pct",0) for r in rows),2),
         "mean_fps":m["mean_window_fps"],"capture_window_count":n,"new_spu_compilations":0,
         "limitations":("Legacy top14 workers only: group figures are lower bounds, aggregate/PPU/SPU/RSX ratios not complete; truncated small workers + percentage rounding. " if rows[0]["mode"].startswith("top14") else "All REGISTERED RPCS3 workers, not every kernel/driver thread; sampling contains signal skew. ") +
                       "CPU ns are host execution time, include waits in kernel, and do not establish frame dependency, GPU utilization, individual instruction costs or FPS benefit."}
    if rows[0]["mode"]=="exact":
        out["max_group_core_pct"]={k:round(max(r["group_core_pct"][k] for r in rows),2) for k in keys}
        out["min_group_core_pct"]={k:round(min(r["group_core_pct"][k] for r in rows),2) for k in keys}
        out["mean_worker_count"]={k:round(statistics.mean(r["workers"][k] for r in rows),2) for k in keys}
        for r in rows:
            sum_ns=sum(r["group_ns"].values())
            # integer total percentage is truncated; group reconstruction can be within ~1% point
            if abs(100*sum_ns/r["window_ns"] - r["total_pct"])>2:
                raise ValueError("group data inconsistent with logged total CPU time")
    return out

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("capture",type=Path,nargs="+")
    p.add_argument("--output",type=Path)
    a=p.parse_args()
    results=[analyse(path.with_suffix("")) for path in a.capture]
    data={"captures":results,"valid":all(x["capture_valid"] for x in results)}
    if a.output:
        if a.output.exists():raise SystemExit("output already exists, refusing to overwrite")
        a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(json.dumps(data,indent=2)+"\n",encoding="utf8")
    print(json.dumps(data,indent=2)[:18000])
if __name__=="__main__":main()
