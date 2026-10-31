#!/usr/bin/env python3
"""Offline compare actual PS5 target compiler native vs emulated TLS *code shape*.

Host C++20 checks initializer, 64B alignment, isolation and destructor
lifecycle for both modes. PS5 object disassembly checks true ELF TLS
versus __emutls fallback. This does NOT run a PS5 loader or benchmark FPS.
"""
from pathlib import Path
import argparse
import subprocess,tempfile,re

SRC=Path(__file__).with_name("ps5-native-vs-emulated-tls.cpp")
DEFAULT=Path.home()/"work/ps5-rpcs3-app/.deps/native/ps5-payload-sdk/bin/prospero-clang++"

def run(*cmd):
 p=subprocess.run(list(map(str,cmd)),capture_output=True,text=True,timeout=55)
 if p.returncode:
  raise AssertionError(f"{cmd}\nexit={p.returncode}\n{p.stdout}\n{p.stderr}")
 return p.stdout

def main():
 ap=argparse.ArgumentParser()
 ap.add_argument("--compiler",type=Path,default=DEFAULT)
 args=ap.parse_args()
 with tempfile.TemporaryDirectory(prefix="ps5-tls-modes-") as d:
  out=Path(d)
  for mode,flag in (("native","-fno-emulated-tls"),("emulated","-femulated-tls")):
   obj=out/f"{mode}.o"
   run(args.compiler,"-std=c++20","-O2","-march=znver2",flag,
       "-ftls-model=initial-exec","-c",SRC,"-o",obj)
   symbols=run("llvm-readelf-19","-s",obj)
   reloc=run("llvm-readelf-19","-r",obj)
   disasm=run("llvm-objdump-19","-dr",obj)
   if mode=="native":
    assert re.search(r"\bTLS\b.*ps5_native_tls_pattern",symbols),symbols[-1000:]
    assert "R_X86_64_GOTTPOFF" in reloc or "R_X86_64_TPOFF32" in reloc,reloc
    assert "%fs:" in disasm or "fs:" in disasm
    assert "__emutls_get_address" not in disasm
   else:
    assert "__emutls_get_address" in (disasm+reloc), "no emutls runtime call"
    assert "__emutls_v.ps5_native_tls_pattern" in symbols
   exe=out/f"{mode}-lifecycle"
   run("clang++-19","-std=c++20","-O2","-pthread",flag,"-DPS5_HOST_TLS_LIFECYCLE_TEST",
       SRC,"-o",exe)
   run(exe)
   print(f"PASS {mode}: actual PS5 Clang object relocation + hosted C++20 thread init/alignment/isolation/destructor lifetime")
 print("LIMIT: host TLS lifecycle does not prove PS5 kernel loader/thread teardown; native vs emulated performance not measured.")

if __name__=="__main__":main()
