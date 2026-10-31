#!/usr/bin/env python3
"""Verify patch0066 source isolation and PS5 sampled RSX register-class histogram."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[2]
PATCH=ROOT/"port/rpcs3-latest-patches/0066-PS5-sample-RSX-method-address-class-histogram.patch"
FILES=("rpcs3/Emu/RSX/ps5_rsx_words.h","rpcs3/Emu/RSX/RSXFIFO.cpp","rpcs3/ps5/ps5_frontend.cpp")
def run(*cmd,cwd=None):
    p=subprocess.run(cmd,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=40)
    if p.returncode:
        raise AssertionError(f"{cmd} exit {p.returncode}\n{p.stdout}\n{p.stderr}")
    return p.stdout

def check(source:Path, original:Path):
    assert PATCH.is_file() and PATCH.read_text().count("diff --git ")==3
    cur={n:(source/n).read_bytes() for n in FILES}
    old={n:(original/n).read_bytes() for n in FILES}
    assert b"PS5 RSXCLASS: rank" in cur[FILES[2]]
    assert b"ps5_rsx_class::record_word(reg)" in cur[FILES[1]]
    assert b"ps5_rsx_class::record_handler(reg)" in cur[FILES[1]]
    with tempfile.TemporaryDirectory(prefix="rsx0066-patch-") as d:
        tmp=Path(d)
        run("git","init","-q",str(tmp))
        for n,blob in cur.items():
            path=tmp/n;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(blob)
        run("git","apply","--reverse","--check",str(PATCH),cwd=tmp)
        run("git","apply","--reverse",str(PATCH),cwd=tmp)
        for n,blob in old.items():
            assert (tmp/n).read_bytes()==blob,f"patch0066 modifies unrelated source {n}"
        run("git","apply","--check",str(PATCH),cwd=tmp)
        run("git","apply",str(PATCH),cwd=tmp)
        for n,blob in cur.items():assert (tmp/n).read_bytes()==blob,n
    print("PASS: reverse reproduces exact patch0065 source; forward replay byte exact")

    sample=r"""
#define __PROSPERO__ 1
#include "rpcs3/Emu/RSX/ps5_rsx_words.h"
#include <cassert>
int main()
{
 using namespace ps5_rsx_class;
 static_assert(count==256 && top_count==12);
 record_word(0x0001);record_handler(0x0001);
 record_word(0x0040);record_word(0x0041);record_handler(0x0040);
 record_word(0x2000);record_handler(0x2000);
 record_word(0x3fff);
#if PS5_RSX_CLASS_ACTIVE
 auto a=take();
 assert(a.words==5 && a.handlers==3 && a.nonempty==4);
 assert(a.hottest[0].index==1 && a.hottest[0].words==2 && a.hottest[0].handlers==1);
 assert(a.hottest[1].index==0 && a.hottest[1].words==1);
 assert(a.hottest[2].index==128);
 assert(a.hottest[3].index==255);
#else
 auto a=take();
 assert(a.words==0 && a.handlers==0 && a.nonempty==0);
#endif
 auto b=take();
 assert(b.words==0 && b.handlers==0 && b.nonempty==0 && !b.hottest[0].words);
 // Include the prior method words sampler; class probing must be independent.
 using namespace ps5_rsx_words;
 unsigned count=0;
 for(unsigned i=0;i<1024;++i)if(selected()){++count;record(10,8,0);}
 assert(count==2);
 auto c=ps5_rsx_words::take();
 assert(c.sampled_runs==2 && c.loop_words==20 && c.handler_calls==16);
 return 0;
}
"""
    with tempfile.TemporaryDirectory(prefix="rsx0066-clang-") as d:
        tmp=Path(d)
        unit=tmp/"test.cpp";unit.write_text(sample)
        for active in (0,1):
            exe=tmp/f"test-{active}"
            run("clang++-19","-std=c++20","-O2","-pthread",f"-DPS5_RSX_CLASS_ACTIVE={active}","-I",str(source),str(unit),"-o",str(exe))
            run(str(exe))
            print(f"PASS: class probe={active} C++20 semantics and unchanged 0065 sampler")
    print("PASS: patch0066 source and native header tests")


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--source",type=Path,default=Path.home()/"work/rpcs3-latest")
    p.add_argument("--original",type=Path,default=Path.home()/"work/rsx0066-original-20261031")
    a=p.parse_args()
    check(a.source,a.original)
