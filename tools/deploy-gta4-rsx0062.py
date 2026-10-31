#!/usr/bin/env python3
"""Safely stage, activate, or roll back the paired PS5 RPCS3 SPU-coverage diagnostic patch-0062 files.

Run from WSL with --dist pointing at the verified matching title dist folder.
Only two title-root files are touched. Does not delete user configs/game data.
A successful transfer is not proof of correct gameplay or FPS.
"""
import argparse
import ftplib
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = "/data/homebrew/PPSA99303/"
FILES = ("eboot.bin", "rpcs3ps5-text.bin")
NEW = ".rsx0062-stage"
OLD = ".before-rsx0062-20261030"
EXPECTED = {
    "eboot.bin": "d293d74636aa6e7cf19876d086a8ca98cf666999c8010771ded7cff7f3691644",
    "rpcs3ps5-text.bin": "5430f413e0574d082fa71add8e6b40dcf2a1a6bf714212f77469e5883d8a0d60",
}
PSLIST = Path(__file__).resolve().parent / "pskill" / "pslist.elf"


def check_closed(host):
    command = ["nc", "-w", "4", host, "9021"]
    proc = subprocess.run(command, input=PSLIST.read_bytes(), stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=14, check=True)
    listing = proc.stdout.decode("utf-8", errors="replace")
    if "pskill: done" not in listing:
        raise RuntimeError("Incomplete PS5 process listing; refusing to touch executable")
    offenders = [line for line in listing.splitlines()
                 if re.search(r"pskill: pid .* (?:eboot.bin|rpcs3ps5-launch.elf)$", line)]
    if offenders:
        raise RuntimeError("Title or launcher still running: " + ", ".join(offenders))
    print("OK: console process list has no eboot.bin or launcher", flush=True)


def hash_file(path):
    hash = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            hash.update(block)
    return hash.hexdigest()


def size(ftp, name):
    return ftp.size(ROOT + name)


def rename(ftp, before, after):
    ftp.rename(ROOT + before, ROOT + after)


def upload(ftp, src, remote):
    sent = 0
    def callback(buf):
        nonlocal sent
        sent += len(buf)
        if sent // (16 << 20) > (sent - len(buf)) // (16 << 20):
            print(f"  {src.name}: uploaded {sent >> 20} MiB", flush=True)
    with src.open("rb") as f:
        ftp.storbinary("STOR " + ROOT + remote, f, blocksize=256 * 1024,
                       callback=callback)
    ftp.sendcmd("SITE CHMOD 777 " + ROOT + remote)
    print(f"Staged {remote}: {sent:,} source bytes", flush=True)


def receive(ftp, remote, dst):
    with dst.open("wb") as f:
        ftp.retrbinary("RETR " + ROOT + remote, f.write, blocksize=256 * 1024)


def verify_elf(remote_path, local_elf):
    # FTPSRV's open() can expose a decrypted ELF even when the original was
    # uploaded as a signed SELF. Match actual load and TLS bytes, not SELF size.
    from elftools.elf.elffile import ELFFile
    with remote_path.open("rb") as rf, local_elf.open("rb") as lf:
        remote, local = ELFFile(rf), ELFFile(lf)
        if remote.header["e_entry"] != local.header["e_entry"]:
            raise RuntimeError("Downloaded ELF entry point differs from converted build")
        a = [p for p in remote.iter_segments() if p["p_type"] in ("PT_LOAD", "PT_TLS")]
        b = [p for p in local.iter_segments() if p["p_type"] in ("PT_LOAD", "PT_TLS")]
        if len(a) != len(b):
            raise RuntimeError(f"Downloaded ELF segment count {len(a)} vs {len(b)}")
        for i, (one, two) in enumerate(zip(a, b)):
            for key in ("p_type", "p_vaddr", "p_filesz", "p_memsz", "p_flags"):
                if one[key] != two[key]:
                    raise RuntimeError(f"Downloaded ELF segment {i} {key} mismatch")
            if one.data() != two.data():
                raise RuntimeError(f"Downloaded ELF segment {i} data mismatch")
    print("OK: downloaded decrypted ELF's load/TLS segments match converted build", flush=True)


