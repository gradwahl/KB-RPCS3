#!/usr/bin/env python3
"""Offline PS3->PS5 trophy-title mapping and fail-closed native registration gate.

Uses ONLY: previously saved local read-only inventories, verified game identities,
and live PS5 firmware report. May optionally read PS5 title inventory via FTP.
Outputs a PC-side plan. DOES NOT install tiles, bindings, trophies, or patches.
"""
from __future__ import annotations

import argparse
import json
import re
import zlib
from ftplib import FTP, error_perm
from pathlib import Path

NPWR = re.compile(r"^NPWR[0-9]{5}_[0-9]{2}$")
SERIAL = re.compile(r"^[A-Z0-9]{9}$")
TILE = re.compile(r"^PPSA8[0-9]{4}$")
MAX_TILES = 10000


class PlanError(ValueError):
    pass


def allocate_title(serial: str, reserved: set[str], taken: dict[str, str]) -> str:
    """Mirror KB-RPCS3 tiles.cpp crc32 + linear probing, while skipping reserved IDs."""
    if not SERIAL.fullmatch(serial):
        raise PlanError(f"Invalid PS3 serial {serial}")
    start = zlib.crc32(serial.encode("ascii")) % MAX_TILES
    for offset in range(MAX_TILES):
        tid = f"PPSA8{(start + offset) % MAX_TILES:04d}"
        if tid not in reserved and tid not in taken:
            taken[tid] = serial
            return tid
    raise PlanError("No available tile IDs")


def list_used_title_ids(ftp: FTP) -> list[str]:
    """Only list app identifiers; no files or account directories read."""
    used = set()
    for folder in ("/data/homebrew", "/system_data/priv/appmeta"):
        try:
            ftp.cwd(folder)
            listing = []
            ftp.retrlines("LIST", listing.append)
        except error_perm as exc:
            raise PlanError(f"Cannot verify existing PS5 title inventory: {folder} {exc}") from exc
        for line in listing:
            row = line.split(maxsplit=8)
            if len(row) == 9 and row[0].startswith("d") and TILE.fullmatch(row[8]):
                used.add(row[8])
    return sorted(used)


