#!/usr/bin/env python3
"""Check exact reversible patch0072 and default-off gating, no reset."""
from pathlib import Path
import subprocess,hashlib,json,tempfile
REPO=Path(__file__).resolve().parents[2]
PATCH=REPO/'port/rpcs3-latest-patches/0072-PS5-opt-in-CPU-topology-and-affinity-readback.patch'
FRONT='rpcs3/ps5/ps5_frontend.cpp'
HEAD='rpcs3/ps5/ps5_cpu_topology.h'

def run(*cmd,cwd=None):
 p=subprocess.run(cmd,cwd=cwd,text=True,capture_output=True,timeout=45)
 if p.returncode: raise AssertionError(f'{cmd}: {p.returncode}: {p.stderr}\n{p.stdout}')
 return p.stdout

def main():
 import argparse
 ap=argparse.ArgumentParser()
 ap.add_argument('--source',type=Path,default=Path.home()/'work/rpcs3-latest')
 ap.add_argument('--original',type=Path,default=Path.home()/'work/cpu-plan-topology0072-original-20261031')
 a=ap.parse_args()
 manifest=json.loads((a.original/'manifest.json').read_text('utf8'))
 assert manifest['patch']==72
 now={key:(a.source/key).read_bytes() for key in (FRONT,HEAD)}
 for name,bytes_ in now.items():
  assert hashlib.sha256(bytes_).hexdigest()==manifest['after'][name]
 assert '#define PS5_CPU_TOPOLOGY_PROBE 0' in now[HEAD].decode('utf8')
 assert 'PS5 TOPO SUMMARY:' in now[FRONT].decode('utf8')
 assert 'PS5 TOPO CPU:' in now[FRONT].decode('utf8')
 assert PATCH.read_text('utf8').count('diff --git ')==2
 with tempfile.TemporaryDirectory(prefix='cpu0072-verify-') as d:
  root=Path(d)
  run('git','init','-q',str(root))
  for key,bytes_ in now.items():
   dest=root/key;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(bytes_)
  run('git','apply','--reverse','--check',str(PATCH),cwd=root)
  run('git','apply','--reverse',str(PATCH),cwd=root)
  assert not (root/HEAD).exists()
  assert (root/FRONT).read_bytes()==(a.original/'ps5_frontend.cpp').read_bytes()
  assert hashlib.sha256((root/FRONT).read_bytes()).hexdigest()==manifest['before'][FRONT]
  run('git','apply','--check',str(PATCH),cwd=root)
  run('git','apply',str(PATCH),cwd=root)
  assert all((root/key).read_bytes()==value for key,value in now.items())
  check=root/'gate.cpp'
  check.write_text('#include "rpcs3/ps5/ps5_cpu_topology.h"\n'
                   '#if PS5_CPU_TOPOLOGY_PROBE != EXPECTED\n#error Wrong CPU probe gate\n#endif\n'
                   'int main() {return 0;}\n',encoding='utf8')
  for enable in (0,1):
   exe=root/f'gate{enable}'
   run('clang++-19','-std=c++20','-pthread','-Wall','-Wextra','-Werror',
       f'-DEXPECTED={enable}',f'-DPS5_CPU_TOPOLOGY_PROBE={enable}',
       '-I',str(a.source),str(check),'-o',str(exe))
   run(str(exe))
 print('PASS patch0072 exact forward/reverse, default-OFF and opt-in-ON C++20 gates')

if __name__=='__main__':main()
