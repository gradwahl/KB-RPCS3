#!/usr/bin/env python3
"""Prepare reversible PS5 SPU LLVM tuning A/B experiments for GTA IV NPUB30702.

prepare/status are read-only on PS5. apply/restore refuse to change the
tuning file unless the PS5 title and launcher are fully stopped.
The original tuning file (or its absence) is saved exactly.
No game configuration, game data, or executable is modified.
"""
import argparse
import ftplib
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess

ROOT = "/data/homebrew/PPSA99303/rpcs3/"
TUNE = ROOT + "ps5-tuning.txt"
STAGE = TUNE + ".spu-test-stage"
BACKUP = TUNE + ".spu-test-prev"
KEYS = ("spu_insert_select", "spu_narrow_ls_store", "spu_narrow_ls_check")
MODES = {
    "baseline": (0, 0, 0),
    "narrow-check": (0, 1, 1),
    "narrow-perf": (0, 1, 0),
    "insert-select": (1, 0, 0),
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fetch(ftp, path):
    buf = io.BytesIO()
    try:
        ftp.retrbinary("RETR " + path, buf.write)
        return buf.getvalue()
    except ftplib.error_perm as exc:
        if str(exc).startswith("550"):
            return None
        raise


def delete_verified(ftp, path):
    """PS5 ftpsrv may reply '226 File deleted' instead of standard 250."""
    try:
        ftp.delete(path)
    except ftplib.error_reply as exc:
        # Treat the server's nonstandard 226 as success *only* when the
        # deletion is independently confirmed below.
        if not str(exc).startswith("226 "):
            raise
    if fetch(ftp, path) is not None:
        raise RuntimeError(f"FTP delete did not remove {path}")


def check_stopped(host):
    payload = Path(__file__).resolve().parent / "pskill" / "pslist.elf"
    proc = subprocess.run(["nc", "-w", "4", host, "9021"], input=payload.read_bytes(),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=12, check=True)
    text = proc.stdout.decode("utf-8", "replace")
    if "pskill: done" not in text:
        raise RuntimeError("Incomplete console process listing; refusing modification")
    running = [line for line in text.splitlines()
               if re.search(r"pskill: pid .* (?:eboot.bin|rpcs3ps5-launch.elf)$", line)]
    if running:
        raise RuntimeError("KB-RPCS3 is still running; close it first: " + str(running))
    print("OK: no KB-RPCS3 executable/launcher process running", flush=True)


def variant(base, values):
    text = (base or b"").decode("utf-8")
    for key, val in zip(KEYS, values):
        pat = r"(?m)^(\s*" + re.escape(key) + r"\s+)\S+([^\r\n]*)$"
        hits = list(re.finditer(pat, text))
        if len(hits) > 1:
            raise ValueError("Duplicate tuning key: " + key)
        if len(hits) == 1:
            text = re.sub(pat, lambda m: m[1] + str(val) + m[2], text)
        else:
            if text and not text.endswith("\n"):
                text += "\n"
            text += key + " " + str(val) + "\n"
    return text.encode("utf-8")


def require_known(current, session):
    original = (session / "original.bin").read_bytes() if (session / "original.bin").exists() else None
    variants = {m: (session / (m + ".txt")).read_bytes() for m in MODES}
    known = [original, *variants.values()]
    if current not in known:
        raise RuntimeError("Remote tuning changed outside the experiment; refusing overwrite")
    return original, variants


def put_atomically(ftp, current, desired):
    if fetch(ftp, STAGE) is not None or fetch(ftp, BACKUP) is not None:
        raise RuntimeError("Unexpected existing test-stage/backup path; refusing to overwrite")
    if desired is not None:
        ftp.storbinary("STOR " + STAGE, io.BytesIO(desired))
        ftp.sendcmd("SITE CHMOD 666 " + STAGE)
        if fetch(ftp, STAGE) != desired:
            raise RuntimeError("Staged file readback failed; live tuning unchanged")
    moved = False
    try:
        if current is not None:
            ftp.rename(TUNE, BACKUP)
            moved = True
        if desired is not None:
            ftp.rename(STAGE, TUNE)
        if fetch(ftp, TUNE) != desired:
            raise RuntimeError("Post-swap readback mismatch")
    except Exception:
        if moved:
            if fetch(ftp, TUNE) is not None:
                delete_verified(ftp, TUNE)
            ftp.rename(BACKUP, TUNE)
        raise
    if moved:
        delete_verified(ftp, BACKUP)
    print("OK: tuning variant installed and byte-for-byte verified", flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["prepare", "status", "restore", *MODES])
    p.add_argument("--host", default="192.168.0.137")
    p.add_argument("--port", type=int, default=2121)
    p.add_argument("--session", type=Path, default=Path("results/gta4-spu-tuning-20261030"))
    a = p.parse_args()
    if a.action in ("narrow-check", "narrow-perf"):
        p.error("Narrow-store experiments blocked until scalar checker fix is built and verified; use insert-select first")
    if a.action not in ("prepare", "status"):
        check_stopped(a.host)
    with ftplib.FTP(timeout=30) as ftp:
        ftp.connect(a.host, a.port)
        ftp.login()
        ftp.voidcmd("TYPE I")
        original = fetch(ftp, TUNE)
        if a.action == "status":
            print("Remote tuning file:", "absent (all defaults)" if original is None
                  else f"{len(original)} bytes SHA-256 {sha(original)}")
            if original is not None:
                print(original.decode("utf-8", "replace")[:3000])
            return
        if a.action == "prepare":
            a.session.mkdir(parents=True, exist_ok=False)
            if original is not None:
                (a.session / "original.bin").write_bytes(original)
            for mode, values in MODES.items():
                (a.session / (mode + ".txt")).write_bytes(variant(original, values))
            (a.session / "manifest.json").write_text(
                json.dumps({"original_present": original is not None,
                            "original_sha256": sha(original) if original is not None else None,
                            "modes": {m: dict(zip(KEYS, vals)) for m, vals in MODES.items()}},
                           indent=2), encoding="utf-8")
            print(f"Saved exact baseline ({'present' if original is not None else 'absent'}) and "
                  f"{len(MODES)} reversible variants in {a.session}. PS5 unchanged.")
            return
        manifest = json.loads((a.session / "manifest.json").read_text())
        saved, variants = require_known(original, a.session)
        if (saved is not None) != manifest["original_present"]:
            raise RuntimeError("Inconsistent baseline manifest")
        if saved is not None and sha(saved) != manifest["original_sha256"]:
            raise RuntimeError("Baseline hash mismatch")
        desired = saved if a.action == "restore" else variants[a.action]
        if original == desired:
            print("Tuning already has requested contents; no change")
            return
        put_atomically(ftp, original, desired)
        print("Takes effect on next launch / new SPU JIT compilation; "
              "do not compare warmed blocks compiled with a previous mode.", flush=True)


if __name__ == "__main__":
    main()
