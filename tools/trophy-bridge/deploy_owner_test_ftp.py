#!/usr/bin/env python3
"""Guarded single TITLE-LIFETIME PROBE deployment (no PS5 trophy files).

This tool installs ONLY the specific new PPSA88395 OWNER TEST folder from
the previously staged local data, with param.json written LAST for
ShadowMountPlus. It requires the destination to be entirely absent from
homebrew and appmeta. No existing files are overwritten.

It performs independent FTP readback/SHA256 of each staged file BEFORE
param.json activation. It never writes to /user/trophy2, /system_data,
PPSA99303 or other installed titles.

The only removal method intentionally implemented is safe *pre-activation*
cleanup. Post-install app removal must use the PS5 Games Home Options->Delete
on the exact OWNER TEST app, then manually verify target appmeta is gone
before cleaning up the now-unregistered dedicated folder.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from ftplib import FTP, error_perm, error_reply
from io import BytesIO
from pathlib import Path

TITLE = "PPSA88395"
ROOT = "/data/homebrew/" + TITLE
APP_META = "/system_data/priv/appmeta/" + TITLE
USER_APP = "/user/app/" + TITLE
ALLOWED = (
    "eboot.bin",
    "native-owner.txt",
    "sce_module/libc.prx",
    "sce_sys/icon0.png",
    "sce_sys/pic0.png",
    "sce_sys/param.json",
)
FOLDERS = (ROOT, ROOT + "/sce_sys", ROOT + "/sce_module")
MAX_BYTES = 10 * 1024 * 1024

class DeployError(RuntimeError):
    pass

def absent(f: FTP, path: str) -> bool:
    try:
        f.cwd(path)
        return False
    except error_perm as exc:
        if str(exc).startswith("550"):
            return True
        raise

def listing(f: FTP, path: str) -> list[str]:
    f.cwd(path)
    lines = []
    f.retrlines("LIST", lines.append)
    return sorted(line.split(maxsplit=8)[-1] for line in lines
                  if len(line.split(maxsplit=8)) == 9 and line.split(maxsplit=8)[-1] not in (".", ".."))

def delete_file(f: FTP, path: str) -> None:
    try:
        result = f.sendcmd("DELE " + path)
        if not result.startswith(("226", "250")):
            raise DeployError(f"Unrecognized FTP DELE success: {result}")
    except error_reply as exc:
        if not str(exc).startswith("226"):
            raise
    # Check parent no longer lists the filename regardless of FTP status-code quirks.
    parent, name = path.rsplit("/", 1)
    if name in listing(f, parent):
        raise DeployError(f"File deletion not confirmed: {path}")

def cleanup_unregistered(f: FTP) -> None:
    if not absent(f, APP_META):
        raise DeployError("Cannot clean folder while system appmeta exists; delete owner test via PS5 UI first")
    if absent(f, ROOT):
        return
    for file in reversed(ALLOWED):
        path = ROOT + "/" + file
        parent, name = path.rsplit("/", 1)
        try:
            if name in listing(f, parent):
                delete_file(f, path)
        except error_perm as exc:
            if not str(exc).startswith("550"):
                raise
    for folder in reversed(FOLDERS):
        if not absent(f, folder):
            extras = listing(f, folder)
            if extras:
                raise DeployError(f"Refusing to delete unexpected files in test folder: {folder}: {extras}")
            f.rmd(folder)
    if not absent(f, ROOT):
        raise DeployError("Dedicated test title folder persisted after cleanup")

def validate_host(stage: Path) -> dict[str, bytes]:
    meta = json.loads((stage.parent / "STAGE-ONLY-NO-INSTALL.json").read_text(encoding="utf-8"))
    if meta.get("status") != "HOST_ONLY_UNDEPLOYED_NO_TROPHY_REGISTRATION" or meta.get("firmware") != "13.20":
        raise DeployError("Unsafe stage manifest")
    games = [x for x in meta.get("apps", []) if x.get("title_id") == TITLE]
    if len(games) != 1 or games[0].get("ps3_serial") != "NPUB30702" or games[0].get("npwr") != "NPWR00132_00":
        raise DeployError("Stage game identity mismatch")
    if games[0].get("contains_trophy_assets") is not False or games[0].get("has_game_emulator") is not False:
        raise DeployError("Stage contains more than a title-lifetime test")
    hashes = games[0].get("file_sha256", {})
    if set(hashes) != set(ALLOWED):
        raise DeployError("Unexpected stage file inventory")
    actual = {p.relative_to(stage).as_posix() for p in stage.rglob("*") if p.is_file()}
    if actual != set(ALLOWED):
        raise DeployError("Unexpected stage path")
    output = {}
    for name in ALLOWED:
        data = (stage / name).read_bytes()
        if len(data) == 0 or len(data) > MAX_BYTES:
            raise DeployError(f"Unexpected stage file size: {name}")
        if hashlib.sha256(data).hexdigest() != hashes[name]:
            raise DeployError(f"Stage hash mismatch: {name}")
        output[name] = data
    param = json.loads(output["sce_sys/param.json"])
    if param.get("titleId") != TITLE or "OWNER TEST" not in param["localizedParameters"]["en-US"]["titleName"]:
        raise DeployError("Not an explicitly labeled owner-test title")
    if not output["eboot.bin"].startswith(bytes.fromhex("4f153d1d")):
        raise DeployError("Not a PS5 signed title SELF")
    return output

def elf_load_tls_segments(raw: bytes) -> tuple[int, list[tuple]]:
    """Verify exact loaded program identity despite PS5 SELF->ELF FTP readback."""
    import struct
    if len(raw) < 64 or raw[:4] != b"\x7fELF" or raw[4:6] != b"\x02\x01":
        raise DeployError("Expected PS5 decrypted little-endian ELF")
    entry = struct.unpack_from("<Q", raw, 24)[0]
    phoff = struct.unpack_from("<Q", raw, 32)[0]
    entsize, count = struct.unpack_from("<HH", raw, 54)
    if entsize != 56 or not 1 <= count <= 128 or phoff+count*entsize > len(raw):
        raise DeployError("Invalid PS5 ELF program-header table")
    segments = []
    for i in range(count):
        typ, flags, off, addr, _, filelen, memlen, alignment = struct.unpack_from(
            "<IIQQQQQQ", raw, phoff + i * entsize)
        if typ in (1, 7):
            if off+filelen > len(raw):
                raise DeployError("Out-of-bounds ELF load/TLS segment")
            segments.append((typ, flags, addr, filelen, memlen, alignment,
                             hashlib.sha256(raw[off:off+filelen]).hexdigest()))
    if not segments or not any(item[0] == 1 for item in segments):
        raise DeployError("Missing ELF executable load segments")
    return entry, segments


def verify_self_readback(source_self: bytes, readback: bytes,
                         converted: bytes) -> str:
    """A signed SELF can be returned as an ELF by the PS5 FTP server."""
    if hashlib.sha256(source_self).digest() == hashlib.sha256(readback).digest():
        return "SHA256_IDENTICAL_SIGNED_SELF"
    if not readback.startswith(b"\x7fELF"):
        raise DeployError("Non-ELF altered uploaded eboot.bin")
    if elf_load_tls_segments(readback) != elf_load_tls_segments(converted):
        raise DeployError("Decrypted ELF load/TLS or entry point differs from signed build")
    return "MATCHED_CONVERTED_ELF_LOAD_TLS_SEGMENTS"


def precheck(f: FTP) -> None:
    for place in (ROOT, APP_META, USER_APP):
        if not absent(f, place):
            raise DeployError("Title already exists, refusing overwrite: " + place)

def install(f: FTP, staged: dict[str, bytes], converted: bytes,
            converted_libc: bytes) -> dict:
    precheck(f)
    made = False
    installed = False
    try:
        for folder in FOLDERS:
            f.mkd(folder)
        made = True
        report = []
        # param.json last, following the existing ShadowMountPlus tile path.
        for name in ALLOWED:
            content = staged[name]
            path = ROOT + "/" + name
            if name == "sce_sys/param.json":
                installed = True  # STOR can succeed then raise on an unexpected server reply.
            f.storbinary("STOR " + path, BytesIO(content), blocksize=8192)
            if name in ("eboot.bin", "sce_module/libc.prx"):
                chmod = f.sendcmd("SITE CHMOD 777 " + path)
                if not chmod.startswith("200"):
                    raise DeployError("Executable permissions not confirmed: "+name)
            readback = bytearray()
            def capture(block):
                if len(readback)+len(block)>MAX_BYTES:
                    raise DeployError("Readback too large")
                readback.extend(block)
            f.retrbinary("RETR " + path, capture, blocksize=8192)
            expected = hashlib.sha256(content).hexdigest()
            mode = "SHA256_EXACT"
            if name == "eboot.bin":
                mode = verify_self_readback(content, readback, converted)
            elif name == "sce_module/libc.prx":
                mode = verify_self_readback(content, readback, converted_libc)
            elif hashlib.sha256(readback).hexdigest() != expected:
                raise DeployError("Live upload hash mismatch: "+name)
            report.append({"file": name, "bytes": len(content), "sha256": expected,
                           "readback_verification": mode})
        return {"title": TITLE, "mode": "EXPLICIT_USER_APPROVED_DISPOSABLE_TITLE_TEST",
                "console_path": ROOT, "param_json_written_last": True,
                "all_files_verified": True, "file_checks": report,
                "trophy_registration_attempted": False}
    except BaseException:
        # Pre-activation only: safe, no registered PS5 title was triggered.
        if made and not installed and absent(f, APP_META):
            try:
                cleanup_unregistered(f)
                print("PRE_ACTIVATION_ROLLBACK_SUCCEEDED", flush=True)
            except Exception as exc:
                print("PRE_ACTIVATION_ROLLBACK_FAILED",str(exc),flush=True)
        raise

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host",required=True)
    p.add_argument("--port",type=int,default=2121)
    p.add_argument("--stage",type=Path,required=True)
    p.add_argument("--converted-elf",type=Path,required=True,
                   help="Unencrypted converted eboot.elf from SAME signed owner build")
    p.add_argument("--converted-libc",type=Path,required=True,
                   help="Locally extracted libc.prx ELF from SAME signed runtime library")
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args()
    if a.report.exists():
        p.error("Report already exists")
    try:
        files=validate_host(a.stage)
        converted=a.converted_elf.read_bytes()
        if (len(converted) > MAX_BYTES or len(converted) < 1000 or
                hashlib.sha256(converted).hexdigest() != "9e97292522e025f8b02f24754b9a1b0937c25a5b3f39154f7f3e9e4e09560af8"):
            raise DeployError("Converted owner-test ELF build identity mismatch")
        elf_load_tls_segments(converted)
        converted_libc=a.converted_libc.read_bytes()
        if (len(converted_libc)>MAX_BYTES or
            hashlib.sha256(converted_libc).hexdigest() != "8ee6e124993e1af26420cb455890fd002f5d6c7e78883c860ce45734e7d002bb"):
            raise DeployError("Converted libc ELF build identity mismatch")
        elf_load_tls_segments(converted_libc)
        with FTP() as ftp:
            ftp.connect(a.host,a.port,timeout=15);ftp.login()
            out=install(ftp,files,converted,converted_libc)
        with a.report.open("x",encoding="utf-8") as dest:
            json.dump(out,dest,indent=2)
        print(json.dumps(out,indent=2))
    except (DeployError,OSError,ValueError,error_perm,error_reply) as exc:
        p.exit(1,"Owner test install: "+str(exc)+"\n")

if __name__=="__main__":
    main()
