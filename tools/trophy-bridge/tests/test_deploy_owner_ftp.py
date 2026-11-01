"""Fake FTP regression tests for the single disposable PS5 owner-test installer."""
import importlib.util
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from ftplib import error_perm, error_reply

script=Path(__file__).resolve().parents[1]/"deploy_owner_test_ftp.py"
spec=importlib.util.spec_from_file_location("guarded_owner_ftp",script)
d=importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)

class FakeFTP:
    def __init__(self):
        self.folders={"/data/homebrew","/system_data/priv/appmeta","/user/app"}
        self.files={}
        self.ops=[]
        self.on_stor=None
    def cwd(self,path):
        self.ops.append(("CWD",path))
        if path not in self.folders:
            raise error_perm("550 No such file or directory")
    def retrlines(self, command, cb):
        self.ops.append(("LIST",command))
        return [
            cb(f"{'d' if child in self.folders else '-'}rwxrwxrwx 1 0 0 100 Nov 01 00:00 {child.rsplit('/',1)[-1]}")
            for child in sorted(self.folders | set(self.files))
            if child.rsplit("/",1)[0] == self.ops[-2][1]
        ]
    def mkd(self,path):
        self.ops.append(("MKD",path))
        if path in self.folders: raise error_perm("550 exists")
        self.folders.add(path)
    def storbinary(self,cmd,reader,blocksize=None):
        path=cmd.removeprefix("STOR ")
        self.ops.append(("STOR",path))
        if path in self.files: raise error_perm("550 exists")
        self.files[path]=reader.read()
        if self.on_stor:
            self.on_stor(path)
    def retrbinary(self,cmd,cb,blocksize=None):
        path=cmd.removeprefix("RETR ")
        self.ops.append(("RETR",path))
        cb(self.files[path])
    def sendcmd(self,cmd):
        if cmd.startswith("SITE CHMOD 777 "):
            self.ops.append(("CHMOD",cmd))
            return "200 OK"
        path=cmd.removeprefix("DELE ")
        self.ops.append(("DELE",path))
        self.files.pop(path)
        raise error_reply("226 File deleted")
    def rmd(self,path):
        self.ops.append(("RMD",path))
        self.folders.remove(path)


class OwnerDeployTests(unittest.TestCase):
    def setUp(self):
        self.files={k:(b"\x4f\x15\x3d\x1d"+bytes(1100) if k=="eboot.bin" else
                       json.dumps({"titleId": d.TITLE, "localizedParameters":{"en-US":{"titleName":"GTA IV OWNER TEST"}}}).encode()
                       if k=="sce_sys/param.json" else
                       b"synthetic content "+k.encode()) for k in d.ALLOWED}
        self.ftp=FakeFTP()

    def test_exact_six_files_param_json_written_last(self):
        result=d.install(self.ftp,self.files,b'',b'')
        self.assertTrue(result["all_files_verified"])
        sent=[p for op,p in self.ftp.ops if op=="STOR"]
        self.assertEqual(sent, [d.ROOT+"/"+f for f in d.ALLOWED])
        self.assertEqual(sent[-1], d.ROOT+"/sce_sys/param.json")
        self.assertEqual(len(result["file_checks"]),6)
        self.assertNotIn(d.APP_META, self.ftp.folders)

    def test_refuses_existing_ps5_appmeta(self):
        self.ftp.folders.add(d.APP_META)
        with self.assertRaises(d.DeployError):
            d.install(self.ftp,self.files,b'',b'')
        self.assertFalse(any(op=="STOR" for op,_ in self.ftp.ops))

    def test_cleanly_rolls_back_before_param(self):
        def fail(path):
            if path.endswith("sce_sys/icon0.png"):
                raise RuntimeError("synthetic connection failure")
        self.ftp.on_stor=fail
        with self.assertRaises(RuntimeError):
            d.install(self.ftp,self.files,b'',b'')
        self.assertNotIn(d.ROOT,self.ftp.folders)
        self.assertFalse(any(x.startswith(d.ROOT) for x in self.ftp.files))
        self.assertNotIn("sce_sys/param.json",self.ftp.files)

    def test_never_auto_deletes_after_param_upload(self):
        def fail(path):
            if path.endswith("sce_sys/param.json"):
                raise RuntimeError("synthetic connection loss immediately after registration trigger")
        self.ftp.on_stor=fail
        with self.assertRaises(RuntimeError):
            d.install(self.ftp,self.files,b'',b'')
        self.assertIn(d.ROOT,self.ftp.folders)
        self.assertIn(d.ROOT+"/sce_sys/param.json",self.ftp.files)

    def test_rejects_modified_decrypted_elf_segments(self):
        import struct
        def raw_elf(fill):
            b=bytearray(256)
            b[:6]=b"\x7fELF\x02\x01"
            struct.pack_into("<Q",b,24,288)
            struct.pack_into("<Q",b,32,64)
            struct.pack_into("<HH",b,54,56,1)
            struct.pack_into("<IIQQQQQQ",b,64,1,5,160,0,0,32,32,16)
            b[160:192]=bytes([fill])*32
            return bytes(b)
        good=raw_elf(3)
        bad=raw_elf(4)
        self.assertEqual(d.verify_self_readback(b"SELF",good,good),
                         "MATCHED_CONVERTED_ELF_LOAD_TLS_SEGMENTS")
        with self.assertRaisesRegex(d.DeployError,"differs"):
            d.verify_self_readback(b"SELF",bad,good)

    def test_cleanup_refuses_when_registered(self):
        self.ftp.folders.add(d.ROOT)
        self.ftp.folders.add(d.APP_META)
        with self.assertRaises(d.DeployError):
            d.cleanup_unregistered(self.ftp)

if __name__=="__main__":
    unittest.main()
