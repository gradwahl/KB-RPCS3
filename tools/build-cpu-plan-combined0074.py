#!/usr/bin/env python3
"""Build explicit combined CPU-plan experiment; restore original source gates afterward."""
from pathlib import Path
import hashlib, json, os, shutil, subprocess
REPO=Path(__file__).resolve().parents[1]
SRC=Path.home()/"work/rpcs3-latest"
ARCH=Path.home()/"work/cpu-plan-combined0074-all-on-20261031"
GATES={
 "rpcs3/ps5/ps5_release_profile.h":("PS5_RELEASE_PROFILE_ACTIVE",1),
 "rpcs3/ps5/ps5_spu_hotjit.h":("PS5_SPU_HOTJIT_ACTIVE",1),
 "rpcs3/ps5/ps5_cpu_topology.h":("PS5_CPU_TOPOLOGY_PROBE",1),
 "rpcs3/Emu/Cell/ps5_spu_live_compile_workers.h":("PS5_SPU_LIVE_JIT_WORKER_CAP",2),
 "rpcs3/Emu/RSX/VK/vkutils/ps5_vk_fence_sleep.h":("PS5_VK_FENCE_TIMED_WAIT",1),
}
def main():
 ARCH.mkdir(exist_ok=True)
 assert not (ARCH/"manifest.json").exists() and not (ARCH/"source-gates").exists(), "Existing build archive"
 originals={f:(SRC/f).read_bytes() for f in GATES}
 for test in ("check-ps5-vk-fence-wait.py","check-ps5-jit-workers0073.py","check-ps5-cpu-topology-parser.py","check-ps5-release-profile0074.py","check-ps5-spu-hotjit-parser.py"):
  subprocess.run(["python3",str(REPO/"port/tests"/test)],check=True)
 try:
  for f,(key,value) in GATES.items():
   before=originals[f]; needle=f"#define {key} 0".encode(); assert before.count(needle)==1,f
   after=before.replace(needle,f"#define {key} {value}".encode())
   (SRC/f).write_bytes(after)
   dst=ARCH/"source-gates"/f; dst.parent.mkdir(parents=True,exist_ok=True); dst.write_bytes(after)
  env=dict(os.environ,JOBS="2")
  subprocess.run(["bash",str(REPO/"tools/wsl-build-latest.sh")],env=env,check=True)
  app=Path.home()/"work/ps5-rpcs3-app-latest"
  for name in ("eboot.bin","rpcs3ps5-text.bin"):
   shutil.copy2(app/"dist/PPSA99303"/name,ARCH/name)
  shutil.copy2(app/"build/ps5/eboot.elf",ARCH/"eboot.elf")
  files={n:{"sha256":hashlib.sha256((ARCH/n).read_bytes()).hexdigest(),"bytes":(ARCH/n).stat().st_size} for n in ("eboot.bin","eboot.elf","rpcs3ps5-text.bin")}
  (ARCH/"manifest.json").write_text(json.dumps({"patch_count":74,"gates":{k:v for k,v in GATES.values()},"runtime_required":{"spu_insert_select":1},"files":files,"gameplay":"UNTESTED"},indent=2))
  print("PASS combined experiment archived",ARCH,flush=True)
 finally:
  for f,data in originals.items():
   # Only restore our exact gate edit, preserving unrelated concurrent work.
   current=(SRC/f).read_bytes(); key,value=GATES[f]
   expected=data.replace(f"#define {key} 0".encode(),f"#define {key} {value}".encode())
   if current==expected: (SRC/f).write_bytes(data)
   else: raise RuntimeError(f"Concurrent source modification; inspect {f}")
  print("Original default-OFF source headers restored; build output is explicit experimental image",flush=True)
if __name__=="__main__": main()
