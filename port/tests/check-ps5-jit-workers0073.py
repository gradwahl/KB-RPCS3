#!/usr/bin/env python3
"""Patch0073 exact reversible replay, source isolation, worker-count C++ tests."""
from pathlib import Path
import subprocess,tempfile,hashlib,json
REPO=Path(__file__).resolve().parents[2]
PATCH=REPO/'port/rpcs3-latest-patches/0073-PS5-opt-in-cap-live-SPU-LLVM-compile-workers.patch'
SRC='rpcs3/Emu/Cell/SPUCommonRecompiler.cpp'
HEAD='rpcs3/Emu/Cell/ps5_spu_live_compile_workers.h'
def run(*args,cwd=None):
 p=subprocess.run(args,cwd=cwd,text=True,capture_output=True,timeout=50)
 if p.returncode:raise AssertionError(f'{args} -> {p.returncode}\n{p.stderr}\n{p.stdout}')
 return p.stdout
def main():
 import argparse
 parser=argparse.ArgumentParser()
 parser.add_argument('--source',type=Path,default=Path.home()/'work/rpcs3-latest')
 parser.add_argument('--original',type=Path,default=Path.home()/'work/cpu-plan-jit-workers0073-original-20261031')
 a=parser.parse_args()
 m=json.loads((a.original/'manifest.json').read_text())
 assert m['patch']==73
 data={p:(a.source/p).read_bytes() for p in (SRC,HEAD)}
 assert all(hashlib.sha256(value).hexdigest()==m['after'][key] for key,value in data.items())
 assert PATCH.read_text().count('diff --git ')==2
 source=data[SRC].decode()
 assert source.count('ps5_spu_live_workers::limit(worker_count)')==1
 assert source.index('ps5_spu_live_workers::limit(worker_count)')>source.index('struct spu_llvm_worker')
 assert source.index('ps5_spu_live_workers::limit(worker_count)')>source.index('struct spu_llvm', source.index('struct spu_llvm_worker') + 20)
 assert source.index('ps5_spu_live_workers::limit(worker_count)')>source.index('named_thread_group workers("SPU Worker "')
 assert source.index('ps5_spu_live_workers::limit(worker_count)')<source.index('make_single<named_thread_group<spu_llvm_worker>>("SPUW."')
 assert '#define PS5_SPU_LIVE_JIT_WORKER_CAP 0' in data[HEAD].decode()
 with tempfile.TemporaryDirectory(prefix='jit-worker0073-') as directory:
  tmp=Path(directory);run('git','init','-q',str(tmp))
  for name,value in data.items():
   p=tmp/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(value)
  run('git','apply','--reverse','--check',str(PATCH),cwd=tmp)
  run('git','apply','--reverse',str(PATCH),cwd=tmp)
  assert not (tmp/HEAD).exists()
  raw=(a.original/'SPUCommonRecompiler.cpp').read_bytes()
  assert (tmp/SRC).read_bytes()==raw
  assert hashlib.sha256(raw).hexdigest()==m['before'][SRC]
  run('git','apply','--check',str(PATCH),cwd=tmp)
  run('git','apply',str(PATCH),cwd=tmp)
  assert all((tmp/k).read_bytes()==v for k,v in data.items())
  cpp=tmp/'check.cpp'
  cpp.write_text(r"""
#include "rpcs3/Emu/Cell/ps5_spu_live_compile_workers.h"
#include <cassert>
unsigned normal(unsigned hc) {
  unsigned count=1;
  if(hc>=12)count=hc-12+3;
  else if(hc>=6)count=2;
  return count;
}
int main() {
  for(unsigned cpu: {1u,5u,6u,11u,12u,13u,16u,28u}) {
    unsigned n=normal(cpu);
    unsigned got=ps5_spu_live_workers::limit(n);
#if PS5_SPU_LIVE_JIT_WORKER_CAP
    assert(got==(n<PS5_SPU_LIVE_JIT_WORKER_CAP?n:PS5_SPU_LIVE_JIT_WORKER_CAP));
#else
    assert(got==n);
#endif
    assert(got>=1);
    if(cpu==13) assert(got==(PS5_SPU_LIVE_JIT_WORKER_CAP==0?4u:(PS5_SPU_LIVE_JIT_WORKER_CAP<4?PS5_SPU_LIVE_JIT_WORKER_CAP:4u)));
  }
  return 0;
}
""".replace('#include <cassert>','#include <cassert>\n#include <initializer_list>'))
  for cap in (0,1,2,4,32):
   target=tmp/f'cap{cap}'
   run('clang++-19','-std=c++20','-O2','-Wall','-Wextra','-Werror',
       f'-DPS5_SPU_LIVE_JIT_WORKER_CAP={cap}',
       '-I',str(a.source),str(cpp),'-o',str(target))
   run(str(target))
  invalid=run('clang++-19','--version')
  assert 'clang' in invalid.lower()
 print('PASS patch0073 exact replay, source isolation to SPUW, C++20 caps 0/1/2/4/32 including 13->4/2, nonzero floor')
if __name__=='__main__':main()
