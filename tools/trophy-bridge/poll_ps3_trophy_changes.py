#!/usr/bin/env python3
"""Read-only PS3 trophy unlock change detector for future PS5 bridge research.

Reads current TROPUSR.DAT from KB-RPCS3 via FTP and compares against a local
snapshot manifest. Writes an offline event-diff report to a new PC file ONLY.
DOES NOT unlock/register/write PS5 trophies, touch system services, or sync PSN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from ftplib import FTP
from pathlib import Path

from export_rpc3_trophies import read_unlocks, TrophyFormatError

TROPHY_ROOT = "/data/homebrew/PPSA99303/rpcs3/dev_hdd0/home/00000001/trophy"
NPWR = re.compile(r"^NPWR[0-9]{5}_[0-9]{2}$")
MAX_TROPUSR = 2 * 1024 * 1024


class DiffError(ValueError):
    pass


def compare_progress(manifest: dict, states: dict[int, dict],
                     native_plan: dict | None = None) -> dict:
    if manifest.get("schema") != "kb-rpcs3-ps3-trophy-export/v1":
        raise DiffError("Unexpected RPCS3 trophy export schema")
    npwr = manifest.get("communication_id")
    if not isinstance(npwr, str) or not NPWR.fullmatch(npwr):
        raise DiffError("Invalid NPWR ID")
    if manifest.get("has_unlock_database") is not True:
        raise DiffError("Baseline has no confirmed unlock database")
    trophies = manifest.get("trophies")
    if not isinstance(trophies, list) or not trophies or len(trophies) > 4096:
        raise DiffError("Invalid trophy manifest")
    defined = {t.get("id") for t in trophies}
    if (len(defined) != len(trophies) or
            any(not isinstance(i, int) for i in defined) or
            set(states) != defined):
        raise DiffError("Live and baseline trophy IDs differ")

    target = None
    if native_plan is not None:
        if native_plan.get("schema") != "kb-rpcs3-safe-native-trophy-plan/v1":
            raise DiffError("Invalid native plan schema")
        matches = [g for g in native_plan.get("games", []) if g.get("npwr") == npwr]
        if len(matches) != 1 or matches[0].get("registration_allowed") is not False:
            raise DiffError("Native plan is invalid, missing or unexpectedly permits registration")
        target = matches[0].get("ps5_title_id")

    events = []
    reversed_unlocks = []
    for trophy in sorted(trophies, key=lambda x: x["id"]):
        tid = trophy["id"]
        old = trophy.get("unlocked")
        if not isinstance(old, bool):
            raise DiffError(f"Baseline trophy {tid} status is unknown")
        state = states[tid]
        new = state.get("unlocked")
        if not isinstance(new, bool):
            raise DiffError(f"Invalid live trophy {tid} state")
        if old is False and new is True:
            events.append({
                "event": "ps3_trophy_newly_unlocked",
                "npwr": npwr,
                "ps3_trophy_id": tid,
                "name": trophy.get("name", ""),
                "grade": trophy.get("grade", ""),
                "raw_ps3_tick": state.get("ps3_tick"),
                "proposed_ps5_title_id_NOT_REGISTERED": target,
            })
        elif old is True and new is False:
            reversed_unlocks.append(tid)

    return {
        "schema": "kb-rpcs3-trophy-diff/v1",
        "source": "read_only_live_RPCS3_TROPUSR",
        "npwr": npwr,
        "title": manifest.get("game_title", ""),
        "trophy_count": len(trophies),
        "baseline_unlocked": sum(t["unlocked"] for t in trophies),
        "current_unlocked": sum(v["unlocked"] for v in states.values()),
        "new_unlock_events": events,
        "reversed_unlocks_warning": reversed_unlocks,
        "ps5_events_delivered": 0,
        "native_trophy_registration_performed": False,
        "psn_sync_performed": False,
    }


def retr_tropusr(ftp: FTP, npwr: str) -> bytes:
    if not NPWR.fullmatch(npwr):
        raise DiffError("Invalid NPWR ID")
    remote = f"{TROPHY_ROOT}/{npwr}/TROPUSR.DAT"
    data = bytearray()
    def add(block: bytes) -> None:
        if len(data) + len(block) > MAX_TROPUSR:
            raise DiffError("TROPUSR.DAT exceeds read-only size limit")
        data.extend(block)
    ftp.retrbinary("RETR " + remote, add, blocksize=8192)
    return bytes(data)


def inspect(host: str, port: int, manifests_root: Path,
            native_plan: dict | None = None) -> dict:
    dirs = sorted(p for p in manifests_root.iterdir()
                  if p.is_dir() and NPWR.fullmatch(p.name) and
                  (p / "manifest.json").is_file())
    if not dirs:
        raise DiffError("No NPWR trophy manifests found")
    output = {
        "schema": "kb-rpcs3-trophy-bridge-readonly-poll/v1",
        "mode": "READ_ONLY_OFFLINE_NO_PS5_REGISTRATION",
        "games": [],
    }
    with FTP() as ftp:
        ftp.connect(host, port, timeout=10)
        ftp.login()
        for folder in dirs:
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            if manifest.get("communication_id") != folder.name:
                raise DiffError(f"Manifest/NPWR folder mismatch: {folder.name}")
            raw = retr_tropusr(ftp, folder.name)
            # Reuse the tested RPCS3 binary parser without persisting live
            # progress data. Temporary files are deleted before returning.
            with tempfile.TemporaryDirectory(prefix="kb_trophy_poll_") as tmp:
                sample = Path(tmp) / "TROPUSR.DAT"
                sample.write_bytes(raw)
                states = read_unlocks(sample)
            diff = compare_progress(manifest, states, native_plan)
            diff["source_file_sha256"] = hashlib.sha256(raw).hexdigest()
            output["games"].append(diff)
    output["total_new_unlocks"] = sum(len(g["new_unlock_events"]) for g in output["games"])
    output["total_reversed_warnings"] = sum(len(g["reversed_unlocks_warning"]) for g in output["games"])
    return output


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=2121)
    ap.add_argument("--manifests", required=True, type=Path)
    ap.add_argument("--native-plan", type=Path)
    ap.add_argument("--report", required=True, type=Path)
    a = ap.parse_args()
    if a.report.exists():
        ap.error("Output report already exists: refusing to overwrite")
    try:
        plan = json.loads(a.native_plan.read_text(encoding="utf-8")) if a.native_plan else None
        report = inspect(a.host, a.port, a.manifests, plan)
        content = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        with a.report.open("x", encoding="utf-8") as out:
            out.write(content)
        print(content, end="")
    except (OSError, ValueError, TrophyFormatError) as exc:
        ap.exit(1, f"Read-only trophy poll refused: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
