#!/usr/bin/env python3
"""Read-only FTP snapshot of KB-RPCS3 PS3 trophy records and PNG icons.

This intentionally uses only FTP commands USER/PASS, PWD/CWD, LIST, TYPE, PASV,
RETR, QUIT; never DELE, STOR, RNFR, MKD or any console-side write commands.
Snapshots are stored outside Git by default, with no overwrites.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from ftplib import FTP
from pathlib import Path

TROPHY_ROOT = "/data/homebrew/PPSA99303/rpcs3/dev_hdd0/home/00000001/trophy"
NPWR_PATTERN = re.compile(r"NPWR[0-9]{5}_[0-9]{2}")
FILE_PATTERN = re.compile(r"(?:TROPUSR\.DAT|TROPCONF\.SFM|ICON0\.PNG|TROP[0-9]{3}\.PNG|GR[0-9]{3}\.PNG)")
MAX_FILES_PER_SET = 256
MAX_FILE_BYTES = 12 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024


def list_directory(ftp: FTP, path: str) -> list[tuple[str, int, str]]:
    ftp.cwd(path)
    rows = []
    ftp.retrlines("LIST", rows.append)
    results = []
    for row in rows:
        parts = row.split(maxsplit=8)
        if len(parts) != 9 or parts[8] in (".", ".."):
            continue
        if parts[0].startswith("l"):
            raise ValueError(f"Symlink not supported in FTP snapshot: {parts[8]}")
        kind = "dir" if parts[0].startswith("d") else "file"
        if not parts[0].startswith(("-", "d")):
            raise ValueError(f"Unsupported FTP entry type: {parts[8]}")
        results.append((parts[8], int(parts[4]), kind))
    return results


def snapshot(host: str, port: int, destination_parent: Path, *, dry_run: bool = False) -> dict:
    with FTP() as ftp:
        ftp.connect(host, port, timeout=15)
        ftp.login()  # PS5 etaHEN FTP: anonymous login (no stored credentials).
        root_items = list_directory(ftp, TROPHY_ROOT)
        sets = sorted(name for name, _, kind in root_items if kind == "dir" and NPWR_PATTERN.fullmatch(name))
        if not sets:
            raise RuntimeError("No NPWR trophy folders found")
        planned = []
        total_bytes = 0
        for name in sets:
            subpath = f"{TROPHY_ROOT}/{name}"
            entries = list_directory(ftp, subpath)
            selected = [(filename, size) for filename, size, kind in entries
                        if kind == "file" and FILE_PATTERN.fullmatch(filename)]
            names = {x for x, _ in selected}
            if not {"TROPCONF.SFM", "TROPUSR.DAT"} <= names:
                raise ValueError(f"{name}: incomplete trophy set")
            if len(selected) > MAX_FILES_PER_SET or any(size < 0 or size > MAX_FILE_BYTES for _, size in selected):
                raise ValueError(f"{name}: suspicious file count/size")
            total_bytes += sum(size for _, size in selected)
            if total_bytes > MAX_TOTAL_BYTES:
                raise ValueError("Snapshot exceeds safe total size")
            planned.append((name, selected))

        if dry_run:
            return {"mode": "read-only dry run", "sets": [{"npwr": name, "files": len(files), "bytes": sum(size for _, size in files)} for name, files in planned]}

        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output = destination_parent / f"kb-rpcs3-trophies_{stamp}"
        index = 1
        while output.exists():
            output = destination_parent / f"kb-rpcs3-trophies_{stamp}_{index}"
            index += 1
        output.mkdir(parents=True, exist_ok=False)
        snapshot_root = output / "source"
        snapshot_root.mkdir()
        report = {"source": TROPHY_ROOT, "read_only_ftp": True, "folders": [], "total_bytes": total_bytes}
        for name, files in planned:
            directory = snapshot_root / name
            directory.mkdir()
            record = {"npwr": name, "file_count": len(files), "files": []}
            for filename, expected in files:
                local = directory / filename
                digest = hashlib.sha256()
                written = 0
                with local.open("xb") as stream:
                    def callback(block: bytes) -> None:
                        nonlocal written
                        stream.write(block)
                        digest.update(block)
                        written += len(block)
                        if written > MAX_FILE_BYTES:
                            raise ValueError(f"File size limit exceeded: {filename}")
                    ftp.retrbinary(f"RETR {TROPHY_ROOT}/{name}/{filename}", callback)
                if written != expected:
                    raise ValueError(f"FTP file changed or was incomplete: {name}/{filename} expected {expected} got {written}")
                record["files"].append({"name": filename, "bytes": written, "sha256": digest.hexdigest()})
            report["folders"].append(record)
        (output / "snapshot-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return {"mode": "read-only snapshot complete", "output": str(output), "folders": [{"npwr": i["npwr"], "file_count": i["file_count"]} for i in report["folders"]], "total_bytes": total_bytes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="IP address or hostname of your own PS5 FTP server")
    parser.add_argument("--port", type=int, default=2121)
    parser.add_argument("--output-parent", type=Path, default=Path.home() / "Documents" / "KB-RPCS3-Trophy-Bridge-Data")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = snapshot(args.host, args.port, args.output_parent, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
