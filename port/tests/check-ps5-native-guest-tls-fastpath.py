#!/usr/bin/env python3
"""Reproduce PS5 native-TLS guest-context fast-path feasibility checks.

Compiles with the actual Prospero Clang target and the existing
-fno-emulated-tls / initial-exec / znver2 flags; verifies the
R_X86_64_GOTTPOFF relocation and compares native-TLS versus the
direct guest-context/local-store parameters that RPCS3 already has.

This is an OFFLINE microprobe. Do not infer an FPS win or modify live
JIT state based on this result.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import tempfile


HERE = Path(__file__).resolve().parent
PROBE = HERE / "ps5-native-guest-tls-assembly-probe.cpp"
HOST_TEST = HERE / "check-ps5-native-guest-tls-isolation.cpp"
DEFAULT_COMPILER = (
    Path.home()
    / "work/ps5-rpcs3-app/.deps/native/ps5-payload-sdk/bin/prospero-clang++"
)


def run(*args: str) -> str:
    proc = subprocess.run(
        args, capture_output=True, text=True, timeout=35, check=False
    )
    if proc.returncode:
        raise AssertionError(
            f"Command failed: {' '.join(args)}\n"
            f"exit={proc.returncode}\n{proc.stdout}\n{proc.stderr}"
        )
    return proc.stdout


def instructions(disassembly: str, name: str) -> list[str]:
    section = f"Disassembly of section .text.{name}:"
    start = disassembly.find(section)
    if start < 0:
        raise AssertionError(f"Missing function disassembly: {name}")
    end = disassembly.find("\nDisassembly of section ", start + len(section))
    chunk = disassembly[start:end if end >= 0 else None]
    # llvm-objdump --no-show-raw-insn emits one mnemonic per instruction;
    # uppercase R_X86_64 relocation records must NOT count as instructions.
    lines = [
        l.strip()
        for l in chunk.splitlines()
        if re.match(r"^\s*[0-9a-f]+:\s+[a-z][a-z0-9]*\b", l)
    ]
    if not lines:
        raise AssertionError(f"No instructions found for {name}")
    return lines


def check(compiler: Path) -> None:
    if not compiler.is_file():
        raise FileNotFoundError(compiler)
    with tempfile.TemporaryDirectory(prefix="ps5-native-guest-tls-") as tmp:
        folder = Path(tmp)
        obj = folder / "probe.o"
        run(
            str(compiler), "-std=c++20", "-O3", "-march=znver2",
            "-fno-emulated-tls", "-ftls-model=initial-exec",
            "-c", str(PROBE), "-o", str(obj),
        )
        dis = run("llvm-objdump-19", "--no-show-raw-insn", "-dr", str(obj))
        required = {
            "ps5_tls_r13": "ps5_direct_r13",
            "ps5_tls_ls_byte": "ps5_direct_ls_byte",
        }
        counts = {}
        for native_tls, direct in required.items():
            ni = instructions(dis, native_tls)
            di = instructions(dis, direct)
            assert len(ni) > len(di), (native_tls, len(ni), direct, len(di))
            assert any("%fs:" in line for line in ni), "Native TLS must use FS"
            assert not any("emutls" in l for l in ni)
            counts[native_tls] = len(ni)
            counts[direct] = len(di)
        assert "R_X86_64_GOTTPOFF" in dis and "ps5_current_guest" in dis
        readelf = run("llvm-readelf-19", "-s", str(obj))
        assert any(
            "TLS" in line and "ps5_current_guest" in line
            for line in readelf.splitlines()
        ), "Guest cache variable was not compiled as native TLS"
        exe = folder / "functional"
        run(
            "clang++-19", "-std=c++20", "-O3", "-Wall", "-Wextra",
            "-Werror", "-pthread", str(HOST_TEST), "-o", str(exe),
        )
        run(str(exe))
    print("PASS: actual PS5 compiler uses native TLS (R_X86_64_GOTTPOFF)")
    print("PASS: host TLS thread isolation, guest switch, unbind and pointer parity")
    for tls, direct in required.items():
        print(
            f"INSTRUCTIONS: {tls}={counts[tls]} vs "
            f"{direct}={counts[direct]} — direct pointer cheaper"
        )
    print("No emulator hot-path modification or FPS-speedup claim")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiler", type=Path, default=DEFAULT_COMPILER)
    args = parser.parse_args()
    check(args.compiler)
