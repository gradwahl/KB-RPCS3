#!/usr/bin/env python3
"""Patch0068 reversible replay + C++20 event counter and timer tests."""
from pathlib import Path
import json,subprocess,tempfile,hashlib

ROOT=Path(__file__).resolve().parents[2]
PATCH=ROOT/"port/rpcs3-latest-patches/0068-PS5-sample-SPU-reservation-wait-callback-CPU-wall-time.patch"
NAMES=("rpcs3/Emu/Cell/SPUThread.cpp","rpcs3/ps5/ps5_frontend.cpp","rpcs3/Emu/Cell/ps5_spu_reswait.h")
def run(*cmd,cwd=None):
 p=subprocess.run(cmd,cwd=cwd,capture_output=True,text=True,timeout=40)
 if p.returncode:raise AssertionError(f"{cmd}: exit {p.returncode}\n{p.stdout}\n{p.stderr}")
 return p.stdout
def check(src:Path,orig:Path):
 m=json.loads((orig/"manifest.json").read_text("utf8"))
 assert m["baseline"]==67 and m["selected"]==68
 current={n:(src/n).read_bytes() for n in NAMES}
 for n in NAMES:
  assert hashlib.sha256(current[n]).hexdigest()==m["patched_sha256"][Path(n).name]
 assert PATCH.read_text().count("diff --git ")==3
 with tempfile.TemporaryDirectory() as d:
  root=Path(d)
  run("git","init","-q",str(root))
  for n,b in current.items():
   p=root/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
  run("git","apply","--reverse","--check",str(PATCH),cwd=root)
  run("git","apply","--reverse",str(PATCH),cwd=root)
  assert not (root/NAMES[2]).exists()
  assert (root/NAMES[0]).read_bytes()==(orig/"SPUThread.cpp").read_bytes()
  assert (root/NAMES[1]).read_bytes()==(orig/"ps5_frontend.cpp").read_bytes()
  run("git","apply","--check",str(PATCH),cwd=root)
  run("git","apply",str(PATCH),cwd=root)
  for n,b in current.items():assert (root/n).read_bytes()==b
 print("PASS exact patch reverse/forward, baseline preserved")
 test=r"""
#include "rpcs3/Emu/Cell/ps5_spu_reswait.h"
#include <cassert>
#include <thread>
using namespace ps5_spu_reswait;
int main()
{
    static_assert(sample_period==128 && event_count==4);
    using E=event;
    assert(take(E::callback).calls==0);
    for (unsigned i=0;i<256;++i)
    {
        scope s(E::callback);
        for (volatile int j=0;j<900;++j) {}
    }
    auto c=take(E::callback);
    assert(c.calls==256 && c.samples==2);
    assert(c.wall_ns>0 && c.cpu_ns>0 && c.wall_max_ns>0);
    std::thread t([]{for(unsigned i=0;i<128;++i){scope s(E::atomic_wait);}});
    t.join();
    auto w=take(E::atomic_wait);
    assert(w.calls==128 && w.samples==1);
    {scope s(E::callback_notify);}
    {scope s(E::post_wait_notify);}
    assert(take(E::callback_notify).calls==1);
    assert(take(E::post_wait_notify).calls==1);
    auto later=take(E::callback);
    assert(later.calls==c.calls && later.samples==c.samples);
}
"""
 with tempfile.TemporaryDirectory() as d:
  root=Path(d);f=root/"test.cpp";f.write_text(test)
  for cc in ("clang++-19","g++"):
   try:run(cc,"--version")
   except FileNotFoundError:continue
   for mode in ("host","prospero"):
    if mode=="prospero" and cc!="clang++-19":continue
    e=root/f"{cc}-{mode}"
    run(cc,"-std=c++20","-O2","-Wall","-Wextra","-Wno-deprecated-volatile",
        "-pthread","-I",str(src),str(f),"-o",str(e))
    run(str(e))
    print("PASS C++20",cc,mode,"128-window sampling, exact counters and per-thread isolation")
if __name__=="__main__":
 import argparse
 p=argparse.ArgumentParser()
 p.add_argument("--source",type=Path,default=Path.home()/"work/rpcs3-latest")
 p.add_argument("--original",type=Path,default=Path.home()/"work/ps5spuwait0068-original-20261031")
 a=p.parse_args();check(a.source,a.original)
