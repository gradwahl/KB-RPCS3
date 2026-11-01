#!/usr/bin/env python3
"""Remove ONLY the consented, disposable PPSA88395 owner-test SOURCE folder.

Does not remove system appmeta, registered application, any games, user accounts,
trophies or KB-RPCS3 title. Requires an independently complete stopped-process
listing and validates the exact test files + title identity before deletion.
After source removal, use PS5 Games Home -> owner test -> Options -> Delete
to unregister the now-unbacked title (no auto-reinstall).
"""
from __future__ import annotations
import argparse
import json
import re
import socket
from ftplib import FTP, error_perm, error_reply
from pathlib import Path

TITLE="PPSA88395"
ROOT="/data/homebrew/"+TITLE
FILES=(
    "sce_sys/param.json",
    "sce_sys/icon0.png",
    "sce_sys/pic0.png",
    "sce_module/libc.prx",
    "eboot.bin",
    "native-owner.txt",
)
DIRS=(ROOT+"/sce_module", ROOT+"/sce_sys", ROOT)
EXPECTED={
    ROOT: {"sce_sys","sce_module","eboot.bin","native-owner.txt"},
    ROOT+"/sce_sys": {"param.json","icon0.png","pic0.png"},
    ROOT+"/sce_module": {"libc.prx"},
}
PSLIST_MARKER="pskill: done, 0 process(es) named __list_only__* stopped"

class CleanupError(RuntimeError):
    pass

def list_children(ftp, path):
    ftp.cwd(path)
    rows=[]
    ftp.retrlines("LIST",rows.append)
    result={}
    for row in rows:
        cols=row.split(maxsplit=8)
        if len(cols)!=9:
            raise CleanupError("Unexpected FTP LIST record")
        mode,name=cols[0],cols[8]
        if name in (".",".."):continue
        if mode[0] not in ("-","d"):
            raise CleanupError("Unexpected symlink or file type in test title")
        result[name]="dir" if mode[0]=="d" else "file"
    return result

def check_source_shape(ftp):
    for folder,expect in EXPECTED.items():
        contents=list_children(ftp,folder)
        if set(contents)!=expect:
            raise CleanupError(f"Test title has unexpected source entries: {folder}: {set(contents)^expect}")
    for n in ("sce_sys","sce_module"):
        if list_children(ftp,ROOT)[n]!="dir":
            raise CleanupError("Wrong directory type in test title")
    for folder in (ROOT+"/sce_sys",ROOT+"/sce_module"):
        if any(kind!="file" for kind in list_children(ftp,folder).values()):
            raise CleanupError("Unexpected nested directory in test title")

def read_small(ftp,path,limit=4096):
    data=bytearray()
    def app(block):
        if len(data)+len(block)>limit:
            raise CleanupError("Test title marker unexpectedly large")
        data.extend(block)
    ftp.retrbinary("RETR "+path,app)
    return bytes(data)

def validate_identity(ftp):
    check_source_shape(ftp)
    marker=read_small(ftp,ROOT+"/native-owner.txt")
    if marker not in (b"PPSA88395 NPWR00132_00 NPUB30702\n",
                      b"PPSA88395 NPWR00132_00 NPUB30702\r\n"):
        raise CleanupError("Source test-title marker mismatch")
    obj=json.loads(read_small(ftp,ROOT+"/sce_sys/param.json").decode("utf-8"))
    if (obj.get("titleId")!=TITLE or
        obj.get("contentId")!="UP9000-PPSA88395_00-RPCS3OWNER000000" or
        "OWNER TEST (NOT TROPHIES)" not in
        obj.get("localizedParameters",{}).get("en-US",{}).get("titleName","")):
        raise CleanupError("Source contains an unexpected app identity")

def read_process_list(host,port,elf):
    raw=elf.read_bytes()
    if not 10000<len(raw)<200000 or b"pskill: done" not in raw:
        raise CleanupError("Not a known read-only process-list ELF")
    with socket.create_connection((host,port),timeout=9) as s:
        s.settimeout(10)
        s.sendall(raw)
        s.shutdown(socket.SHUT_WR)
        output=bytearray()
        while PSLIST_MARKER.encode() not in output:
            block=s.recv(4096)
            if not block: break
            output.extend(block)
            if len(output)>65536:
                raise CleanupError("Oversized process-list output")
    text=output.decode("utf-8","replace")
    if PSLIST_MARKER not in text or "pskill: KILL" in text:
        raise CleanupError("Incomplete or unsafe PS5 process listing")
    active=[row for row in text.splitlines()
            if re.search(r"pskill: pid \d+ ppid \d+ (eboot\.bin|rpcs3ps5-launch\.elf)$",row)]
    if active:
        raise CleanupError("Cannot remove test title while any native title or launcher runs: "+repr(active))
    return {"completed":True,"native_eboots_running":0,"launcher_running":0}

def delete_file(ftp,path):
    try:
        result=ftp.sendcmd("DELE "+path)
        if not result.startswith(("226","250")):
            raise CleanupError("Unexpected DELE response: "+result)
    except error_reply as exc:
        if not str(exc).startswith("226"):
            raise
    parent,name=path.rsplit("/",1)
    if name in list_children(ftp,parent):
        raise CleanupError("FTP deletion not verified: "+path)

def remove_source(ftp):
    validate_identity(ftp)
    removed=[]
    for name in FILES:
        delete_file(ftp,ROOT+"/"+name)
        removed.append(name)
    for directory in DIRS:
        if list_children(ftp,directory):
            raise CleanupError("Non-empty folder (refusing recursive delete): "+directory)
        ftp.rmd(directory)
    try:
        ftp.cwd(ROOT)
    except error_perm as e:
        if not str(e).startswith("550"):raise
    else:
        raise CleanupError("Test source directory still present after cleanup")
    return removed

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host",required=True)
    p.add_argument("--port",type=int,default=2121)
    p.add_argument("--loader-port",type=int,default=9021)
    p.add_argument("--pslist-elf",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    args=p.parse_args()
    if args.report.exists():p.error("report exists; no overwrites")
    try:
        # Independently check processes before and immediately preceding removal.
        first=read_process_list(args.host,args.loader_port,args.pslist_elf)
        with FTP() as ftp:
            ftp.connect(args.host,args.port,timeout=12);ftp.login()
            validate_identity(ftp)
            second=read_process_list(args.host,args.loader_port,args.pslist_elf)
            deleted=remove_source(ftp)
        record={
            "title":TITLE,"action":"TEST_SOURCE_ONLY_DELETED","files_deleted":deleted,
            "ps5_ui_unregistration_required":True,
            "system_appmeta_touched":False,"user_trophies_touched":False,
            "emulator_files_touched":False,
            "process_list_before":first,"process_list_immediately_before":second
        }
        args.report.write_text(json.dumps(record,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(record,indent=2))
    except (CleanupError,OSError,ValueError,error_perm,error_reply) as exc:
        p.exit(1,"OWNER TEST SOURCE CLEANUP STOPPED: "+str(exc)+"\n")
if __name__=="__main__":
    main()
