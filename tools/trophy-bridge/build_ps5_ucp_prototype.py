#!/usr/bin/env python3
"""Offline PS5-format trophy00.ucp prototype from read-only RPCS3 exports.

Builds a structurally valid NpTrophy v2 UCP with a digest and JSON definitions,
following the public sample in LiEnby/PS5TrophyExtract0r/Examples.
This is NOT an installable or PSN-valid trophy package: it has no npbind.dat,
no signed title association, and no PS5 trophy service registration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

UCP_MAGIC = 0xB228C60A
HEADER_BYTES = 0x60
ENTRY_BYTES = 0x40
MAX_ENTRIES = 8192
MAX_FILE_BYTES = 128 * 1024 * 1024
ENTRY_NAME = re.compile(r"^[a-zA-Z0-9_.-]{1,31}$")
GRADE_LETTERS = {"platinum": "P", "gold": "G", "silver": "S", "bronze": "B"}
LANG = "en-US"


class UcpFormatError(ValueError):
    pass


def align16(value: int) -> int:
    return (value + 15) & ~15


def pack_ucp(entries: dict[str, bytes]) -> bytes:
    """Pack UCP, including the 20-byte SHA1 over the file with digest zeroed."""
    if not entries or len(entries) > MAX_ENTRIES:
        raise UcpFormatError("Invalid UCP entry count")
    for name, payload in entries.items():
        if not ENTRY_NAME.fullmatch(name) or not isinstance(payload, bytes):
            raise UcpFormatError(f"Invalid UCP entry name or content: {name!r}")
        if len(payload) > MAX_FILE_BYTES:
            raise UcpFormatError(f"UCP entry is too large: {name}")

    names = sorted(entries)
    start = align16(HEADER_BYTES + ENTRY_BYTES * len(names))
    blob = bytearray(start)
    records = []
    for name in names:
        offset = len(blob)
        payload = entries[name]
        blob.extend(payload)
        blob.extend(bytes(align16(len(blob)) - len(blob)))
        records.append((name, offset, len(payload)))
    if len(blob) > MAX_FILE_BYTES:
        raise UcpFormatError("UCP too large")

    struct.pack_into(">IIQIII", blob, 0, UCP_MAGIC, 1, len(blob), len(names), 0x40, 0)
    for i, (name, offset, size) in enumerate(records):
        position = HEADER_BYTES + i * ENTRY_BYTES
        blob[position:position + 32] = name.encode("ascii").ljust(32, b"\0")
        struct.pack_into(">QQ", blob, position + 32, offset, size)

    blob[0x1c:0x30] = hashlib.sha1(blob).digest()
    return bytes(blob)


def inspect_ucp(raw: bytes) -> dict:
    """Validate offsets, layout, content and SHA1; return safe file listings."""
    if not HEADER_BYTES <= len(raw) <= MAX_FILE_BYTES:
        raise UcpFormatError("Invalid UCP file size")
    magic, version, file_size, count, toc_offset, reserved = struct.unpack_from(">IIQIII", raw, 0)
    if magic != UCP_MAGIC or version != 1:
        raise UcpFormatError("Not a version-1 PS5 UCP")
    if file_size != len(raw) or reserved != 0 or toc_offset != 0x40:
        raise UcpFormatError("Unexpected UCP header")
    if not 1 <= count <= MAX_ENTRIES or HEADER_BYTES + count * ENTRY_BYTES > len(raw):
        raise UcpFormatError("Invalid UCP table")
    digest = bytearray(raw)
    expected = bytes(digest[0x1c:0x30])
    digest[0x1c:0x30] = bytes(20)
    if hashlib.sha1(digest).digest() != expected:
        raise UcpFormatError("UCP SHA1 digest mismatch")
    names = []
    spans = []
    for i in range(count):
        position = HEADER_BYTES + i * ENTRY_BYTES
        name_bytes = raw[position:position + 32].partition(b"\0")[0]
        try:
            name = name_bytes.decode("ascii")
        except UnicodeDecodeError as exc:
            raise UcpFormatError("Invalid entry name encoding") from exc
        offset, size = struct.unpack_from(">QQ", raw, position + 32)
        if not ENTRY_NAME.fullmatch(name) or offset < HEADER_BYTES + count * ENTRY_BYTES or offset + size > len(raw):
            raise UcpFormatError("UCP invalid entry or out-of-bounds payload")
        names.append(name)
        spans.append((offset, offset + size))
        if name.endswith(".json"):
            try:
                json.loads(raw[offset:offset + size])
            except (ValueError, UnicodeDecodeError) as exc:
                raise UcpFormatError(f"Invalid embedded JSON {name}") from exc
    if names != sorted(set(names)):
        raise UcpFormatError("UCP entry names out of order or duplicate")
    spans.sort()
    if any(spans[i][1] > spans[i + 1][0] for i in range(len(spans) - 1)):
        raise UcpFormatError("Overlapping UCP file entries")
    return {"files": names, "count": count, "bytes": len(raw), "sha1_valid": True}


def _json_bytes(obj: dict) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def build_trophy_entries(manifest_path: Path, *, experimental_uds_conditions: bool = False) -> dict[str, bytes]:
    """Map PS3 trophies to PS5 v2 names. Optional synthetic UDS rules are OFF by default.

    Test-only stat IDs: 1000+PS3 trophy ID (non-platinum only). These are
    hypotheses, not documented Sony-authorized trophy unlock definitions.
    """
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "kb-rpcs3-ps3-trophy-export/v1":
        raise UcpFormatError("Unsupported trophy manifest schema")
    comm_id = manifest.get("communication_id", "")
    if not re.fullmatch(r"NPWR[0-9]{5}_[0-9]{2}", comm_id):
        raise UcpFormatError("Invalid NPWR ID")
    trophies = manifest.get("trophies", [])
    groups = manifest.get("groups", [])
    if not isinstance(trophies, list) or not trophies or len(trophies) > 4096:
        raise UcpFormatError("Invalid trophy list")

    group_ids = {g["id"] for g in groups}
    if len(group_ids) != len(groups) or any(not isinstance(i, int) or not 1 <= i <= 9999 for i in group_ids):
        raise UcpFormatError("Invalid trophy group IDs")

    definitions, texts = [], []
    ids = set()
    entries: dict[str, bytes] = {}
    for trophy in trophies:
        tid = trophy.get("id")
        if not isinstance(tid, int) or not 0 <= tid <= 9999 or tid in ids:
            raise UcpFormatError(f"Invalid or repeated trophy id: {tid}")
        ids.add(tid)
        grade = GRADE_LETTERS.get(trophy.get("grade"))
        if not grade:
            raise UcpFormatError(f"Invalid grade for trophy {tid}")
        item = {"id": f"{tid:04d}", "hidden": bool(trophy.get("hidden")), "grade": grade, "hasReward": False}
        if experimental_uds_conditions and grade != "P":
            item["unlockCondition"] = {
                "udsStatId": str(1000 + tid), "comparator": "ge",
                "targetValue": "1", "progressive": False,
            }
        pid = trophy.get("platinum_link_id")
        if pid is not None:
            if not isinstance(pid, int) or not 0 <= pid <= 9999:
                raise UcpFormatError(f"Invalid platinum link for {tid}")
            item["platinumTrophyId"] = f"{pid:04d}"
        gid = trophy.get("group_id")
        if gid is not None:
            if gid not in group_ids:
                raise UcpFormatError(f"Trophy {tid} references unknown group {gid}")
            item["groupId"] = f"{gid:04d}"
        definitions.append(item)
        texts.append({"id": item["id"], "name": trophy.get("name", ""), "detail": trophy.get("description", "")})
        png_ref = trophy.get("icon")
        if png_ref:
            icon = _read_icon(manifest_path.parent, png_ref)
            entries[f"trop{tid:04d}.png"] = icon

    for item in definitions:
        if "platinumTrophyId" in item and int(item["platinumTrophyId"]) not in ids:
            raise UcpFormatError("Unknown platinum trophy reference")

    group_definitions, group_texts = [], []
    for group in sorted(groups, key=lambda g: g["id"]):
        groupid = f"{group['id']:04d}"
        group_definitions.append({"id": groupid})
        group_texts.append({"id": groupid, "name": group.get("name", "")})
        if group.get("icon"):
            entries[f"gr{groupid}_{LANG}.png"] = _read_icon(manifest_path.parent, group["icon"])

    if (manifest_path.parent / "icons" / "ICON0.PNG").is_file():
        entries[f"icon0_{LANG}.png"] = _read_icon(manifest_path.parent, "icons/ICON0.PNG")

    revision = 1  # New experimental revision. NOT official PS5/PSN authorization.
    trophy_set_version = "1.0"
    entries["tropconf.json"] = _json_bytes({
        "schemaVersion": "0.90",
        "trophyDefinitionRevision": revision,
        "platform": ["PS5"],
        "trophyNpCommId": comm_id,
        "udsNpCommId": comm_id,
        "trophySetVersion": trophy_set_version,
        "defaultLanguage": LANG,
        "languages": [LANG],
        "groups": group_definitions,
        "trophies": definitions,
    })
    entries[f"tropmeta_{LANG}.json"] = _json_bytes({
        "schemaVersion": "0.90",
        "trophyDefinitionRevision": revision,
        "trophySetVersion": trophy_set_version,
        "trophyNpCommId": comm_id,
        "metadata": {
            "titleMetadata": {"name": manifest.get("game_title", "")},
            "groupMetadata": group_texts,
            "trophyMetadata": texts,
        },
    })
    return entries


def _read_icon(root: Path, relative: str) -> bytes:
    # Refuse paths outside this exported game folder.
    allowed = root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(allowed) or path.parent.name != "icons":
        raise UcpFormatError("Icon path outside exported icons folder")
    content = path.read_bytes()
    if not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise UcpFormatError(f"Invalid PNG header: {relative}")
    return content


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True, help="RPCS3 exporter manifest.json")
    parser.add_argument("--output", type=Path, required=True, help="New offline trophy00.ucp output path")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        entries = build_trophy_entries(args.manifest)
        ucp = pack_ucp(entries)
        report = inspect_ucp(ucp)
        if args.output.exists() and not args.dry_run:
            raise UcpFormatError("Output already exists; refusing to overwrite")
        if not args.dry_run:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(ucp)
        print(json.dumps({
            "status": "OFFLINE_PROTOTYPE_NOT_PS5_REGISTERED",
            "output": str(args.output),
            "source": str(args.manifest),
            "files": report["count"],
            "bytes": report["bytes"],
            "sha1_verified": report["sha1_valid"],
            "dry_run": args.dry_run,
        }, indent=2))
    except (UcpFormatError, OSError, KeyError, ValueError, TypeError) as exc:
        parser.exit(1, f"PS5 UCP prototype: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
