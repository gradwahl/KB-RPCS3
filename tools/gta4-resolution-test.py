#!/usr/bin/env python3
"""Reversible 150% versus 100% resolution-scale test for GTA IV NPUB30702.

Only changes Resolution Scale; all other settings remain identical to the
verified RPCS3 Scheduler + Mega config from the scheduler test.
"""
import argparse
import ftplib
import re
import subprocess
from pathlib import Path
import runpy

helper = runpy.run_path(str(Path(__file__).with_name("gta4-scheduler-ab.py")))
get = helper["get"]
setting = helper["setting"]
replace_setting = helper["replace_setting"]
upload_config = helper["upload_config"]
CONFIG = helper["CONFIG"]
PSLIST = Path(__file__).resolve().parent / "pskill" / "pslist.elf"


def check_closed(host):
    """Refuse to modify a game config while KB-RPCS3 or its launcher runs."""
    proc = subprocess.run(["nc", "-w", "4", host, "9021"], input=PSLIST.read_bytes(),
                          capture_output=True, timeout=14, check=True)
    listing = proc.stdout.decode("utf8", errors="replace")
    if "pskill: done" not in listing:
        raise RuntimeError("Incomplete console process listing; refusing config edit")
    if any(re.search(r"pskill: pid .* (?:eboot.bin|rpcs3ps5-launch.elf)$", line)
           for line in listing.splitlines()):
        raise RuntimeError("GTA IV/KB-RPCS3 is still running; close it before changing resolution")
    print("OK: console game and launcher are closed", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=["prepare", "apply100", "restore150"])
    ap.add_argument("--session", type=Path, default=Path("results/gta4-resolution-20261030"))
    ap.add_argument("--scheduler-session", type=Path, default=Path("results/gta4-scheduler-20261030"))
    ap.add_argument("--host", default="192.168.0.137")
    ap.add_argument("--port", type=int, default=2121)
    args = ap.parse_args()

    if args.action in ("apply100", "restore150"):
        check_closed(args.host)

    with ftplib.FTP(timeout=25) as ftp:
        ftp.connect(args.host, args.port)
        ftp.login()
        live = get(ftp, CONFIG)

        if args.action == "prepare":
            baseline = (args.scheduler_session / "B.yml").read_bytes()
            if live != baseline:
                raise ValueError("Console config is not the verified scheduler-B baseline; refusing to prepare")
            for key, wanted in [("Thread Scheduler Mode", "RPCS3 Scheduler"),
                                ("SPU Block Size", "Mega"), ("Clocks scale", "100"),
                                ("Frame limit", "60"), ("Resolution Scale", "150")]:
                actual = setting(baseline.decode("utf-8"), key)
                if actual != wanted:
                    raise ValueError(f"Unexpected {key}: {actual}")
            args.session.mkdir(parents=True, exist_ok=False)
            (args.session / "150.yml").write_bytes(live)
            (args.session / "100.yml").write_bytes(replace_setting(live, "Resolution Scale", "100"))
            print("Saved both variants. Nothing was changed on the console.")
            return

        original = (args.session / "150.yml").read_bytes()
        reduced = (args.session / "100.yml").read_bytes()
        if live not in (original, reduced):
            raise ValueError("Console config changed outside this test; refusing to overwrite")
        target = reduced if args.action == "apply100" else original
        upload_config(ftp, target)
        print(f"Verified Resolution Scale {setting(target.decode('utf-8'), 'Resolution Scale')}% on console.")
        print("Takes effect on the next GTA IV launch; running game stays unchanged.")


if __name__ == "__main__":
    main()