def make_plan(preflight: dict, iso: dict, firmware: dict,
              reserved_title_ids: list[str]) -> dict:
    if preflight.get("schema") != "kb-rpcs3-trophy-registration-preflight/v1":
        raise PlanError("Invalid preflight schema")
    if firmware.get("schema") != "kb-rpcs3-live-firmware/v1" or not firmware.get("kernel_probe_verified"):
        raise PlanError("Unverified PS5 system firmware")
    fw = firmware["firmware"]
    sdk_hex = firmware.get("sdk_hex", "")
    if not re.fullmatch(r"0x[0-9a-fA-F]{8}", sdk_hex) or fw != f"{sdk_hex[2:4]}.{sdk_hex[4:6]}":
        raise PlanError("Firmware report is inconsistent")
    if iso.get("source") != "PS3_DISC_IMAGE_ISO9660" or not iso.get("identity_verified_from_iso"):
        raise PlanError("ISO identity is not verified")
    iso_serial = iso.get("serial")
    iso_npwr = iso.get("trophy_sets")
    if not isinstance(iso_npwr, list) or not SERIAL.fullmatch(iso_serial or "") or not all(NPWR.fullmatch(v) for v in iso_npwr):
        raise PlanError("Invalid ISO serial/NPWR mapping")

    tile_mapping = preflight.get("tile_records", {})
    existing = {tid: serial for serial, tid in tile_mapping.items()}
    if any(not SERIAL.fullmatch(serial) or not TILE.fullmatch(tid) for serial,tid in tile_mapping.items()):
        raise PlanError("Invalid existing PS5 tile map")
    if len(existing) != len(tile_mapping):
        raise PlanError("Duplicate PS5 tile mapping")
    reserved = set(reserved_title_ids)
    if not all(TILE.fullmatch(tid) for tid in reserved):
        raise PlanError("Invalid reserved title identifier")
    # Do not allocate a title over one that exists in PS5 appmeta / homebrew.
    occupied = reserved | set(existing)
    taken: dict[str, str] = {}

    results = []
    used_npwr = set()
    for item in preflight.get("trophy_sets", []):
        npwr = item.get("npwr")
        if not isinstance(npwr, str) or not NPWR.fullmatch(npwr) or npwr in used_npwr:
            raise PlanError("Duplicate/invalid trophy set")
        used_npwr.add(npwr)
        installed_serial = item.get("verified_serial")
        iso_match = npwr in iso_npwr
        if installed_serial and iso_match and installed_serial != iso_serial:
            raise PlanError("Contradictory installed-game and ISO identities")
        if installed_serial:
            if installed_serial not in item.get("matching_installed_serials", []):
                raise PlanError("Installed-game proof missing")
            serial = installed_serial
            source = "installed_PS3_TROPDIR"
        elif iso_match:
            serial = iso_serial
            source = "verified_ISO_PS3_GAME_PARAM_SFO_and_TROPDIR"
        else:
            serial = None
            source = "UNVERIFIED"
        candidate = None
        existing_tile = tile_mapping.get(serial) if serial else None
        if existing_tile:
            if existing_tile in taken and taken[existing_tile] != serial:
                raise PlanError("Duplicate tile assignment")
            candidate = existing_tile
            taken[existing_tile] = serial
        elif serial:
            candidate = allocate_title(serial, occupied, taken)
        blockers = []
        if not serial:
            blockers.append("NO_VERIFIED_PS3_TITLE_ID")
        if not existing_tile:
            blockers.append("PROPOSED_TILE_NOT_INSTALLED")
        blockers.extend([
            "PS5_PER_GAME_ACTIVE_PROCESS_NOT_IMPLEMENTED",
            "SONY_VALID_GAME_SPECIFIC_NPBIND_UNAVAILABLE",
            "NO_VERIFIED_NATIVE_TROPHY_SERVICE_REGISTRATION_INTEGRATION",
            "GUEST_PS3_TO_PS5_UDS_EVENT_PROVIDER_NOT_IMPLEMENTED",
        ])
        # The published PHU patch/offset table ends at 12.70, and no 13.20
        # support has been verified. Never map older firmware offsets forward.
        if fw == "13.20":
            blockers.append("UNSUPPORTED_FIRMWARE_13_20_FOR_PUBLISHED_PHU_PATCHES")
        else:
            blockers.append("FIRMWARE_SPECIFIC_REGISTRATION_STILL_UNVERIFIED")
        results.append({
            "ps3_game": item.get("game"),
            "ps3_serial": serial,
            "identity_evidence": source,
            "npwr": npwr,
            "trophy_count": item.get("trophy_count"),
            "ps5_title_id": candidate,
            "ps5_title_status": "existing_tile" if existing_tile else "PLAN_ONLY_NOT_INSTALLED",
            "ps5_runtime_ownership": "UNVERIFIED_MAIN_APP_RUNS_AS_PPSA99303",
            "ps5_trophy_menu_ready": False,
            "registration_allowed": False,
            "blockers": blockers,
        })
    if not results:
        raise PlanError("No trophy sets found")
    return {
        "schema": "kb-rpcs3-safe-native-trophy-plan/v1",
        "console_firmware": fw,
        "console_sdk": sdk_hex,
        "title_id_algorithm": "KB-RPCS3 tiles.cpp CRC32 % 10000, increment until free",
        "used_ps5_title_ids_seen": sorted(occupied),
        "registration_mode": "DISABLED_OFFLINE_PLANNING_ONLY",
        "creates_npbind": False,
        "writes_console": False,
        "psn_sync": False,
        "games": results,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--preflight", required=True, type=Path)
    p.add_argument("--iso-identity", required=True, type=Path)
    p.add_argument("--firmware", required=True, type=Path)
    p.add_argument("--host", required=True)
    p.add_argument("--port", type=int, default=2121)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    if args.out.exists():
        p.error("Report already exists; no overwrites")
    try:
        with FTP() as ftp:
            ftp.connect(args.host, args.port, timeout=12)
            ftp.login()
            used = list_used_title_ids(ftp)
        plan = make_plan(
            json.loads(args.preflight.read_text(encoding="utf-8")),
            json.loads(args.iso_identity.read_text(encoding="utf-8")),
            json.loads(args.firmware.read_text(encoding="utf-8")),
            used,
        )
        result = json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
        with args.out.open("x", encoding="utf-8") as out:
            out.write(result)
        print(result, end="")
    except (PlanError, OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        p.exit(1, f"Native trophy plan refused: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
