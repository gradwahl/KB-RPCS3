#!/usr/bin/env python3
"""Validate patch 0065 as strictly diagnostic RSX method-loop accounting.

Tests the exact installed WSL source and patch against archived pre-0065
bytes, including reversible replay, plus actual Clang C++20 header behavior
with the probe ON and OFF. Never edits the live WSL sources.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[2]
PATCH = REPO / "port/rpcs3-latest-patches/0065-PS5-sample-RSX-method-words-per-FIFO-run.patch"
FILES = ("rpcs3/Emu/RSX/RSXFIFO.cpp", "rpcs3/ps5/ps5_frontend.cpp")
HEADER = "rpcs3/Emu/RSX/ps5_rsx_words.h"


def run(*args, cwd=None):
    result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=30)
    if result.returncode:
        raise AssertionError(f"{args}: {result.returncode}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def check(source: Path, original: Path):
    assert PATCH.is_file() and PATCH.read_text().count("diff --git ") == 3
    # Compare against the recorded source state, not a misleading clean HEAD:
    # prior port patches are deliberately uncommitted inside the WSL tree.
    current = {r: (source / r).read_bytes() for r in (*FILES, HEADER)}
    expected = {r: (original / r).read_bytes() for r in FILES}
    assert b"PS5 RSXWORDS: every 512 method_runs" in current["rpcs3/ps5/ps5_frontend.cpp"]
    fifo = current[FILES[0]]
    assert fifo.count(b"ps5_sample_method_words") == 5
    assert b"if (ps5_sample_method_words) ++ps5_method_loop_words;" in fifo
    assert b"if (ps5_sample_method_words) ++ps5_method_handlers;" in fifo
    assert b"if (ps5_sample_method_words) ++ps5_flattened_skips;" in fifo
    assert b"fifo_ctrl->sync_get();" in fifo
    with tempfile.TemporaryDirectory(prefix="ps5-rsx-words-") as temp:
        tempdir = Path(temp)
        run("git", "init", "-q", str(tempdir))
        for r, blob in current.items():
            file = tempdir / r
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(blob)
        run("git", "apply", "--reverse", "--check", str(PATCH), cwd=tempdir)
        run("git", "apply", "--reverse", str(PATCH), cwd=tempdir)
        for r, blob in expected.items():
            assert (tempdir / r).read_bytes() == blob, f"RSX 0065 changed non-probe source: {r}"
        assert not (tempdir / HEADER).exists(), "0065 header not removed by reverse replay"
        run("git", "apply", "--check", str(PATCH), cwd=tempdir)
        run("git", "apply", str(PATCH), cwd=tempdir)
        for r, blob in current.items():
            assert (tempdir / r).read_bytes() == blob, f"Forward replay differs: {r}"
    print("PASS: full 0065 reverse reconstructs exactly archived sources; forward replay byte-exact")

    harness = r'''
#define __PROSPERO__ 1
#include "rpcs3/Emu/RSX/ps5_rsx_words.h"
#include <cassert>
#include <cstdint>
int main()
{
    using namespace ps5_rsx_words;
    unsigned selected_count = 0;
    for (unsigned i = 0; i < 1024; ++i)
    {
        if (selected())
        {
            ++selected_count;
            record(12, 8, 1);
            record(4, 3, 0);
        }
    }
#if PS5_RSX_WORDS_ACTIVE
    assert(selected_count == 2);
    auto a = take();
    assert(a.sampled_runs == 4 && a.loop_words == 32);
    assert(a.handler_calls == 22 && a.flattened_skips == 2);
    assert(a.max_words_in_run == 12);
#else
    assert(selected_count == 0);
    auto a = take();
    assert(a.sampled_runs == 0 && a.loop_words == 0);
    assert(a.handler_calls == 0 && a.flattened_skips == 0);
#endif
    auto b = take();
    assert(b.sampled_runs == 0 && b.loop_words == 0);
    assert(b.handler_calls == 0 && b.flattened_skips == 0);
    assert(b.max_words_in_run == 0);
    return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix="ps5-rsx-words-cxx-") as temp:
        tempdir = Path(temp)
        test = tempdir / "test.cpp"
        test.write_text(harness)
        for active in (0, 1):
            exe = tempdir / f"probe-{active}"
            run("clang++-19", "-std=c++20", "-O2", "-pthread",
                f"-DPS5_RSX_WORDS_ACTIVE={active}",
                "-I", str(source), str(test), "-o", str(exe))
            run(str(exe))
            print(f"PASS: compiled native Clang header test with probe={active}")
    print("PASS: patch 0065 is source-reversible and counter semantics validated")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path.home() / "work/rpcs3-latest")
    parser.add_argument("--original", type=Path, default=Path.home() / "work/rsx0065-original-20261031")
    args = parser.parse_args()
    check(args.source, args.original)