def verify_download(ftp, remote, local_path, tmp_path, converted):
    receive(ftp, remote, tmp_path)
    actual = hash_file(tmp_path)
    expected = hash_file(local_path)
    if actual == expected:
        print(f"OK: {remote} exact SHA-256 verified ({actual})", flush=True)
        return
    if local_path.name == "eboot.bin" and tmp_path.open("rb").read(4) == b"\x7fELF":
        verify_elf(tmp_path, converted)
        return
    raise RuntimeError(f"{remote} differs from staged source: {actual} != {expected}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "activate", "rollback", "status"))
    parser.add_argument("--host", default="192.168.0.137")
    parser.add_argument("--port", default=2121, type=int)
    parser.add_argument("--dist", type=Path, default=Path("/home/callum/work/ps5-rpcs3-app-latest/dist/PPSA99303"))
    parser.add_argument("--converted", type=Path, default=Path("/home/callum/work/ps5-rpcs3-app-latest/build/ps5/eboot.elf"))
    parser.add_argument("--session", type=Path, default=Path("/home/callum/work/rsx0062-deploy-20261030"))
    args = parser.parse_args()

    if args.action != "status":
        check_closed(args.host)
    if args.action in ("stage", "activate"):
        for name in FILES:
            file = args.dist / name
            if hash_file(file) != EXPECTED[name]:
                raise RuntimeError(f"Source hash mismatch: {file}")
        if not args.converted.is_file():
            raise RuntimeError("Missing linked ELF for decrypted-SELF comparison")

    args.session.mkdir(parents=True, exist_ok=True)
    with ftplib.FTP(timeout=60) as ftp:
        ftp.connect(args.host, args.port)
        ftp.login()
        ftp.voidcmd("TYPE I")
        if args.action == "status":
            print("Remote current sizes:", {x: size(ftp, x) for x in FILES}, flush=True)
            print("Stage:", {x: size(ftp, x + NEW) for x in FILES if exists(ftp, x + NEW)})
            print("Backup:", {x: size(ftp, x + OLD) for x in FILES if exists(ftp, x + OLD)})
            return

        if args.action == "stage":
            if any(exists(ftp, x + NEW) or exists(ftp, x + OLD) for x in FILES):
                raise RuntimeError("Existing stage/backup; refusing to overwrite: inspect status")
            for name in FILES:
                if not exists(ftp, name):
                    raise RuntimeError(f"Missing live file {name}")
            for name in FILES:
                upload(ftp, args.dist / name, name + NEW)
                verify_download(ftp, name + NEW, args.dist / name,
                                args.session / ("staged-" + name), args.converted)
            (args.session / "staged.json").write_text(json.dumps(EXPECTED, indent=2))
            print("READY: two staged files verified. Live pair unchanged.", flush=True)

        elif args.action == "activate":
            if not (args.session / "staged.json").exists():
                raise RuntimeError("No completed stage manifest")
            if any(not exists(ftp, x + NEW) for x in FILES):
                raise RuntimeError("Incomplete stage; refusing to activate")
            if any(exists(ftp, x + OLD) for x in FILES):
                raise RuntimeError("Backup names already exist; refusing to overwrite")
            # Independently verify both remote staging files before changing live pair.
            for name in FILES:
                verify_download(ftp, name + NEW, args.dist / name,
                                args.session / ("preactivate-" + name), args.converted)
            check_closed(args.host)
            # First preserve *both* old files, then expose the paired replacements.
            # Recovery handler tries to move any new active files back to stage,
            # then restores the two backups.
            changed = []
            try:
                for name in FILES:
                    rename(ftp, name, name + OLD)
                    changed.append(("saved", name))
                    print(f"Backed up {name}", flush=True)
                for name in FILES:
                    rename(ftp, name + NEW, name)
                    changed.append(("activated", name))
                    print(f"Activated {name}", flush=True)
                for name in FILES:
                    verify_download(ftp, name, args.dist / name,
                                    args.session / ("installed-" + name), args.converted)
                print("SUCCESS: matching executable/mirror installed and verified; prior pair retained.", flush=True)
            except Exception:
                print("ERROR: activation failed; attempting automatic rollback", flush=True)
                try:
                    for name in FILES:
                        if exists(ftp, name) and exists(ftp, name + OLD):
                            rename(ftp, name, name + NEW)
                    for name in FILES:
                        if exists(ftp, name + OLD) and not exists(ftp, name):
                            rename(ftp, name + OLD, name)
                    print("Recovery names:", {x:exists(ftp, x) for x in FILES}, flush=True)
                except Exception as recovery_error:
                    print(f"URGENT: automatic rollback failed: {recovery_error}", flush=True)
                raise

        elif args.action == "rollback":
            if not all(exists(ftp, x + OLD) for x in FILES):
                raise RuntimeError("Both prior files must exist; refusing unsafe rollback")
            if any(exists(ftp, x + NEW) for x in FILES):
                raise RuntimeError("Stage name occupied; refusing to overwrite")
            for name in FILES:
                rename(ftp, name, name + NEW)
            for name in FILES:
                rename(ftp, name + OLD, name)
            print("Rollback: previous executable and mirror restored; candidate retained as stage.", flush=True)


def exists(ftp, name):
    try:
        n = ftp.size(ROOT + name)
        # ftpsrv v0.21.1 reports missing files as UINT64_MAX instead of 550.
        return n is not None and n != (1 << 64) - 1
    except ftplib.error_perm as e:
        if str(e).startswith("550"):
            return False
        raise


if __name__ == "__main__":
    main()
