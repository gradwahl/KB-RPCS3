#!/usr/bin/env python3
"""Patch0069 reversible replay and fixed-size sampled producer/wait table tests."""
from pathlib import Path
import subprocess, tempfile, hashlib, json
ROOT=Path(__file__).resolve().parents[2]
PATCH=ROOT/"port/rpcs3-latest-patches/0069-PS5-sample-SPU-reservation-page-wait-outcomes-and-producer.patch"
NAMES=("rpcs3/Emu/Cell/SPUThread.cpp","rpcs3/Emu/Memory/vm.cpp","rpcs3/ps5/ps5_frontend.cpp","rpcs3/Emu/Cell/ps5_spu_wakeup.h")
def run(*cmd,cwd=None):
 p=subprocess.run(cmd,cwd=cwd,capture_output=True,text=True,timeout=45)
 if p.returncode:raise AssertionError(f"{cmd}\nexit={p.returncode}\n{p.stdout}\n{p.stderr}")
 return p.stdout
def check(src,orig):
 manifest=json.loads((orig/"manifest.json").read_text())
 assert manifest["patch_count"]==69
 current={n:(src/n).read_bytes() for n in NAMES}
 for n in NAMES:
  assert hashlib.sha256(current[n]).hexdigest()==manifest["after"][n],n
 assert PATCH.read_text().count("diff --git ")==4
 with tempfile.TemporaryDirectory() as d:
  root=Path(d);run("git","init","-q",str(root))
  for n,b in current.items():
   f=root/n;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(b)
  run("git","apply","--reverse","--check",str(PATCH),cwd=root)
  run("git","apply","--reverse",str(PATCH),cwd=root)
  assert not (root/NAMES[-1]).exists()
  for n in NAMES[:-1]:
   assert (root/n).read_bytes()==(orig/Path(n).name).read_bytes()
  run("git","apply","--check",str(PATCH),cwd=root)
  run("git","apply",str(PATCH),cwd=root)
  assert all((root/n).read_bytes()==current[n] for n in NAMES)
 print("PASS exact forward/reverse patch, original dirty state preserved")
 test=r"""
#define __PROSPERO__ 1
#include "rpcs3/Emu/Cell/ps5_spu_wakeup.h"
#include <cassert>
#include <thread>
#include <vector>
using namespace ps5_spu_wakeup;
int main()
{
 static_assert(sample_every==128 && slots==256 && probes==8);
 // Events are observed only one in 128 per host thread, never all calls.
 for (unsigned i=0;i<256;++i)
 {
  wait_probe p(0x12345100);
  if (p.sampled())p.finish(i==0,false);
 }
 auto* a=get_slot(0x12345000);
 assert(a && a->page_key.load()==(0x12345000u>>12)+1);
 auto x=read(*a);
 assert(x.waits==2 && x.changed==1 && x.unchanged==1);
 assert(x.cleared==0);
 for (unsigned i=0;i<256;++i)
 {
  if (sample_notification())note_notification(0x12345abc,producer::ppu);
 }
 auto y=read(*a);
 assert(y.ppu==2 && y.spu==0 && y.other==0);
 // Concurrent different guest pages must not conflate; same guest page
 // different offsets must resolve to one slot. Leave guest memory untouched.
 std::vector<std::thread> workers;
 for(unsigned t=0;t<6;++t)workers.emplace_back([t]{
  for(unsigned i=0;i<128;++i)
  {
   wait_probe p(0x20000000u+t*4096u+37u);
   if(p.sampled())p.finish(false,true);
   if(sample_notification())note_notification(0x20000000u+t*4096u+97u,producer::spu);
  }
 });
 for(auto& t:workers)t.join();
 for(unsigned t=0;t<6;++t)
 {
  auto* slot=get_slot(0x20000000u+t*4096u);
  assert(slot);
  const auto z=read(*slot);
  assert(z.waits==1 && z.cleared==1 && z.spu==1);
 }
 assert(overflow.load()==0 && wait_samples.load()==8 && producer_samples.load()==8);
}
"""
 with tempfile.TemporaryDirectory() as d:
  f=Path(d)/"check.cpp";f.write_text(test)
  for cc in ("clang++-19","g++"):
   try:run(cc,"--version")
   except FileNotFoundError:continue
   out=Path(d)/cc
   run(cc,"-std=c++20","-O2","-Wall","-Wextra","-Werror","-pthread","-I",str(src),str(f),"-o",str(out))
   run(str(out))
   print("PASS",cc,"C++20 bounded 4KiB page table, per-thread sampling, producer classes, race/concurrency")
if __name__=="__main__":
 import argparse
 p=argparse.ArgumentParser()
 p.add_argument("--source",type=Path,default=Path.home()/"work/rpcs3-latest")
 p.add_argument("--original",type=Path,default=Path.home()/"work/ps5spu0069-original-20261031")
 a=p.parse_args()
 check(a.source,a.original)
