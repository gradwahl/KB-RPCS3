#!/usr/bin/env python3
"""Cross-compile real PS5 diagnostic probe APIs OFF vs ON at O3/Zen2.

Instruction counts are static code shape, not host CPU timings or FPS.
No changes to active emulator, no console reads.
"""
from pathlib import Path
import argparse,re,subprocess,tempfile
SRC=Path(__file__).with_name("ps5-release-probe-assembly.cpp")
DEFAULT=Path.home()/"work/ps5-rpcs3-app/.deps/native/ps5-payload-sdk/bin/prospero-clang++"

def run(*cmd):
 p=subprocess.run(list(map(str,cmd)),capture_output=True,text=True,timeout=55)
 if p.returncode:
  raise AssertionError(f"{cmd}\nexit={p.returncode}\n{p.stdout}\n{p.stderr}")
 return p.stdout

def instructions(dis:str)->list[str]:
 m=re.search(r"<ps5_probe_guest_reservation>:\s*\n(.*?)(?=\n\S|\Z)",dis,re.S)
 assert m,dis[:1100]
 return [line for line in m.group(1).splitlines() if re.match(r"^\s*[0-9a-f]+:\s+[a-z]",line)]

def main():
 ap=argparse.ArgumentParser()
 ap.add_argument("--source",type=Path,default=Path.home()/"work/rpcs3-latest")
 ap.add_argument("--compiler",type=Path,default=DEFAULT)
 a=ap.parse_args()
 with tempfile.TemporaryDirectory(prefix="ps5-release-probe-ir-") as d:
  counts={}
  for mode in (0,1):
   obj=Path(d)/f"diagnostic-{mode}.o"
   run(a.compiler,"-std=c++20","-O3","-march=znver2","-fno-emulated-tls",
       "-ftls-model=initial-exec","-D__PROSPERO__",
       f"-DPS5_RELEASE_PROFILE_ACTIVE={mode}","-I",a.source,"-c",SRC,"-o",obj)
   listing=run("llvm-objdump-19","-d","--no-show-raw-insn",obj)
   ins=instructions(listing)
   counts[mode]=len(ins)
   if mode==0:
    assert len(ins)<=4,("OFF probe did not compile away",ins)
    assert not re.search(r"lock\s|clock_gettime|call",'\n'.join(ins))
   else:
    assert len(ins)>counts[0]+10,("ON probe unexpectedly just as small",ins)
   print(f"PS5 Zen2 target: diagnostic={mode}, reservation probe instructions={len(ins)}")
  print("PASS default OFF compiled to small no-profiling stub; ON emitted measured probe code")
  print("LIMIT instruction count does not equal execution time; no PS5 perf impact measured.")

if __name__=="__main__":main()
