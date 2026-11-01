#!/usr/bin/env python3
"""Read-only RPCS3 trophy export for future PS5 native-trophy interoperability.

This does NOT register trophies with the PS5, modify TROPUSR.DAT, or sync PSN.
Only standard-library Python is required.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import struct
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

MAGIC = 0x818F54AD
MAX_FILE_SIZE = 32 * 1024 * 1024
MAX_TROPHIES = 4096
MAX_TABLES = 32
GRADES = {"B": "bronze", "S": "silver", "G": "gold", "P": "platinum"}
SAFE_SET_NAME = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


class TrophyFormatError(ValueError):
    """Input cannot safely be interpreted as RPCS3 trophy data."""


def _xml_text(element: ET.Element, tag: str) -> str:
    child = element.find(tag)
    return (child.text or "").strip() if child is not None else ""


def read_config(path: Path) -> dict:
    data = path.read_bytes()
    if len(data) > MAX_FILE_SIZE:
        raise TrophyFormatError("TROPCONF.SFM is unexpectedly large")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise TrophyFormatError(f"Invalid TROPCONF.SFM XML: {exc}") from exc

    # RPCS3 normally uses <trophyconf>; allow a wrapping document.
    if root.tag != "trophyconf":
        root = root.find("trophyconf")
    if root is None:
        raise TrophyFormatError("Missing trophyconf root")

    groups = []
    group_ids = set()
    for group in root.findall("group"):
        try:
            group_id = int(group.attrib["id"])
        except (KeyError, ValueError) as exc:
            raise TrophyFormatError("Invalid trophy group ID") from exc
        if not 1 <= group_id <= 9999 or group_id in group_ids:
            raise TrophyFormatError(f"Duplicate or out-of-range group ID: {group_id}")
        group_ids.add(group_id)
        groups.append({"id": group_id, "name": _xml_text(group, "name"), "description": _xml_text(group, "detail")})

    trophies = []
    used = set()
    for item in root.findall("trophy"):
        try:
            number = int(item.attrib["id"])
        except (KeyError, ValueError) as exc:
            raise TrophyFormatError("Missing or invalid trophy id") from exc
        if number < 0 or number >= MAX_TROPHIES or number in used:
            raise TrophyFormatError(f"Duplicate or out-of-range trophy id: {number}")
        used.add(number)
        letter = item.get("ttype", "").upper()
        if letter not in GRADES:
            raise TrophyFormatError(f"Trophy {number} has unknown type {letter!r}")
        hidden = item.get("hidden", item.get("hid", "no")).lower() in ("yes", "true", "1")
        pid_str = item.get("pid", "-1")
        try:
            pid = int(pid_str)
        except ValueError as exc:
            raise TrophyFormatError(f"Invalid platinum link for trophy {number}") from exc
        try:
            trophy_group_id = int(item.attrib["gid"]) if "gid" in item.attrib else None
        except ValueError as exc:
            raise TrophyFormatError(f"Invalid group ID for trophy {number}") from exc
        if trophy_group_id is not None and trophy_group_id not in group_ids:
            raise TrophyFormatError(f"Trophy {number} references unknown group {trophy_group_id}")
        trophies.append({
            "id": number,
            "group_id": trophy_group_id,
            "name": _xml_text(item, "name"),
            "description": _xml_text(item, "detail"),
            "grade": GRADES[letter],
            "hidden": hidden,
            "platinum_link_id": None if pid in (-1, 0xFFFFFFFF) else pid,
            "unlocked": None,
            "ps3_tick": None,
            "icon": None,
        })

    if not trophies:
        raise TrophyFormatError("No trophies in TROPCONF.SFM")
    trophies.sort(key=lambda item: item["id"])
    return {
        "title": _xml_text(root, "title-name"),
        "description": _xml_text(root, "title-detail"),
        "communication_id": _xml_text(root, "npcommid") or path.parent.name,
        "groups": groups,
        "trophies": trophies,
    }


def read_unlocks(path: Path) -> dict[int, dict]:
    """Parse RPCS3 big-endian TROPUSR table type 6, without modifying it.

    Source: rpcs3/rpcs3/Loader/TROPUSR.h and TROPUSR.cpp.
    The table-entry size field excludes the 0x10-byte entry header.
    PS3 ticks are intentionally preserved raw, not mislabelled Unix times.
    """
    if path.stat().st_size > MAX_FILE_SIZE:
        raise TrophyFormatError("TROPUSR.DAT is unexpectedly large")
    data = path.read_bytes()
    if len(data) < 0x30:
        raise TrophyFormatError("TROPUSR.DAT header is truncated")
    magic, _version, num_tables, _reserved = struct.unpack_from(">IIII", data, 0)
    if magic != MAGIC:
        raise TrophyFormatError("Not an RPCS3 TROPUSR.DAT (bad magic)")
    if not 1 <= num_tables <= MAX_TABLES:
        raise TrophyFormatError("Invalid TROPUSR table count")
    headers_end = 0x30 + num_tables * 0x20
    if headers_end > len(data):
        raise TrophyFormatError("Truncated TROPUSR table headers")

    seen_table6 = False
    unlocks = {}
    for index in range(num_tables):
        pos = 0x30 + index * 0x20
        kind, entry_size, _unused, count, offset, _unused2 = struct.unpack_from(
            ">IIIIQQ", data, pos
        )
        if kind != 6:
            continue
        if seen_table6:
            raise TrophyFormatError("Duplicate type-6 trophy tables")
        seen_table6 = True
        if entry_size != 0x60 or count > MAX_TROPHIES:
            raise TrophyFormatError("Invalid RPCS3 type-6 table layout")
        stride = entry_size + 0x10
        if offset < headers_end or offset + stride * count > len(data):
            raise TrophyFormatError("Type-6 trophy entries are out of bounds")
        for i in range(count):
            pos = offset + i * stride
            row_type, row_size, row_index, _unused, trophy_id, state, _a, _b, ts1, ts2 = (
                struct.unpack_from(">IIIIIIIIQQ", data, pos)
            )
            if row_type != 6 or row_size != 0x60 or row_index != i:
                raise TrophyFormatError(f"Corrupted type-6 row {i}")
            if trophy_id in unlocks or state not in (0, 1):
                raise TrophyFormatError(f"Invalid state or duplicate trophy {trophy_id}")
            unlocks[trophy_id] = {
                "unlocked": bool(state),
                "ps3_tick": ts2 if state else None,
            }
    if not seen_table6:
        raise TrophyFormatError("Missing RPCS3 type-6 unlock table")
    return unlocks


def discover_sets(source: Path) -> list[Path]:
    if not source.is_dir():
        raise TrophyFormatError(f"Input is not a directory: {source}")
    if (source / "TROPCONF.SFM").is_file():
        return [source]
    folders = sorted({p.parent for p in source.rglob("TROPCONF.SFM")})
    if not folders:
        raise TrophyFormatError("No TROPCONF.SFM found beneath input directory")
    return folders


def prepare_set(folder: Path) -> tuple[dict, list[tuple[Path, str]]]:
    config = read_config(folder / "TROPCONF.SFM")
    state_file = folder / "TROPUSR.DAT"
    states_present = state_file.is_file()
    if states_present:
        unlocks = read_unlocks(state_file)
        defined = {trophy["id"] for trophy in config["trophies"]}
        if set(unlocks) != defined:
            raise TrophyFormatError(
                "TROPUSR trophy IDs do not match TROPCONF; refusing an incorrect merge"
            )
        for trophy in config["trophies"]:
            trophy.update(unlocks[trophy["id"]])

    assets = []
    title_icon = folder / "ICON0.PNG"
    if title_icon.is_file():
        assets.append((title_icon, "icons/ICON0.PNG"))
    for group in config["groups"]:
        group_icon = folder / f"GR{group['id']:03d}.PNG"
        if group_icon.is_file():
            group["icon"] = f"icons/{group_icon.name}"
            assets.append((group_icon, group["icon"]))
        else:
            group["icon"] = None
    for trophy in config["trophies"]:
        icon_path = folder / f"TROP{trophy['id']:03d}.PNG"
        if icon_path.is_file():
            name = f"icons/{icon_path.name}"
            trophy["icon"] = name
            assets.append((icon_path, name))

    manifest = {
        "schema": "kb-rpcs3-ps3-trophy-export/v1",
        "source": "RPCS3 local PS3 trophies",
        "registration_status": "NOT_REGISTERED_WITH_PS5",
        "psn_sync": False,
        "trophy_set": folder.name,
        "communication_id": config["communication_id"],
        "game_title": config["title"],
        "game_description": config["description"],
        "groups": config["groups"],
        "has_unlock_database": states_present,
        "trophies": config["trophies"],
    }
    return manifest, assets


def export(source: Path, output: Path, *, dry_run=False, no_icons=False) -> list[dict]:
    folders = discover_sets(source)
    output = output.resolve()
    jobs = []
    names = set()
    for folder in folders:
        if not SAFE_SET_NAME.fullmatch(folder.name):
            raise TrophyFormatError(f"Unsafe trophy directory name: {folder.name!r}")
        if folder.name.lower() in names:
            raise TrophyFormatError(f"Duplicate trophy set directory: {folder.name}")
        names.add(folder.name.lower())
        manifest, assets = prepare_set(folder)
        if no_icons:
            for trophy in manifest["trophies"]:
                trophy["icon"] = None
            for group in manifest["groups"]:
                group["icon"] = None
            assets = []
        destination = output / folder.name
        if destination.exists() and not dry_run:
            raise TrophyFormatError(
                f"Output already exists: {destination} (choose a new output directory)"
            )
        jobs.append((destination, manifest, assets))

    if not dry_run:
        for destination, manifest, assets in jobs:
            destination.mkdir(parents=True, exist_ok=False)
            (destination / "manifest.json").write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            if not no_icons:
                for source_icon, relative in assets:
                    target = destination / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source_icon, target)

    return [{
        "trophy_set": manifest["trophy_set"],
        "game_title": manifest["game_title"],
        "trophies": len(manifest["trophies"]),
        "unlocked": sum(t["unlocked"] is True for t in manifest["trophies"]),
        "has_unlock_database": manifest["has_unlock_database"],
        "output": str(destination),
    } for destination, manifest, _ in jobs]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="RPCS3 trophy/ directory or individual NPWR folder")
    parser.add_argument("--output", type=Path, required=True, help="New local directory for JSON manifests and optional icons")
    parser.add_argument("--dry-run", action="store_true", help="Validate input; do not create files")
    parser.add_argument("--no-icons", action="store_true", help="Export metadata only")
    args = parser.parse_args(argv)
    try:
        results = export(args.input, args.output, dry_run=args.dry_run, no_icons=args.no_icons)
    except (TrophyFormatError, OSError) as exc:
        print(f"trophy-bridge: {exc}", file=sys.stderr)
        return 1
    for result in results:
        print(json.dumps(result, ensure_ascii=False))
    print("DRY RUN ONLY" if args.dry_run else "LOCAL EXPORT ONLY; NOT INSTALLED ON PS5")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
