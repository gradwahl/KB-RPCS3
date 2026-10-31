#!/usr/bin/env python3
"""Patch0074 exact reversible replay, C++ diagnostic hot-probe correctness.

Uses real source headers and (only for TSC) a host stub. OFF means no
SIGUSR1 registration, no probe writes, no JIT registry call; ON retains
instrumentation semantics. No PS5 process, game or caches touched.
"""
from pathlib import Path
import hashlib,json,subprocess,tempfile,textwrap

ROOT=Path(__file__).resolve().parents[2]
PATCH=ROOT/"port/rpcs3-latest-patches/0074-PS5-default-off-production-CPU-profiling.patch"
ORIGINAL=Path.home()/"work/cpu-plan-release-profile0074-original-20261031"
SOURCE=Path.home()/"work/rpcs3-latest"

def run(*cmd,cwd=None,allow_failure=False):
    p=subprocess.run(list(map(str,cmd)),cwd=cwd,text=True,capture_output=True,timeout=50)
    if p.returncode and not allow_failure:
        raise AssertionError(f"{cmd}: exit {p.returncode}\n{p.stdout}\n{p.stderr}")
    return p

CPP=r"""
#include "rpcs3/ps5/ps5_release_profile.h"
#include "rpcs3/Emu/Cell/ps5_spu_reswait.h"
#include "rpcs3/Emu/Cell/ps5_spu_wakeup.h"
#include "rpcs3/Emu/RSX/ps5_worker_activity.h"
#include "rpcs3/Emu/RSX/ps5_rsx_words.h"
#include <cassert>
#include <chrono>
#include <thread>
#include <cstdint>
using namespace std::chrono_literals;
int main() {
    static_assert(PS5_RELEASE_PROFILE_ACTIVE == EXPECTED);
    static_assert(PS5_RSX_WORDS_ACTIVE == EXPECTED);
    static_assert(PS5_RSX_CLASS_ACTIVE == EXPECTED);
    using namespace ps5_spu_reswait;
    {
        scope m(event::atomic_wait);
        std::this_thread::sleep_for(1ms);
    }
    auto s=take(event::atomic_wait);
    assert(s.calls==EXPECTED);
    assert(s.samples==EXPECTED);
    ps5_spu_wakeup::wait_probe w(0x100040);
    assert(w.sampled()==bool(EXPECTED));
    w.finish(true,false);
    assert(ps5_spu_wakeup::wait_samples.load()==EXPECTED);
    assert(ps5_spu_wakeup::sample_notification()==bool(EXPECTED));
    if constexpr (EXPECTED)
        ps5_spu_wakeup::note_notification(0x100040,ps5_spu_wakeup::producer::ppu);
    assert(ps5_spu_wakeup::producer_samples.load()==EXPECTED);
    auto* ptr=ps5_worker_activity::register_spu(0x10000);
    assert(bool(ptr)==bool(EXPECTED));
    ps5_worker_activity::begin_task(ptr,true);
    assert(ptr == nullptr || ptr->coverage.tasks.load()==1);
    auto t=ps5_worker_activity::begin_cpu_work(0x10000);
    assert(bool(t.slot)==bool(EXPECTED));
    ps5_worker_activity::end_cpu_work(t);
    auto stamp=utils::get_tsc();
    ps5_worker_activity::record_rsx(ps5_worker_activity::stage::rsx_fifo_running,stamp);
    assert(ps5_worker_activity::rsx[2].sampled.load()==EXPECTED);
    unsigned n=0;
    for(unsigned i=0;i<512;++i) if(ps5_rsx_words::selected())++n;
    assert(n==EXPECTED);
    ps5_rsx_class::record_word(0x400);
    assert(ps5_rsx_class::data[(0x400>>6)&255u].words.load()==EXPECTED);
    ps5_rsx_class::record_handler(0x400);
    assert(ps5_rsx_class::data[(0x400>>6)&255u].handlers.load()==EXPECTED);
    return 0;
}
"""

def main(source=SOURCE,original=ORIGINAL):
    m=json.loads((original/"manifest.json").read_text())
    assert m["patch"]==74
    files=m["files"]
    assert len(files)==8 and PATCH.read_text().count("diff --git ")==8
    before=m["before"];after=m["after"]
    assert all(hashlib.sha256((source/p).read_bytes()).hexdigest()==h for p,h in after.items())
    frontend=(source/"rpcs3/ps5/ps5_frontend.cpp").read_text()
    util=(source/"Utilities/Thread.cpp").read_text()
    jit=(source/"rpcs3/Emu/Cell/SPULLVMRecompiler.cpp").read_text()
    assert frontend.count("#if PS5_RELEASE_PROFILE_ACTIVE")>=2
    assert 'rpcs3ps5_tune_refresh();' in frontend.split("#else\n                // Preserve live tuning refresh")[1]
    assert "if (now - g_main_heartbeat > 20000" in frontend
    assert "pthread_kill(g_main_pthread, SIGUSR2);" in frontend
    assert '#if defined(__PROSPERO__) && PS5_RELEASE_PROFILE_ACTIVE' in util
    assert 'ps5_cpu_register(this, &m_tname);' in util
    assert 'ps5_jit_name(reinterpret_cast<u64>(fn)' in jit
    assert "PS5_RELEASE_PROFILE_ACTIVE" in jit
    assert '#define PS5_RELEASE_PROFILE_ACTIVE 0' in (source/files[-1]).read_text()
    with tempfile.TemporaryDirectory(prefix="release-profile0074-") as dirname:
        t=Path(dirname)
        run("git","init","-q",str(t))
        for p in files:
            d=t/p;d.parent.mkdir(parents=True,exist_ok=True);d.write_bytes((source/p).read_bytes())
        run("git","apply","--reverse","--check",PATCH,cwd=t)
        run("git","apply","--reverse",PATCH,cwd=t)
        assert not (t/files[-1]).exists()
        for p,h in before.items():
            assert (t/p).read_bytes()==(original/p).read_bytes()
            assert hashlib.sha256((t/p).read_bytes()).hexdigest()==h
        run("git","apply","--check",PATCH,cwd=t)
        run("git","apply",PATCH,cwd=t)
        for p,h in after.items():
            assert hashlib.sha256((t/p).read_bytes()).hexdigest()==h
        print("PASS patch0074 exact forward/reverse replay and previous dirty sources preserved")
        # Shadow only TSC hardware support, not the diagnostic source headers.
        (t/"util").mkdir()
        (t/"util/tsc.hpp").write_text(
            '#pragma once\n#include <atomic>\n#include <cstdint>\n'
            'namespace utils { inline std::atomic<std::uint64_t> counter{500}; '
            'inline std::uint64_t get_tsc() { return counter.fetch_add(500); } }\n'
        )
        p=t/"probe.cpp";p.write_text(CPP)
        for value in (0,1):
            exe=t/f"probe_{value}"
            run("clang++-19","-std=c++20","-O2","-pthread","-Wall","-Wextra",
                "-D__PROSPERO__",f"-DEXPECTED={value}",
                f"-DPS5_RELEASE_PROFILE_ACTIVE={value}",
                "-I",t,"-I",source,p,"-o",exe)
            run(exe)
        print("PASS native header functional host tests: diagnostic OFF=no atomic samples; ON=counters, RSX methods, SPU samples")

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--source",type=Path,default=SOURCE)
    p.add_argument("--original",type=Path,default=ORIGINAL)
    a=p.parse_args()
    main(a.source,a.original)
