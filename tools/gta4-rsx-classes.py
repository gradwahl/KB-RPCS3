#!/usr/bin/env python3
"""Parse 0066 sampled RSX method-address histogram from a valid GTA IV capture.

Register offsets are RSX byte offsets grouped into 256-byte bands. Counts
represent only method-bearing run_FIFO samples selected 1 in 512; do not
interpret them as GPU instructions, full register traffic or CPU cost.
"""
from __future__ import annotations
from pathlib import Path
import argparse
import json
import re

TIME = re.compile(r"\b(\d+):(\d{2}):(\d{2})\.(\d+)")
HEAD = re.compile(r"PS5 RSXCLASS2: bucket_bytes (\d+) words (\d+) handlers (\d+) nonempty (\d+) top_limit (\d+)")
ROW = re.compile(r"PS5 RSXCLASS: rank (\d+) offset 0x([0-9a-fA-F]+) words (\d+) handlers (\d+)")
FPS = re.compile(r"PS5 FPS: ([\d.]+)")

def time_of(line: str) -> float:
    m=TIME.search(line)
    if not m: raise ValueError("missing timestamp")
    h,minute,second,frac=m.groups()
    return 3600*int(h)+60*int(minute)+int(second)+int(frac)/10**len(frac)

def analyse(stem: Path) -> dict:
    base=json.loads(stem.with_suffix(".json").read_text(encoding="utf-8"))
    if not base["valid"] or base["mode"]!="B" or base["resolution_scale"]!="150":
        raise ValueError("capture must be valid scheduler B 150%")
    if base.get("new_spu_compilations"):raise ValueError("new SPU compilation invalidates sample")
    if base.get("mfc_meter_mode")!=[["0","0"]]:raise ValueError("requires MFC gate0/helper probes0")
    lines=stem.with_suffix(".log").read_text(encoding="utf-8",errors="replace").splitlines()
    fps=[line for line in lines if FPS.search(line)]
    windows=base["windows"]
    if len(fps)<windows+1:raise ValueError("missing FPS window boundaries")
    start,stop=time_of(fps[-windows-1]),time_of(fps[-1])+.5
    reports=[]
    current=None
    for line in lines:
        if "PS5 RSXCLASS" not in line:continue
        stamp=time_of(line)
        if stamp<start or stamp>stop:continue
        if "PS5 RSXCLASS2:" in line:
            m=HEAD.search(line)
            if not m:raise ValueError("unexpected histogram header")
            width,words,handlers,nonempty,limit=map(int,m.groups())
            if width!=256 or limit!=12 or handlers>words or nonempty>256:
                raise ValueError("inconsistent histogram header")
            current={"time_s":stamp,"words":words,"handlers":handlers,
                     "nonempty":nonempty,"top":[]}
            reports.append(current)
        else:
            m=ROW.search(line)
            if not m:raise ValueError("unexpected histogram row")
            if current is None:raise ValueError("histogram rank without header")
            rank,offset,words,handlers=m.groups()
            rank,offset,words,handlers=int(rank),int(offset,16),int(words),int(handlers)
            if rank!=len(current["top"])+1 or offset>0xff00 or offset%256 or words<=0 or handlers>words:
                raise ValueError("invalid histogram rank or offset")
            current["top"].append({"rank":rank,"offset_bytes":offset,
                "offset_hi_bytes":offset+255,"words":words,"handlers":handlers})
    if not reports:raise ValueError("no RSXCLASS rows in capture window")
    combined={}
    for item in reports:
        hot=item["top"]
        if len(hot)>12 or len(hot)>item["nonempty"] or len({x["offset_bytes"] for x in hot})!=len(hot):
            raise ValueError("invalid top ranking")
        if any(hot[i]["words"]<hot[i+1]["words"] for i in range(len(hot)-1)):
            raise ValueError("histogram not sorted")
        if sum(x["words"] for x in hot)>item["words"] or sum(x["handlers"] for x in hot)>item["handlers"]:
            raise ValueError("rank totals exceed header totals")
        for row in hot:
            dst=combined.setdefault(row["offset_bytes"],{"offset_bytes":row["offset_bytes"],
                 "offset_hi_bytes":row["offset_hi_bytes"],"observed_top_words":0,
                 "observed_top_handlers":0,"top_reports":0})
            dst["observed_top_words"]+=row["words"]
            dst["observed_top_handlers"]+=row["handlers"]
            dst["top_reports"]+=1
    total_words=sum(x["words"] for x in reports)
    total_handlers=sum(x["handlers"] for x in reports)
    ranked=sorted(combined.values(),key=lambda r:(-r["observed_top_words"],r["offset_bytes"]))
    return {"capture":stem.name,"method_probe":"one of every 512 method-bearing FIFO calls",
        "bucket_bytes":256,"window_s":[start,stop],"report_count":len(reports),
        "total_sampled_loop_words":total_words,"total_sampled_direct_handlers":total_handlers,
        "sum_top12_words":sum(sum(row["words"] for row in item["top"]) for item in reports),
        "top12_coverage_fraction":round(sum(sum(row["words"] for row in item["top"]) for item in reports)/total_words,5) if total_words else None,
        "ranked_address_bands":ranked,
        "reports":reports,"valid":total_words>0,
        "limitations":"Only 1/512 method-bearing invocations; periodic phase bias possible. Top12 captures limited buckets, so aggregated band totals exclude windows when a band is not in top12. Header total counts all 256 buckets. Counts do not indicate per-method CPU time, GPU load or FPS gains."}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("capture",type=Path)
    a=p.parse_args()
    stem=a.capture.with_suffix("")
    result=analyse(stem)
    dest=stem.with_name(stem.name+"-rsx-classes").with_suffix(".json")
    if dest.exists():raise SystemExit("Refusing to overwrite "+str(dest))
    dest.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="reports"},indent=2)[:9000])
    print("Saved",dest)
if __name__=="__main__":main()
