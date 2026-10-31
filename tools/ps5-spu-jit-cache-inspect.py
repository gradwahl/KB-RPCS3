#!/usr/bin/env python3
"""Safely disassemble a cached RPCS3 SPU LLVM object (.obj.gz or .o).

Unlike the in-memory legacy ps5_jit_save(), this reads a known bounded
object from disk and uses the ELF symbol table for *real* function bounds.
Use the profile hash to select the exact cache file, and compare the same
function with opt-in insertion OFF/ON from separately warmed builds.
LLVM objdump 19 can disassemble x86-64 output emitted by LLVM 22; the
disassembler's version is not evidence of the compiler's backend version.
"""
from __future__ import annotations
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import re
import subprocess
import tempfile

MAX_OBJECT_BYTES = 64 * 1024 * 1024
SYM = re.compile(r"^\s*[0-9a-fA-F]+ <([^<>]+)>:$")
INST = re.compile(r"^\s*[0-9a-fA-F]+:\s+([a-z][a-z0-9.]*)\s*(.*)")
STACK = re.compile(r"\[(?:[^\]]*\b(?:rsp|rbp)\b[^\]]*)\]", re.I)
VECTOR_SPILL = re.compile(r"\b(?:vmov|movdqu|movaps)[a-z0-9]*\b", re.I)


def command(*argv: str) -> str:
    p = subprocess.run(argv, text=True, capture_output=True, timeout=45)
    if p.returncode != 0:
        raise RuntimeError(f"{argv} returned {p.returncode}: {p.stderr[:1500]}")
    return p.stdout


def bounded_object(path: Path) -> bytes:
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size > MAX_OBJECT_BYTES:
        raise ValueError(f"compressed object exceeds {MAX_OBJECT_BYTES} bytes")
    if path.suffix == ".gz":
        with gzip.open(path, "rb") as stream:
            blob = stream.read(MAX_OBJECT_BYTES + 1)
    else:
        with path.open("rb") as stream:
            blob = stream.read(MAX_OBJECT_BYTES + 1)
    if len(blob) > MAX_OBJECT_BYTES:
        raise ValueError("uncompressed object exceeds safety cap")
    if blob[:4] != b"\x7fELF":
        raise ValueError("not an ELF object, refuse to interpret as JIT code")
    if blob[4] != 2 or blob[5] != 1:
        raise ValueError("expected little-endian ELF64")
    return blob


def inspect(path: Path, selected: str | None = None) -> dict:
    blob = bounded_object(path)
    with tempfile.TemporaryDirectory(prefix="spu-jit-object-") as folder:
        object_path = Path(folder) / "jit.o"
        object_path.write_bytes(blob)
        header = command("llvm-readelf-19", "-h", str(object_path))
        if "X86-64" not in header or "REL (Relocatable file)" not in header:
            raise ValueError("not a relocatable x86-64 LLVM object")
        dump = command("llvm-objdump-19", "-d", "--no-show-raw-insn", "-M", "intel", str(object_path))
    entries: dict[str, dict] = {}
    current = None
    for line in dump.splitlines():
        sym = SYM.match(line)
        if sym:
            current = sym.group(1)
            entries[current] = {"instructions": 0, "stack_operands": 0,
                "vector_stack_instructions": 0, "stack_extractions": 0,
                "instruction_mnemonics": {}, "sample_disassembly": []}
            continue
        ins = INST.match(line)
        if not ins or current is None:
            continue
        mnemonic, arguments = ins.groups()
        item = entries[current]
        item["instructions"] += 1
        item["instruction_mnemonics"][mnemonic] = item["instruction_mnemonics"].get(mnemonic, 0) + 1
        if STACK.search(arguments):
            item["stack_operands"] += 1
            if VECTOR_SPILL.match(mnemonic):
                item["vector_stack_instructions"] += 1
            if mnemonic.startswith("vpextr"):
                item["stack_extractions"] += 1
        if len(item["sample_disassembly"]) < 24:
            item["sample_disassembly"].append(line.strip())
    if not entries:
        raise ValueError("no disassembled ELF function symbols")
    if selected is not None:
        if selected not in entries:
            raise ValueError(f"no exact ELF symbol named {selected}; examples: {list(entries)[:5]}")
        entries = {selected: entries[selected]}
    return {
        "source": str(path),
        "compressed_file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "decompressed_elf_sha256": hashlib.sha256(blob).hexdigest(),
        "backend_version": "UNVERIFIED: determine from matching RPCS3 build/cache manifest, not objdump",
        "format": "ELF64 x86-64 relocatable, symbol-based disassembly",
        "functions": entries,
        "limitations": [
            "Object symbols bound disassembled functions, unlike runtime nearest-entry 256KiB heuristics.",
            "Instruction and stack-operation counts alone are not execution-weighted guest CPU time.",
            "Different cache objects or recompilation flags may produce different functions; match complete guest hashes and build versions.",
            "An LLVM19 disassembler can read LLVM22-generated x86-64 bytes, but the object cannot independently prove the backend release.",
            "Never fetch or dump executing memory; provide explicit archived cache object files only."
        ],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("object_file", type=Path)
    p.add_argument("--function", help="Exact ELF function symbol, including __spu hash")
    p.add_argument("--output", type=Path)
    a = p.parse_args()
    report = inspect(a.object_file, a.function)
    if a.output:
        if a.output.exists():
            raise FileExistsError(f"refusing overwrite: {a.output}")
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    print(json.dumps(report, indent=2)[:22000])


if __name__ == "__main__":
    main()
