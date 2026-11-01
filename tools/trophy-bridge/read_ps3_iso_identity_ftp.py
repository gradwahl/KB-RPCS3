#!/usr/bin/env python3
"""Read only small ISO9660 metadata ranges from a PS3 ISO on KB-RPCS3 FTP.

Never downloads the entire game, writes console files, or modifies trophy data.
Requires an ordinary 2048-byte-sector ISO9660 image with readable PS3_GAME.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
from ftplib import FTP

SECTOR = 2048
ISO_ROOT = "/data/homebrew/PPSA99303/rpcs3/PS3ISO"
SERIAL = re.compile(r"^[A-Z0-9]{9}$")
NPWR = re.compile(r"^NPWR[0-9]{5}_[0-9]{2}$")
MAX_RANGE = 65536
MAX_CALLS = 16
MAX_TRANSFER = 256 * 1024


class IsoError(ValueError):
    pass


def entry(data: bytes) -> dict:
    if len(data) < 34 or data[0] > len(data) or data[0] < 34:
        raise IsoError("Invalid ISO9660 directory record")
    n = data[32]
    raw = data[33:33 + n]
    if len(raw) != n:
        raise IsoError("Truncated ISO9660 name")
    if raw in (b"\0", b"\1"):
        name = "." if raw == b"\0" else ".."
    else:
        name = raw.decode("ascii", errors="strict").split(";")[0].rstrip(".")
    extent = struct.unpack_from("<I", data, 2)[0]
    length = struct.unpack_from("<I", data, 10)[0]
    return {"name": name, "extent": extent, "bytes": length, "directory": bool(data[25] & 2)}


def entries(data: bytes) -> list[dict]:
    result = []
    position = 0
    while position < len(data):
        size = data[position]
        if not size:
            position = ((position // SECTOR) + 1) * SECTOR
            continue
        if size < 34 or position + size > len(data) or position // SECTOR != (position + size - 1) // SECTOR:
            raise IsoError("Invalid ISO9660 directory length")
        result.append(entry(data[position:position + size]))
        position += size
    return result


def parse_sfo(data: bytes) -> dict:
    if len(data) < 20:
        raise IsoError("Truncated PARAM.SFO")
    magic, _, keys, values, count = struct.unpack_from("<4sIIII", data, 0)
    if magic != b"\x00PSF" or count > 100 or 20 + count * 16 > len(data):
        raise IsoError("Not a PS3 PARAM.SFO")
    parsed = {}
    for i in range(count):
        keyoff, _, length, _, valueoff = struct.unpack_from("<HHIII", data, 20 + i * 16)
        if keys + keyoff >= len(data) or values + valueoff + length > len(data):
            raise IsoError("Out-of-range PARAM.SFO field")
        key = data[keys + keyoff:].partition(b"\0")[0].decode("ascii", "replace")
        if key in {"TITLE_ID", "TITLE", "CATEGORY"}:
            parsed[key] = data[values + valueoff:values + valueoff + length].partition(b"\0")[0].decode("utf-8", "replace")
    if not SERIAL.fullmatch(parsed.get("TITLE_ID", "")):
        raise IsoError("Missing or invalid PS3 title ID")
    return parsed


class FTPPartialISO:
    """One connection per short ranged read; never transfer full ISO."""
    def __init__(self, host: str, port: int, filename: str):
        if filename in ("", ".", "..") or any(x in filename for x in ("/", "\\", "\r", "\n", "\0")) or not filename.lower().endswith(".iso"):
            raise IsoError("Provide an ISO filename, not a path")
        self.host = host
        self.port = port
        self.path = ISO_ROOT + "/" + filename
        self.requests = 0
        self.transferred = 0

    def read(self, offset: int, count: int) -> bytes:
        if not 0 <= offset <= (1 << 42) or not 0 < count <= MAX_RANGE:
            raise IsoError("Invalid ISO byte range")
        self.requests += 1
        if self.requests > MAX_CALLS or self.transferred + count > MAX_TRANSFER:
            raise IsoError("ISO read-only budget exhausted")
        ftp = FTP()
        try:
            ftp.connect(self.host, self.port, timeout=12)
            ftp.login()
            conn = ftp.transfercmd("RETR " + self.path, rest=offset)
            buffer = bytearray()
            try:
                conn.settimeout(12)
                while len(buffer) < count:
                    block = conn.recv(min(8192, count - len(buffer)))
                    if not block:
                        break
                    buffer.extend(block)
            finally:
                # Close early; the server may report "broken pipe", as expected
                # when only a few bytes of a multi-GB ISO are requested.
                conn.close()
        finally:
            ftp.close()
        if len(buffer) != count:
            raise IsoError("Unexpected short read from ISO")
        self.transferred += count
        return bytes(buffer)


def get_identity(source) -> dict:
    pvd = source.read(16 * SECTOR, SECTOR)
    if pvd[0] != 1 or pvd[1:6] != b"CD001":
        raise IsoError("Unrecognized ISO9660 primary volume descriptor")
    root = entry(pvd[156:156 + pvd[156]])
    if not root["directory"]:
        raise IsoError("ISO9660 root is not a directory")

    def directory(folder):
        if folder["bytes"] == 0 or folder["bytes"] > MAX_RANGE:
            raise IsoError("Oversized ISO9660 directory")
        return entries(source.read(folder["extent"] * SECTOR, folder["bytes"]))

    def child(parent, wanted, is_dir):
        matches = [e for e in directory(parent) if e["name"].upper() == wanted and e["directory"] == is_dir]
        if len(matches) != 1:
            raise IsoError(f"Missing/ambiguous ISO9660 path component {wanted}")
        return matches[0]

    game = child(root, "PS3_GAME", True)
    sf = child(game, "PARAM.SFO", False)
    if sf["bytes"] > 8192 or sf["bytes"] < 20:
        raise IsoError("Suspicious PARAM.SFO size")
    meta = parse_sfo(source.read(sf["extent"] * SECTOR, sf["bytes"]))
    tropdir = child(game, "TROPDIR", True)
    trop_sets = sorted(e["name"] for e in directory(tropdir) if e["directory"] and NPWR.fullmatch(e["name"]))
    if not trop_sets:
        raise IsoError("ISO does not contain any NPWR trophy folders")
    return {
        "source": "PS3_DISC_IMAGE_ISO9660",
        "identity_verified_from_iso": True,
        "serial": meta["TITLE_ID"],
        "title": meta.get("TITLE", ""),
        "category": meta.get("CATEGORY", ""),
        "trophy_sets": trop_sets,
        "read_only": True,
        "iso_bytes_downloaded": source.transferred,
        "ftp_range_reads": source.requests,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", required=True)
    p.add_argument("--port", type=int, default=2121)
    p.add_argument("--iso-filename", required=True)
    p.add_argument("--output", help="New report JSON path, does not overwrite")
    args = p.parse_args()
    try:
        result = get_identity(FTPPartialISO(args.host, args.port, args.iso_filename))
        text = json.dumps(result, indent=2) + "\n"
        if args.output:
            from pathlib import Path
            with Path(args.output).open("x", encoding="utf-8") as out:
                out.write(text)
        print(text, end="")
    except (IsoError, OSError) as exc:
        p.exit(1, f"ISO metadata probe: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
