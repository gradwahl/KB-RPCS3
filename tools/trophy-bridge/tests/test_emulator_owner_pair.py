"""Host-only native emulator pair/mirror + owner access-probe staging checks."""
import copy
import hashlib
import importlib.util
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location("paired",ROOT/"plan_emulator_owner_pair.py")
p=importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
spec2=importlib.util.spec_from_file_location("stage",ROOT/"stage_native_owner_probes.py")
s=importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(s)


PLAN={
 "schema":"kb-rpcs3-safe-native-trophy-plan/v1",
 "registration_mode":"DISABLED_OFFLINE_PLANNING_ONLY",
 "console_firmware":"13.20",
 "writes_console":False,
 "creates_npbind":False,
 "games":[
  {"ps5_title_id":"PPSA88395","ps3_serial":"NPUB30702","npwr":"NPWR00132_00",
   "ps3_game":"GTA IV","registration_allowed":False,
   "ps5_title_status":"PLAN_ONLY_NOT_INSTALLED","ps5_trophy_menu_ready":False,
   "identity_evidence":"installed_PS3_TROPDIR"},
  {"ps5_title_id":"PPSA85381","ps3_serial":"BLES01739","npwr":"NPWR03806_00",
   "ps3_game":"Dead Island Riptide","registration_allowed":False,
   "ps5_title_status":"PLAN_ONLY_NOT_INSTALLED","ps5_trophy_menu_ready":False,
   "identity_evidence":"verified_ISO_PS3_GAME_PARAM_SFO_and_TROPDIR"},
 ],
 "used_ps5_title_ids_seen":[],
}

class PairTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name)
  self.elf=self.root/"eboot.elf"
  self.self=self.root/"eboot.bin"
  self.mirror=self.root/"rpcs3ps5-text.bin"
  self.content=b"\xcc\x90"*64
  data=bytearray(512)
  data[:6]=b"\x7fELF\x02\x01"
  struct.pack_into("<HH",data,16,0xfe10,62)
  struct.pack_into("<Q",data,24,8)
  struct.pack_into("<Q",data,32,64)
  struct.pack_into("<HH",data,54,56,1)
  struct.pack_into("<IIQQQQQQ",data,64,1,5,256,0,0,len(self.content),len(self.content),0x4000)
  data[256:256+len(self.content)]=self.content
  self.elf.write_bytes(data)
  self.self.write_bytes(p.PS5_SELF_MAGIC+bytes(2048))
  self.mirror.write_bytes(p.MAGIC+struct.pack("<QQ",0,len(self.content))+self.content)

 def test_elf_and_mirror_paired(self):
  result=p.build_report(PLAN,"PPSA88395",self.elf,self.self,self.mirror,self.elf)
  self.assertTrue(result["verified_paired_binaries"]["pair_mirror_matches_elf_executable_segment"])
  self.assertFalse(result["install_allowed"])
  self.assertFalse(result["emulator_per_game_title_ready"])
  self.assertEqual(result["data_root_access_from_target_app_sandbox"],"UNTESTED")


 def test_extracted_signed_self_mismatched_load_segment_refused(self):
  alt=self.root/"unrelated-extracted.elf"
  buf=bytearray(self.elf.read_bytes())
  buf[280]^=1
  alt.write_bytes(buf)
  with self.assertRaisesRegex(p.PairError,"Signed SELF extraction"):
   p.validate_pair(self.elf,self.self,self.mirror,alt)

 def test_mirror_byte_corruption_refused(self):
  data=bytearray(self.mirror.read_bytes())
  data[-1]^=1
  self.mirror.write_bytes(data)
  with self.assertRaisesRegex(p.PairError,"differ"):
   p.validate_pair(self.elf,self.self,self.mirror,self.elf)

 def test_bad_mirror_header_or_length_refused(self):
  self.mirror.write_bytes(b"BADMAGIC----"+self.mirror.read_bytes()[12:])
  with self.assertRaisesRegex(p.PairError,"magic"):
   p.validate_pair(self.elf,self.self,self.mirror,self.elf)
  self.mirror.write_bytes(p.MAGIC+struct.pack("<QQ",0,len(self.content)+1)+self.content)
  with self.assertRaisesRegex(p.PairError,"size"):
   p.validate_pair(self.elf,self.self,self.mirror,self.elf)

 def test_wrong_elf_type_refused(self):
  raw=bytearray(self.elf.read_bytes())
  struct.pack_into("<H",raw,16,3)
  self.elf.write_bytes(raw)
  with self.assertRaisesRegex(p.PairError,"PS5"):
   p.validate_pair(self.elf,self.self,self.mirror,self.elf)

 def test_invalid_registration_enabled_plan_refused(self):
  bad=copy.deepcopy(PLAN)
  bad["registration_mode"]="ENABLED"
  with self.assertRaisesRegex(p.PairError,"registration"):
   p.validate_plan(bad,"PPSA88395")
  bad=copy.deepcopy(PLAN)
  bad["games"][0]["registration_allowed"]=True
  with self.assertRaises(p.PairError):
   p.validate_plan(bad,"PPSA88395")

 def test_other_game_rejected_for_single_gta_probe(self):
  with self.assertRaises(p.PairError):
   p.validate_plan(PLAN,"PPSA85381")

 def test_stage_only_shared_root_title_no_emulator(self):
  app=self.root/"app"
  (app/"sce_module").mkdir(parents=True)
  (app/"eboot.bin").write_bytes(p.PS5_SELF_MAGIC+bytes(2048))
  (app/"sce_module"/"libc.prx").write_bytes(bytes(2048))
  output=self.root/"out"
  result=s.stage(PLAN,app,output,"PPSA88395","shared_root")
  self.assertEqual(len(result["apps"]),1)
  self.assertEqual(result["probe_purpose"],"shared_root")
  self.assertFalse(result["registration_allowed"])
  self.assertEqual(result["apps"][0]["source"],"SIGNED_SHARED_ROOT_READ_ONLY_PROBE_NO_RPCS3")
  self.assertFalse((output/"PPSA85381").exists())
  self.assertFalse((output/"PPSA88395"/"rpcs3").exists())

 def test_staging_rejects_unknown_title(self):
  app=self.root/"app"
  with self.assertRaises(s.StageError):
   s.stage(PLAN,app,self.root/"out","PPSA89999","shared_root")


if __name__=="__main__":
 unittest.main()
