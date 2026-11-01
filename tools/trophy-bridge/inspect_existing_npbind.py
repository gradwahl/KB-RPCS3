#!/usr/bin/env python3
"""Read-only structural inspector for an EXISTING PS5 game's npbind.dat.

This does not create, copy, decrypt, alter, authenticate or install bindings.
The secret/sealed TLV values are never emitted or written to disk.
The extracted plaintext NPWR is not proof of registration or valid signature.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
from ftplib import FTP, error_perm
from pathlib import Path

NPBIND_MAGIC = 0xD294A018
NPWR_RE = re.compile(r"^NPWR[0-9]{5}_[0-9]{2}$")
PS5_TITLE_RE = re.compile(r"^(?:PPSA|PPSB)[0-9]{5}$")
MAX_NPBIND_BYTES = 4096
MAX_PARAM_BYTES = 32768


class BindingFormatError(ValueError):
    pass


def inspect_npbind(data: bytes) -> dict:
    """Parse only the non-secret header and NPWR TLV, fail closed on bad lengths."""
    if not 0x90 <= len(data) <= MAX_NPBIND_BYTES:
        raise BindingFormatError("npbind.dat size outside expected bounds")
    magic, version, _reserved, declared_size = struct.unpack_from(">IIII", data)
    if magic != NPBIND_MAGIC:
        raise BindingFormatError("npbind.dat magic mismatch")
    if version != 1:
        raise BindingFormatError("Unsupported npbind.dat version")
    if declared_size != len(data):
        raise BindingFormatError("npbind.dat declared size mismatch")
    index = 0x80
    npwr = None
    tags = []
    while index + 4 <= len(data):
        tag, size = struct.unpack_from(">HH", data, index)
        index += 4
        if tag == 0:
            break
        if size > len(data) - index:
            raise BindingFormatError("Malformed TLV length")
        if tag in (t["tag"] for t in tags):
            raise BindingFormatError("Duplicate TLV tags")
        tags.append({"tag": tag, "bytes": size})
        if tag == 0x10:
            if size != 12:
                raise BindingFormatError("npbind NpCommId has unexpected length")
            try:
                value = data[index:index + size].decode("ascii")
            except UnicodeDecodeError as exc:
                raise BindingFormatError("Non-ASCII NPWR") from exc
            if not NPWR_RE.fullmatch(value):
                raise BindingFormatError("Invalid NPWR string")
            npwr = value
        index += size
    if npwr is None:
        raise BindingFormatError("Missing plaintext NPWR tag 0x0010")
    return {
        "format": "existing-ps5-npbind/v1",
        "size_bytes": len(data),
        "version": version,
        "npwr": npwr,
        "tlv_layout": tags,
        "signature_status": "NOT_CHECKED_CANNOT_AUTHENTICATE_OFFLINE",
        "reusable_as_new_game_binding": False,
    }


def bounded_retr(ftp: FTP, path: str, limit: int) -> bytes:
    blob = bytearray()
    def append(block: bytes) -> None:
        if len(blob) + len(block) > limit:
            raise BindingFormatError("FTP file exceeds size limit")
        blob.extend(block)
    ftp.retrbinary("RETR " + path, append)
    return bytes(blob)


def inspect_existing_title(ftp: FTP, title_id: str) -> dict:
    if not PS5_TITLE_RE.fullmatch(title_id):
        raise BindingFormatError("Not a PS5 game title ID")
    base = f"/data/etaHEN/games/{title_id}/sce_sys"
    param = bounded_retr(ftp, base + "/param.json", MAX_PARAM_BYTES)
    try:
        title_param = json.loads(param)
    except (ValueError, UnicodeDecodeError) as exc:
        raise BindingFormatError("Bad native game param.json") from exc
    if title_param.get("titleId") != title_id:
        raise BindingFormatError("Native game identity does not match directory")
    raw = bounded_retr(ftp, base + "/trophy2/npbind.dat", MAX_NPBIND_BYTES)
    binding = inspect_npbind(raw)
    return {
        "title_id": title_id,
        "npwr": binding["npwr"],
        "binding": binding,
        "source": "READ_ONLY_EXISTING_GAME",
        "supports_synthetic_ps3_trophy_registration": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--file", type=Path, help="Existing local npbind.dat")
    mode.add_argument("--title", type=str, help="Existing title under PS5 /data/etaHEN/games")
    ap.add_argument("--host", help="PS5 FTP host (required for --title)")
    ap.add_argument("--port", type=int, default=2121)
    args = ap.parse_args()
    try:
        if args.file:
            result = inspect_npbind(args.file.read_bytes())
        else:
            if not args.host:
                ap.error("--host is required with --title")
            with FTP() as ftp:
                ftp.connect(args.host, args.port, timeout=12)
                ftp.login()
                result = inspect_existing_title(ftp, args.title)
        print(json.dumps(result, indent=2))
    except (BindingFormatError, OSError, error_perm) as exc:
        ap.exit(1, f"npbind read-only inspector: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
