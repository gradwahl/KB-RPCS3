#!/usr/bin/env python3
"""Patch0070 reverse/forward replay and opt-in/zero-dump source gates."""
from pathlib import Path
import hashlib, json, subprocess, tempfile

REPO = Path(__file__).resolve().parents[2]
PATCH = REPO / "port/rpcs3-latest-patches/0070-PS5-opt-in-SPU-JIT-hot-function-sampler.patch"
FILES = ("Utilities/Thread.cpp", "rpcs3/ps5/ps5_frontend.cpp", "rpcs3/ps5/ps5_spu_hotjit.h")


def run(*cmd, cwd=None):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=45)
    if p.returncode:
        raise AssertionError(f"{cmd}\nexit={p.returncode}\n{p.stdout}\n{p.stderr}")
    return p.stdout


def check(src: Path, orig: Path):
    manifest = json.loads((orig / "manifest.json").read_text("utf8"))
    assert manifest["patch"] == 70
    fresh = {p: (src / p).read_bytes() for p in FILES}
    assert PATCH.read_text().count("diff --git ") == 3
    for path, data in fresh.items():
        assert hashlib.sha256(data).hexdigest() == manifest["after"][path]
    with tempfile.TemporaryDirectory(prefix="hotjit0070-replay-") as d:
        tmp = Path(d)
        run("git", "init", "-q", str(tmp))
        for filename, data in fresh.items():
            path = tmp / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        run("git", "apply", "--reverse", "--check", str(PATCH), cwd=tmp)
        run("git", "apply", "--reverse", str(PATCH), cwd=tmp)
        assert not (tmp / FILES[-1]).exists()
        for filename in FILES[:-1]:
            assert (tmp / filename).read_bytes() == (orig / Path(filename).name).read_bytes()
        run("git", "apply", "--check", str(PATCH), cwd=tmp)
        run("git", "apply", str(PATCH), cwd=tmp)
        for filename, data in fresh.items():
            assert (tmp / filename).read_bytes() == data
        print("PASS patch0070 exact reverse/forward replay, originals preserved")
        header = src / FILES[-1]
        p = tmp / "test.cpp"
        p.write_text(
            '#include "rpcs3/ps5/ps5_spu_hotjit.h"\n'
            '#if PS5_SPU_HOTJIT_ACTIVE != EXPECTED\n#error opt-in gate mismatch\n#endif\n'
            'int main(){return PS5_SPU_HOTJIT_ACTIVE == EXPECTED ? 0:1;}\n'
        )
        for enable in (0, 1):
            exe = tmp / f"gate{enable}"
            run("clang++-19", "-std=c++20", "-Wall", "-Wextra", "-Werror",
                f"-DEXPECTED={enable}", f"-DPS5_SPU_HOTJIT_ACTIVE={enable}",
                "-I", str(src), str(p), "-o", str(exe))
            run(str(exe))
        print("PASS Clang19 C++20 default OFF / explicit diagnostic ON gate")
    code = fresh[FILES[0]].decode("utf8")
    frontend = fresh[FILES[1]].decode("utf8")
    assert "if (dump_jit)" in code
    assert "ps5_thread_profile(target, 200, false)" in frontend
    assert "PS5_SPU_HOTJIT_ACTIVE" in frontend
    assert "name.rfind(\"SPU[\", 0) == 0" in frontend
    assert "PS5_RSX_PERF_ACTIVE && cpu_reports % 2 == 0" in frontend
    print("PASS separate SPU-only sample mode, no new handler or automatic dumps")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, default=Path.home() / "work/rpcs3-latest")
    p.add_argument("--original", type=Path, default=Path.home() / "work/cpu-plan-hotjit0070-original-20261031")
    opts = p.parse_args()
    check(opts.source, opts.original)
