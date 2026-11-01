#!/usr/bin/env python3
"""Host-only per-game PS5 emulator executable+code-mirror pairing plan.

Checks the ACTUAL paired native eboot.elf / signed eboot.bin / RPCS3 code
mirror against the PS5 ELF's execute segment, and identifies still-unproven
per-title dependencies. No packaging, installation, shell patches or FTP writes.

Source mirror header specified in app/ps5/tools/link-title.sh.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

MAGIC=b"RPCS3PS5TEXT"
TITLE_ID="PPSA88395"
PS5_SELF_MAGIC=bytes.fromhex("4f153d1d")
MAX_ELF=256*1024*1024
MAX_MIRROR=192*1024*1024

class PairError(ValueError):
    pass

def sha_file(path: Path, length: int | None = None, offset: int = 0) -> str:
    if offset < 0 or (length is not None and length < 0):
        raise PairError("Invalid byte range")
    h=hashlib.sha256()
    with path.open("rb") as src:
        src.seek(offset)
        remaining=length
        while remaining is None or remaining > 0:
            part=src.read(min(1<<20, remaining) if remaining is not None else 1<<20)
            if not part:
                break
            h.update(part)
            if remaining is not None:
                remaining-=len(part)
        if remaining is not None and remaining!=0:
            raise PairError("Short executable segment or mirror read")
    return h.hexdigest()

def checked_file(path: Path, low: int, high: int) -> int:
    if not path.is_file() or path.is_symlink():
        raise PairError(f"Required build input missing or a symbolic link: {path}")
    size=path.stat().st_size
    if not low <= size <= high:
        raise PairError(f"Unexpected size for {path.name}: {size}")
    return size

def elf_exec_segment(path: Path) -> dict:
    size=checked_file(path, 64, MAX_ELF)
    with path.open("rb") as f:
        header=f.read(64)
        if header[:6]!=b"\x7fELF\x02\x01":
            raise PairError("Not a little-endian ELF64")
        etype,machine=struct.unpack_from("<HH",header,16)
        # PS5 EBOOT image type is 0xFE10; small homebrew PRX probes use 0xFE18.
        if etype not in (0xfe10,0xfe18) or machine!=62:
            raise PairError("Not a converted PS5 native ELF")
        entry=struct.unpack_from("<Q",header,24)[0]
        phoff=struct.unpack_from("<Q",header,32)[0]
        phentsize,n=struct.unpack_from("<HH",header,54)
        if not (phentsize==56 and 1<=n<=128 and phoff+n*phentsize<=size):
            raise PairError("Invalid ELF program headers")
        f.seek(phoff)
        records=f.read(n*phentsize)
    executable=[]
    for i in range(n):
        t,flags,fileoff,vaddr,_,fsz,msz,align=struct.unpack_from("<IIQQQQQQ",records,i*56)
        if t==1 and flags&1:
            if not (0<fsz<=MAX_MIRROR and fsz<=msz and fileoff+fsz<=size):
                raise PairError("Invalid ELF executable LOAD segment")
            executable.append({
                "vaddr":vaddr, "file_offset":fileoff,
                "file_size":fsz, "mem_size":msz, "flags":flags,
                "content_sha256":sha_file(path,fsz,fileoff),
            })
    if len(executable)!=1:
        raise PairError("Expected exactly one executable PT_LOAD segment")
    if not executable[0]["vaddr"]<=entry<executable[0]["vaddr"]+executable[0]["mem_size"]:
        raise PairError("ELF entry point is not within executable segment")
    return {"entry":entry,**executable[0]}

def load_tls_signature(path: Path) -> tuple:
    """Identity of all executable/non-executable PT_LOAD and PT_TLS bytes."""
    size=checked_file(path,64,MAX_ELF)
    with path.open("rb") as f:
        h=f.read(64)
        if h[:6]!=b"\x7fELF\x02\x01" or struct.unpack_from("<H",h,18)[0]!=62:
            raise PairError("Signed SELF did not extract to an x86-64 ELF")
        entry=struct.unpack_from("<Q",h,24)[0]
        off=struct.unpack_from("<Q",h,32)[0]
        ent,count=struct.unpack_from("<HH",h,54)
        if ent!=56 or not 1<=count<=128 or off+ent*count>size:
            raise PairError("Invalid extracted ELF header")
        f.seek(off)
        ph=f.read(ent*count)
    segments=[]
    for i in range(count):
        typ,flags,p_off,vaddr,_,filesz,memsz,align=struct.unpack_from("<IIQQQQQQ",ph,i*ent)
        if typ in (1,7):
            if not (0<=filesz<=memsz and p_off+filesz<=size):
                raise PairError("Malformed extracted ELF load/TLS range")
            segments.append((typ,flags,vaddr,filesz,memsz,align,
                             sha_file(path,filesz,p_off)))
    if not segments:
        raise PairError("Signed SELF extracted with no LOAD/TLS segments")
    return (entry,tuple(segments))


def validate_pair(elf:Path,self_path:Path,mirror:Path,extracted_self:Path) -> dict:
    exec_segment=elf_exec_segment(elf)
    self_size=checked_file(self_path,1024,MAX_ELF)
    with self_path.open("rb") as f:
        if f.read(4)!=PS5_SELF_MAGIC:
            raise PairError("Expected a signed native PS5 SELF")
    if load_tls_signature(elf) != load_tls_signature(extracted_self):
        raise PairError("Signed SELF extraction LOAD/TLS differs from paired ELF")
    sz=checked_file(mirror,29,MAX_MIRROR)
    with mirror.open("rb") as f:
        head=f.read(28)
    if head[:12]!=MAGIC:
        raise PairError("Invalid RPCS3 native text-mirror magic")
    vaddr,file_size=struct.unpack_from("<QQ",head,12)
    if vaddr!=exec_segment["vaddr"] or file_size!=exec_segment["file_size"]:
        raise PairError("Mirror vaddr or size does not match ELF executable PT_LOAD")
    if sz!=28+file_size:
        raise PairError("Mirror has missing or extra executable bytes")
    mirror_hash=sha_file(mirror,file_size,28)
    if mirror_hash!=exec_segment["content_sha256"]:
        raise PairError("Mirror executable bytes differ from paired ELF")
    return {
        "elf": {"size_bytes":elf.stat().st_size,"sha256":sha_file(elf),
                "entry":exec_segment["entry"]},
        "signed_self":{"size_bytes":self_size,"sha256":sha_file(self_path)},
        "code_mirror":{"size_bytes":sz,"sha256":sha_file(mirror),
                       "exec_segment_sha256":mirror_hash,
                       "exec_vaddr":vaddr,"exec_size":file_size},
        "signed_self_extraction":{"size_bytes":extracted_self.stat().st_size,
                                  "sha256":sha_file(extracted_self)},
        "pair_signed_self_extraction_matches_all_elf_load_tls":True,
        "pair_mirror_matches_elf_executable_segment":True,
    }

def validate_plan(plan:dict, title:str) -> dict:
    if (title!=TITLE_ID or
            plan.get("schema")!="kb-rpcs3-safe-native-trophy-plan/v1" or
            plan.get("registration_mode")!="DISABLED_OFFLINE_PLANNING_ONLY" or
            plan.get("console_firmware")!="13.20" or
            plan.get("writes_console") is not False or
            plan.get("creates_npbind") is not False):
        raise PairError("Unexpected or registration-enabled native owner plan")
    matches=[g for g in plan.get("games",[]) if g.get("ps5_title_id")==title]
    if (len(matches)!=1 or
            matches[0].get("ps3_serial")!="NPUB30702" or
            matches[0].get("npwr")!="NPWR00132_00" or
            matches[0].get("registration_allowed") is not False or
            matches[0].get("ps5_title_status")!="PLAN_ONLY_NOT_INSTALLED"):
        raise PairError("Owner title identity is not the verified GTA IV offline plan")
    return matches[0]

def build_report(plan:dict,title:str,elf:Path,self_path:Path,mirror:Path,
                 extracted_self:Path) -> dict:
    game=validate_plan(plan,title)
    pair=validate_pair(elf,self_path,mirror,extracted_self)
    return {
        "schema":"kb-rpcs3-ps5-emulator-owner-preflight/v1",
        "status":"HOST_ONLY_PAIR_VERIFIED_NOT_DEPLOYABLE",
        "target_firmware":"13.20",
        "proposed_title":title,
        "ps3_serial":game["ps3_serial"],
        "ps3_trophies":game["npwr"],
        "source_build_paths":[str(elf),str(self_path),str(mirror),str(extracted_self)],
        "verified_paired_binaries":pair,
        "data_root_candidate":"/data/homebrew/PPSA99303/rpcs3",
        "data_root_access_from_target_app_sandbox":"UNTESTED",
        "app0_data_root_mapping":"MISSING_AND_NOT_CONFIGURED",
        "required_local_files_not_packaged":[
            "/app0/rpcs3ps5-io.elf",
            "/app0/sce_module/libc.prx",
        ],
        "fixed_helper_target":"/data/homebrew/PPSA99303/rpcs3",
        "native_trophy_binding_validated":False,
        "firmware_13_20_trophy_registration_validated":False,
        "ps5_files_changed":False,
        "emulator_per_game_title_ready":False,
        "native_trophy_menu_ready":False,
        "install_allowed":False,
        "next_action":"RUN_SEPARATELY_APPROVED_READ_ONLY_TITLE_SANDBOX_ACCESS_PROBE",
    }

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--native-plan",required=True,type=Path)
    ap.add_argument("--title-id",default=TITLE_ID)
    ap.add_argument("--elf",required=True,type=Path)
    ap.add_argument("--self",required=True,type=Path)
    ap.add_argument("--mirror",required=True,type=Path)
    ap.add_argument("--extracted-self",required=True,type=Path,
                    help="Use pinned ps5-native-tool self --extract output for this SAME signed SELF")
    ap.add_argument("--report",required=True,type=Path)
    a=ap.parse_args()
    if a.report.exists():ap.error("Cannot overwrite existing report")
    try:
        plan=json.loads(a.native_plan.read_text(encoding="utf-8"))
        result=build_report(plan,a.title_id,a.elf,a.self,a.mirror,a.extracted_self)
        with a.report.open("x",encoding="utf-8") as out:
            json.dump(result,out,indent=2,ensure_ascii=False)
        print(json.dumps(result,indent=2))
    except (OSError,PairError,KeyError,TypeError,ValueError) as exc:
        ap.exit(1,"Host-only emulator owner preflight refused: "+str(exc)+"\n")
if __name__=="__main__":
    main()
