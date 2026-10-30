#!/usr/bin/env python3
"""Test PS5 SPU tuning variants against the real title-side C parser."""
from pathlib import Path
import ctypes
import os
import subprocess
import sys
import tempfile

repo = Path(__file__).resolve().parents[2]
variant_dir = repo / "results/gta4-spu-tuning-20261030"
source = repo / "app/ps5/src/ps5_tuning.c"
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    libpath = root / "libps5tune.so"
    compiler = "clang-19"
    subprocess.run([compiler, "-x", "c", "-std=c11", "-shared", "-fPIC",
                    f'-DPS5_APP_ROOT="{root}"', str(source), "-o", str(libpath)],
                   check=True)
    lib = ctypes.CDLL(str(libpath))
    lib.rpcs3ps5_tune.argtypes = [ctypes.c_int]
    lib.rpcs3ps5_tune.restype = ctypes.c_int64
    lib.rpcs3ps5_tune_refresh.argtypes = []
    lib.rpcs3ps5_tune_refresh.restype = None
    lib.rpcs3ps5_tune_describe.restype = ctypes.c_char_p
    tuning = root / "rpcs3" / "ps5-tuning.txt"
    tuning.parent.mkdir()
    assert [lib.rpcs3ps5_tune(i) for i in (5, 6, 9)] == [0, 0, 0]
    cases = {
        "baseline": (0, 0, 0),
        "insert-select": (1, 0, 0),
        "narrow-check": (0, 1, 1),
        "narrow-perf": (0, 1, 0),
    }
    for i, (name, expected) in enumerate(cases.items()):
        tuning.write_bytes((variant_dir / (name + ".txt")).read_bytes())
        os.utime(tuning, (1700000000 + i * 5, 1700000000 + i * 5))
        lib.rpcs3ps5_tune_refresh()
        actual = tuple(lib.rpcs3ps5_tune(j) for j in (5, 6, 9))
        assert actual == expected, (name, actual, expected)
        # Neither the timing nor affinity defaults should be modified.
        assert [lib.rpcs3ps5_tune(j) for j in (0, 1, 2, 3, 4, 7, 10)] == [
            4000, 100, -1, 100, -1, -1, 0]
        assert b"unknown=" not in lib.rpcs3ps5_tune_describe()
        print(f"PASS: {name}: insert={actual[0]}, narrow={actual[1]}, check={actual[2]}")
    tuning.unlink()
    lib.rpcs3ps5_tune_refresh()
    assert tuple(lib.rpcs3ps5_tune(i) for i in (5, 6, 9)) == (0, 0, 0)
    print("PASS: deleting tuning file restores defaults")
