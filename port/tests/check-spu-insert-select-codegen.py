#!/usr/bin/env python3
"""Offline PS5 SPU JIT insertion-lowering equivalence and Zen2 codegen gate.

Generates LLVM IR matching the *shapes* of RPCS3's existing variable-index
insertelement and optional ps5_insert_by_select (u8/u16/u32/u64 over 128 bits).
Assembles both with LLVM 19, compiles actual PS5-target Zen2 objects, and
runs a Linux-host semantic oracle across thousands of indices/values.

This isolates the lowering, not complete guest SPU functions or RPCS3's
LLVM JIT version. Instruction counts are NOT an FPS benchmark.
Does NOT modify the RPCS3 source, tuning, caches or live console.
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

LANES = [(8, 16), (16, 8), (32, 4), (64, 2)]
HERE = Path(__file__).resolve().parent


def run(*argv: object) -> str:
    args = [str(x) for x in argv]
    p = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if p.returncode:
        raise AssertionError(f"{args} exit={p.returncode}\n{p.stdout}\n{p.stderr}")
    return p.stdout


def make_ir() -> str:
    chunks = [
        "; Derived from SPULLVMRecompiler.cpp ps5_insert_by_select.",
        "; Both paths mask the lane to preserve the same intended semantics.",
        'target triple = "x86_64-sie-ps5"',
        "",
    ]
    for width, n in LANES:
        ty = f"i{width}"
        v = f"<{n} x {ty}>"
        for kind in ("default", "select"):
            fn = f"insert_{kind}_i{width}"
            code = [
                f"define {v} @{fn}({v} %v, i32 %idx, {ty} %elt) {{",
                "entry:",
                f"  %lane = and i32 %idx, {n - 1}",
            ]
            if kind == "default":
                code += [
                    f"  %out = insertelement {v} %v, {ty} %elt, i32 %lane",
                    f"  ret {v} %out",
                ]
            else:
                lane = "%lane"
                if width != 32:
                    op = "trunc" if width < 32 else "zext"
                    code.append(f"  %lanew = {op} i32 %lane to {ty}")
                    lane = "%lanew"
                code += [
                    f"  %idxseed = insertelement {v} poison, {ty} {lane}, i32 0",
                    f"  %idxsplat = shufflevector {v} %idxseed, {v} poison, <{n} x i32> zeroinitializer",
                    f"  %cmp = icmp eq {v} %idxsplat, <{', '.join(f'{ty} {i}' for i in range(n))}>",
                    f"  %eltseed = insertelement {v} poison, {ty} %elt, i32 0",
                    f"  %eltsplat = shufflevector {v} %eltseed, {v} poison, <{n} x i32> zeroinitializer",
                    f"  %out = select <{n} x i1> %cmp, {v} %eltsplat, {v} %v",
                    f"  ret {v} %out",
                ]
            code += ["}", ""]
            chunks.extend(code)
    return "\n".join(chunks) + "\n"


CPP = r"""
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <random>
using V8 = uint8_t __attribute__((vector_size(16)));
using V16 = uint16_t __attribute__((vector_size(16)));
using V32 = uint32_t __attribute__((vector_size(16)));
using V64 = uint64_t __attribute__((vector_size(16)));
extern "C" {
V8 insert_default_i8(V8, uint32_t, uint8_t);
V8 insert_select_i8(V8, uint32_t, uint8_t);
V16 insert_default_i16(V16, uint32_t, uint16_t);
V16 insert_select_i16(V16, uint32_t, uint16_t);
V32 insert_default_i32(V32, uint32_t, uint32_t);
V32 insert_select_i32(V32, uint32_t, uint32_t);
V64 insert_default_i64(V64, uint32_t, uint64_t);
V64 insert_select_i64(V64, uint32_t, uint64_t);
}
template<typename V, typename E, size_t N>
bool test(const char* label, V (*a)(V,uint32_t,E), V (*b)(V,uint32_t,E), std::mt19937_64& rng)
{
    for (unsigned i = 0; i < 4096; ++i)
    {
        std::array<E,N> data{}, original{}, left{}, right{};
        for (auto &x : data) x = static_cast<E>(rng());
        V input;
        std::memcpy(&input,data.data(),16);
        const uint32_t idx = i < N ? i : static_cast<uint32_t>(rng());
        const E elt = static_cast<E>(rng());
        const V va = a(input,idx,elt);
        const V vb = b(input,idx,elt);
        std::memcpy(left.data(),&va,16);
        std::memcpy(right.data(),&vb,16);
        original = data;
        original[idx & (N-1)] = elt;
        if (left!=original || right!=original)
        {
            std::fprintf(stderr,"FAIL %s iteration %u lane %u\n",label,i,idx&(N-1));
            return false;
        }
    }
    std::printf("PASS %s 4096 random/boundary exact lane comparisons\n",label);
    return true;
}
int main()
{
    std::mt19937_64 rng(0x5EEDBEEFFEED1234ull);
    if (!test<V8,uint8_t,16>("u8",insert_default_i8,insert_select_i8,rng)) return 1;
    if (!test<V16,uint16_t,8>("u16",insert_default_i16,insert_select_i16,rng)) return 2;
    if (!test<V32,uint32_t,4>("u32",insert_default_i32,insert_select_i32,rng)) return 3;
    if (!test<V64,uint64_t,2>("u64",insert_default_i64,insert_select_i64,rng)) return 4;
    return 0;
}
"""


def functions(dump: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    current = ""
    for line in dump.splitlines():
        match = re.search(r"<(insert_(?:default|select)_i(?:8|16|32|64))>:", line)
        if match:
            current = match.group(1)
            found[current] = []
            continue
        if not current:
            continue
        if re.match(r"^[\da-f]+ <", line):
            current = ""
            continue
        if re.match(r"^\s*[\da-f]+:\s+[a-z]", line):
            found[current].append(line.strip())
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, help="Write non-sensitive JSON evidence")
    opt = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix="spu-insert-select-") as temp:
        td = Path(temp)
        ir = td / "insert.ll"
        ir.write_text(make_ir(), encoding="utf-8")
        run("llvm-as-19", ir, "-o", td / "insert.bc")
        # Actual native PS5 target and exact Zen2 CPU, not an X86-host guess.
        obj = td / "ps5.o"
        run("llc-19", "-mtriple=x86_64-sie-ps5", "-mcpu=znver2",
            "-O=3", "-filetype=obj", ir, "-o", obj)
        listing = run("llvm-objdump-19", "-d", "-M", "intel",
                      "--no-show-raw-insn", obj)
        fns = functions(listing)
        assert len(fns) == 8, (list(fns), listing[:1500])
        results = {}
        for width, n in LANES:
            results[str(width)] = {}
            for kind in ("default", "select"):
                name = f"insert_{kind}_i{width}"
                lines = fns[name]
                assert len(lines) > 1
                stack = sum(bool(re.search(r"\[\s*rsp\s*[+\]-]|\[\s*rbp\s*[+\]-]", line)) for line in lines)
                results[str(width)][kind] = {
                    "instructions": len(lines), "stack_operand_instructions": stack,
                    "stack_extract_instructions": sum("vpextr" in line and "rsp" in line for line in lines),
                    "mnemonics": [line.split(":", 1)[1].strip().split()[0] for line in lines],
                    "disassembly": lines,
                }
        # Separate target from functional execution; never try to execute PS5 objects on Linux.
        host_obj = td / "linux.o"
        run("llc-19", "-mtriple=x86_64-pc-linux-gnu", "-mcpu=znver2",
            "-O=3", "-filetype=obj", ir, "-o", host_obj)
        harness = td / "verify.cpp"
        harness.write_text(CPP, encoding="utf-8")
        exe = td / "verify"
        run("clang++-19", "-std=c++20", "-O2", "-march=znver2", "-Wall",
            "-Wextra", harness, host_obj, "-o", exe)
        oracle = run(exe)
    results_obj = {
        "date": "2026-10-31",
        "test": "SPU 128-bit variable-index insertion, default LLVM insertelement vs current optional LLVM compare/select",
        "source": "rpcs3/Emu/Cell/SPULLVMRecompiler.cpp ps5_insert_by_select, PS5 TUNE key 5",
        "LLVM": "LLVM 19 offline (runtime RPCS3 JIT LLVM version may differ)",
        "target": "x86_64-sie-ps5 / znver2",
        "oracle": "Linux x86-64/znver2 callable object, each width 4096 random+edge semantic checks",
        "oracle_result": "PASS",
        "sampled_actual_game_blocks": False,
        "sampled_runtime_fps": False,
        "codegen": results,
        "limitations": "Isolated LLVM IR shapes; not the full SPU JIT block or runtime JIT LLVM backend. Instruction/stack operand counts cannot establish throughput or FPS. Never turn on flags globally based on this.",
    }
    print(oracle, end="")
    print(json.dumps({"target": results_obj["target"], "codegen": results}, indent=2))
    if opt.output:
        if opt.output.exists():
            raise FileExistsError(opt.output)
        opt.output.parent.mkdir(parents=True, exist_ok=True)
        opt.output.write_text(json.dumps(results_obj, indent=2) + "\n", encoding="utf-8")
        print(f"PASS wrote {opt.output}")


if __name__ == "__main__":
    main()
