#!/usr/bin/env python3
"""Synthetic ELF object-cache reader tests (no game/console access)."""
import gzip
import importlib.util
import subprocess
import tempfile
from pathlib import Path

TOOLS=Path(__file__).resolve().parents[2]/"tools/ps5-spu-jit-cache-inspect.py"
spec=importlib.util.spec_from_file_location("spu_object_inspect",TOOLS)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
with tempfile.TemporaryDirectory(prefix="cpu-hotjit-object-") as d:
    root=Path(d)
    source=root/"vec.cpp"
    source.write_text('''
using V=unsigned char __attribute__((vector_size(16)));
extern "C" __attribute__((noinline)) V insert_guest(V a, unsigned i, unsigned char b)
{
    a[i & 15u]=b;
    return a;
}
''')
    obj=root/"cache.o"
    subprocess.run(["clang++-19","-O3","-march=znver2","-c",str(source),"-o",str(obj)],check=True)
    gz=root/"cache.obj.gz"
    with gzip.open(gz,"wb") as f:f.write(obj.read_bytes())
    result=mod.inspect(gz,"insert_guest")
    assert result["functions"]["insert_guest"]["instructions"]>3
    assert result["functions"]["insert_guest"]["stack_operands"]>=1
    assert len(result["decompressed_elf_sha256"])==64
    try:mod.inspect(gz,"does_not_exist")
    except ValueError:pass
    else:raise AssertionError("incorrectly accepted unknown symbol")
    bad=root/"bad.obj.gz"
    with gzip.open(bad,"wb") as f:f.write(b"NOT ELF")
    try:mod.inspect(bad)
    except ValueError:pass
    else:raise AssertionError("incorrectly accepted invalid object")
print("PASS bounded gzip ELF64 JIT disassembly, symbol-specific instructions, stack tracking and invalid-object rejection")
