#!/usr/bin/env python3
"""Host-only validation of PS5 CPU group accounting, source isolation and replay."""
from pathlib import Path
import json
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[2]
PATCH=ROOT/"port/rpcs3-latest-patches/0067-PS5-report-exact-PPU-SPU-RSX-main-host-CPU-time.patch"
NAMES=("Utilities/Thread.cpp","rpcs3/ps5/ps5_cpu_groups.h")
def run(*cmd,cwd=None):
    p=subprocess.run(cmd,cwd=cwd,capture_output=True,text=True,timeout=35)
    if p.returncode:raise AssertionError(f"{cmd} -> {p.returncode}\n{p.stdout}\n{p.stderr}")
    return p.stdout
def check(source,orig):
    assert PATCH.exists() and PATCH.read_text().count("diff --git ")==2
    current={x:(source/x).read_bytes() for x in NAMES}
    assert current["Utilities/Thread.cpp"].count(b'group_ns window')==1
    assert current["Utilities/Thread.cpp"].count(b'ps5_thread_cpu_report(u64 window_ns, usz top)')==1
    assert b'pthread_getcpuclockid' not in current["rpcs3/ps5/ps5_cpu_groups.h"]
    before=(orig/"Thread.cpp").read_bytes()
    with tempfile.TemporaryDirectory() as d:
        root=Path(d)
        run("git","init","-q",str(root))
        for n,data in current.items():
            file=root/n;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(data)
        run("git","apply","--reverse","--check",str(PATCH),cwd=root)
        run("git","apply","--reverse",str(PATCH),cwd=root)
        assert (root/NAMES[0]).read_bytes()==before
        assert not (root/NAMES[1]).exists()
        run("git","apply","--check",str(PATCH),cwd=root)
        run("git","apply",str(PATCH),cwd=root)
        for n,blob in current.items():assert (root/n).read_bytes()==blob,n
    print("PASS: reversible source patch, no pre-existing changes lost")
    test=r"""
#include "rpcs3/ps5/ps5_cpu_groups.h"
#include <cassert>
#include <cstdint>
using namespace ps5_cpu_groups;
int main()
{
    static_assert(classify("PPU[0x1000000] main_thread")==kind::ppu);
    static_assert(classify("SPU[0x0000100] PrimaryCellSpursKernel0")==kind::spu);
    static_assert(classify("rsx::thread")==kind::rsx_main);
    static_assert(classify("rsx::Offloader")==kind::other);
    static_assert(classify("Pad Thread")==kind::other);
    static_assert(classify("")==kind::other);
    totals c{};
    c.add("PPU[0x10] a",500);
    c.add("PPU[0x11] b",200);
    c.add("SPU[0x20] c",800);
    c.add("rsx::thread",400);
    c.add("rsx::Offloader",300);
    c.add("Pad Thread",100);
    assert(c.ppu_ns==700 && c.spu_ns==800 && c.rsx_main_ns==400 && c.other_ns==400);
    assert(c.ppu_threads==2 && c.spu_threads==1 && c.rsx_main_threads==1 && c.other_threads==2);
    assert(c.all_ns()==2300);
}
"""
    with tempfile.TemporaryDirectory() as d:
        t=Path(d)/"unit.cpp";t.write_text(test)
        for compiler in ("clang++-19","g++"):
            try:run(compiler,"--version")
            except (FileNotFoundError,AssertionError):continue
            exe=Path(d)/("test-"+compiler)
            run(compiler,"-std=c++20","-Wall","-Wextra","-Werror","-O2","-I",str(source),str(t),"-o",str(exe))
            run(str(exe))
            print("PASS:",compiler,"C++20 classification / full-worker accounting")
if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--source",type=Path,default=Path.home()/"work/rpcs3-latest")
    p.add_argument("--original",type=Path,default=Path.home()/"work/ps5cpu0067-original-20261031")
    a=p.parse_args();check(a.source,a.original)
