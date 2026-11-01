#!/usr/bin/env python3
"""Read-only KB-RPCS3 PS5 trophy-registration preflight, NOT an installer.

Queries only documented KB-RPCS3 game/tile locations via FTP CWD, LIST, RETR;
does not download or modify saves, profile trophies, or console system data.
Maps PS3 trophy NPWR IDs to installed-game serials by TROPDIR folder presence.
A PS3 ISO name alone is NOT enough to prove its internal serial or NPWR mapping.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import unicodedata
import zlib
from ftplib import FTP, error_perm
from pathlib import Path

ROOT = "/data/homebrew/PPSA99303/rpcs3"
TROPHY_ROOT = ROOT + "/dev_hdd0/home/00000001/trophy"
GAME_ROOT = ROOT + "/dev_hdd0/game"
ISO_ROOT = ROOT + "/PS3ISO"
TILE_RECORD = ROOT + "/ps5-tiles.txt"
SERIAL_RE = re.compile(r"^[A-Z0-9]{9}$")
TILE_RE = re.compile(r"^PPSA8[0-9]{4}$")
NPWR_RE = re.compile(r"^NPWR[0-9]{5}_[0-9]{2}$")
TILE_LINE_LEGACY = re.compile(r"^([A-Z0-9]{9}) (PPSA8[0-9]{4})$")
TILE_LINE = re.compile(r"^(PPSA8[0-9]{4}) (.+)$")


class PreflightError(ValueError):
    pass


def listing(ftp: FTP, path: str) -> list[tuple[str, str]]:
    ftp.cwd(path)
    lines = []
    ftp.retrlines("LIST", lines.append)
    entries = []
    for row in lines:
        parts = row.split(maxsplit=8)
        if len(parts) != 9 or parts[8] in (".", ".."):
            continue
        if parts[0].startswith("d"):
            kind = "dir"
        elif parts[0].startswith("-"):
            kind = "file"
        else:
            continue  # reject symlinks or unknown entry classes
        entries.append((kind, parts[8]))
    return entries


def limited_retr(ftp: FTP, path: str, max_bytes=8192) -> bytes:
    data = bytearray()
    def add(chunk: bytes) -> None:
        if len(data) + len(chunk) > max_bytes:
            raise PreflightError("Tile mapping file exceeds safe size")
        data.extend(chunk)
    ftp.retrbinary("RETR " + path, add)
    return bytes(data)


def parse_sfo_title(raw: bytes) -> tuple[str, str]:
    """Read only TITLE and TITLE_ID from a bounded PS3 PARAM.SFO buffer."""
    if len(raw) < 20 or len(raw) > 8192:
        raise PreflightError("Invalid PARAM.SFO size")
    magic, version, key_start, value_start, count = struct.unpack_from("<4sIIII", raw, 0)
    if magic != b"\x00PSF" or count > 128 or 20 + count * 16 > len(raw):
        raise PreflightError("Invalid PARAM.SFO structure")
    result = {}
    for index in range(count):
        offset, fmt, length, capacity, data_offset = struct.unpack_from(
            "<HHIII", raw, 20 + index * 16
        )
        if key_start + offset >= len(raw) or value_start + data_offset + length > len(raw):
            raise PreflightError("Out-of-bounds PARAM.SFO field")
        key = raw[key_start + offset:].partition(b"\0")[0].decode("ascii", errors="ignore")
        if key in ("TITLE", "TITLE_ID"):
            result[key] = raw[value_start + data_offset:value_start + data_offset + length].partition(b"\0")[0].decode("utf-8", errors="replace")
    return result.get("TITLE", ""), result.get("TITLE_ID", "")


def normalized_game_title(title: str) -> str:
    return "".join(c.lower() for c in unicodedata.normalize("NFKD", title) if c.isalnum())


def read_iso_cache(ftp: FTP, serial: str, iso_filenames: list[str]) -> dict | None:
    """Return weak ISO title/filename evidence. Does NOT establish NPWR identity."""
    if not re.fullmatch(r"XISO[0-9]{5}", serial):
        return None
    root = GAME_ROOT + "/" + serial
    try:
        title, internal = parse_sfo_title(limited_retr(ftp, root + "/PARAM.SFO"))
        link = limited_retr(ftp, root + "/RPCS3_ISO_LINK.txt").decode("utf-8")
    except (error_perm, PreflightError, UnicodeDecodeError):
        return None
    lines = link.splitlines()
    if len(lines) < 2 or lines[0] != "RPCS3_XMB_ISO_V1" or internal != serial:
        return None
    file_name = lines[1].replace("\\", "/").rsplit("/", 1)[-1]
    if file_name not in iso_filenames:
        return None
    return {"cache_serial": serial, "game_title": title, "iso_filename": file_name,
            "identity_status": "TITLE_AND_ISO_FILENAME_ONLY_NPWR_UNVERIFIED"}


def parse_tiles(raw: bytes) -> dict[str, str]:
    mapping = {}
    seen_ids = set()
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise PreflightError("Tile records are not valid UTF-8") from exc
    for line in lines:
        line = line.strip()
        if not line:
            continue
        match = TILE_LINE.fullmatch(line)
        if match:
            title_id, serial = match.groups()
        else:
            older = TILE_LINE_LEGACY.fullmatch(line)
            if older:
                serial, title_id = older.groups()
            else:
                raise PreflightError("Invalid PS5 tile record (possibly a path-based tile)")
        if not SERIAL_RE.fullmatch(serial) or serial in mapping or title_id in seen_ids:
            raise PreflightError("Tile mapping contains unsupported/duplicate IDs")
        mapping[serial] = title_id
        seen_ids.add(title_id)
    return mapping


def suggested_tile_id(serial: str) -> str:
    if not SERIAL_RE.fullmatch(serial):
        raise PreflightError("Invalid game serial")
    return f"PPSA8{zlib.crc32(serial.encode()) % 10000:04d}"


def inspect(ftp: FTP, manifest_dir: Path, prototype_dir: Path | None = None) -> dict:
    try:
        known_trophies = sorted(name for kind, name in listing(ftp, TROPHY_ROOT)
                               if kind == "dir" and NPWR_RE.fullmatch(name))
    except error_perm as exc:
        raise PreflightError(f"Cannot inspect RPCS3 trophy root: {exc}") from exc

    try:
        raw = limited_retr(ftp, TILE_RECORD)
    except error_perm as exc:
        if str(exc).startswith("550"):
            raw = b""
        else:
            raise
    tiles = parse_tiles(raw)
    games = sorted(name for kind, name in listing(ftp, GAME_ROOT)
                   if kind == "dir" and SERIAL_RE.fullmatch(name))
    associations: dict[str, list[str]] = {npwr: [] for npwr in known_trophies}
    for serial in games:
        try:
            entries = listing(ftp, GAME_ROOT + "/" + serial + "/TROPDIR")
        except error_perm as exc:
            if str(exc).startswith("550"):
                continue
            raise
        for kind, npwr in entries:
            if kind == "dir" and npwr in associations:
                associations[npwr].append(serial)

    try:
        iso_files = [name for kind, name in listing(ftp, ISO_ROOT) if kind == "file" and
                     name.lower().endswith((".iso", ".bin"))]
    except error_perm as exc:
        iso_files = [] if str(exc).startswith("550") else (_ for _ in ()).throw(exc)

    iso_cache = [item for serial in games
                 if (item := read_iso_cache(ftp, serial, iso_files)) is not None]
    output = {
        "schema": "kb-rpcs3-trophy-registration-preflight/v1",
        "mode": "READ_ONLY_NO_REGISTRATION",
        "main_ps5_title": "PPSA99303",
        "firmware": "NOT_PROBED",
        "ps5_native_registration_supported": False,
        "tile_records": tiles,
        "installed_ps3_serials": games,
        "unmatched_iso_filenames": iso_files,
        "iso_cache_evidence": iso_cache,
        "trophy_sets": [],
    }
    used_ids = {id_: serial for serial, id_ in tiles.items()}
    for npwr in known_trophies:
        serials = sorted(set(associations[npwr]))
        if len(serials) == 1:
            serial = serials[0]
            existing_id = tiles.get(serial)
            candidate_id = existing_id or suggested_tile_id(serial)
            collided_with = used_ids.get(candidate_id) if not existing_id else None
            if collided_with == serial:
                collided_with = None
        else:
            serial = existing_id = candidate_id = collided_with = None

        blockers = []
        if len(serials) == 0:
            blockers.append("NO_VERIFIED_INSTALLED_GAME_SERIAL; ISO identity not verified")
        elif len(serials) > 1:
            blockers.append("AMBIGUOUS_NPWR_TO_SERIAL_MATCH")
        if not existing_id:
            blockers.append("NO_EXISTING_PER_GAME_PS5_TILE")
        if collided_with:
            blockers.append("CANDIDATE_TILE_ID_COLLISION")
        blockers.extend([
            "NO_VERIFIED_NATIVE_NPBIND_FOR_THIS_TITLE",
            "PS5_NATIVE_REGISTRATION_API_UNVERIFIED",
            "FIRMWARE_COMPATIBILITY_UNVERIFIED",
        ])
        manifest = manifest_dir / npwr / "manifest.json"
        if manifest.is_file():
            item = json.loads(manifest.read_text(encoding="utf-8"))
            if item.get("schema") != "kb-rpcs3-ps3-trophy-export/v1" or item.get("communication_id") != npwr:
                raise PreflightError(f"Manifest does not match {npwr}")
            game_title = item.get("game_title")
            trophy_count = len(item.get("trophies", []))
            group_count = len(item.get("groups", []))
        else:
            blockers.append("NO_LOCAL_EXPORT_MANIFEST")
            game_title = None
            trophy_count = None
            group_count = None
        proto_exists = bool(prototype_dir and
                            (prototype_dir / npwr / "trophy00.ucp").is_file())
        if not proto_exists:
            blockers.append("NO_LOCAL_UCP_PROTOTYPE")
        possible_iso = [x for x in iso_cache if game_title and
                        normalized_game_title(game_title) == normalized_game_title(x["game_title"])]
        output["trophy_sets"].append({
            "npwr": npwr,
            "possible_iso_launcher_caches_not_verified": possible_iso,
            "game": game_title,
            "trophy_count": trophy_count,
            "dlc_group_count": group_count,
            "matching_installed_serials": serials,
            "verified_serial": serial,
            "existing_tile": existing_id,
            "proposed_tile_id_only_not_installed": candidate_id,
            "collision_with_serial": collided_with,
            "has_offline_ucp": proto_exists,
            "blockers": blockers,
            "ready_for_ps5_registration": False,
        })
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=2121)
    parser.add_argument("--manifests", type=Path, required=True, help="Local exported NPWR manifest parent")
    parser.add_argument("--ucp-prototypes", type=Path, help="Local UCP prototype parent")
    parser.add_argument("--report", type=Path, help="New local JSON report path (must not exist)")
    args = parser.parse_args()
    if args.report and args.report.exists():
        parser.error("Report already exists; will not overwrite")
    with FTP() as ftp:
        ftp.connect(args.host, args.port, timeout=12)
        ftp.login()
        result = inspect(ftp, args.manifests, args.ucp_prototypes)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8") as out:
            json.dump(result, out, indent=2, ensure_ascii=False)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
