#!/usr/bin/env python3
"""Read-only version fingerprint of native PS5 Trophy 2 runtime libraries.

Checks ELF structure and computes SHA-256 of bounded library bytes in memory.
Does not load libraries into any process, call trophy APIs, export protected
binding material, patch services, install titles or access trophy profiles.
This confirms library PRESENCE only, not an authorized registration method.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from ftplib import FTP
from pathlib import Path

SYSTEM_LIB = "/system/common/lib"
LIBRARIES = (
    "libSceNpTrophy2.sprx",
    "libSceNpTrophy.sprx",
    "libSceNpManager.sprx",
    "libSceIpmi.sprx",
)
MAX_BYTES = 4 * 1024 * 1024


class FingerprintError(ValueError):
    pass


def inspect_elf(raw: bytes) -> dict:
    if len(raw) < 64 or raw[:4] != b"\x7fELF" or raw[4:6] != b"\x02\x01":
        raise FingerprintError("Not an x86-64 little endian ELF")
    obj_type, machine = struct.unpack_from("<HH", raw, 16)
    ph_offset = struct.unpack_from("<Q", raw, 32)[0]
    ph_size, ph_count = struct.unpack_from("<HH", raw, 54)
    if (obj_type != 0xFE18 or machine != 62 or ph_size != 56 or
            not 1 <= ph_count <= 96 or
            ph_offset + ph_count * ph_size > len(raw)):
        raise FingerprintError("Unexpected PS5 library ELF structure")
    seen = []
    dynamic = False
    for i in range(ph_count):
        ph_type, _, offset, _, _, size, _, _ = struct.unpack_from(
            "<IIQQQQQQ", raw, ph_offset + i * ph_size
        )
        if offset + size > len(raw):
            raise FingerprintError("Malformed ELF program segment")
        if ph_type == 2:
            dynamic = True
        if ph_type == 1:
            seen.append(size)
    if not seen or not dynamic:
        raise FingerprintError("No LOAD/DYNAMIC program headers")
    return {
        "format": "PS5_SPRX_ELF64",
        "elf_type": "0xFE18",
        "load_segment_count": len(seen),
        "has_dynamic_segment": dynamic,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def inventory(ftp: FTP, firmware_report: dict) -> dict:
    if (firmware_report.get("schema") != "kb-rpcs3-live-firmware/v1" or
            not firmware_report.get("kernel_probe_verified")):
        raise FingerprintError("Verified live PS5 firmware report required")
    ftp.cwd(SYSTEM_LIB)
    rows = []
    ftp.retrlines("LIST", rows.append)
    sizes = {}
    for line in rows:
        parts = line.split(maxsplit=8)
        if len(parts) == 9 and parts[0].startswith("-") and parts[8] in LIBRARIES:
            sizes[parts[8]] = int(parts[4])
    if set(sizes) != set(LIBRARIES):
        raise FingerprintError("Native trophy library missing from PS5 filesystem")
    report = []
    for name in LIBRARIES:
        if not 64 <= sizes[name] <= MAX_BYTES:
            raise FingerprintError(f"Unexpected trophy library size: {name}")
        data = bytearray()
        def cb(chunk):
            if len(data) + len(chunk) > MAX_BYTES:
                raise FingerprintError("Library transfer exceeds bound")
            data.extend(chunk)
        ftp.retrbinary(f"RETR {SYSTEM_LIB}/{name}", cb, blocksize=16384)
        if len(data) != sizes[name]:
            raise FingerprintError(f"Library changed during read: {name}")
        record = inspect_elf(data)
        record["name"] = name
        report.append(record)
    return {
        "schema": "kb-rpcs3-ps5-trophy-runtime-fingerprint/v1",
        "firmware": firmware_report["firmware"],
        "kernel_sdk_version": firmware_report["sdk_hex"],
        "source": "read_only_console_native_library_ELF_fingerprints",
        "libraries": report,
        "firmware_offsets_confirmed": False,
        "trophy_registration_api_called": False,
        "trophy_service_patched": False,
        "binding_generated": False,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=2121)
    ap.add_argument("--firmware", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    a = ap.parse_args()
    if a.report.exists():
        ap.error("Report exists; refusing to overwrite")
    try:
        verified = json.loads(a.firmware.read_text(encoding="utf-8"))
        with FTP() as ftp:
            ftp.connect(a.host, a.port, timeout=12)
            ftp.login()
            report = inventory(ftp, verified)
        result = json.dumps(report, indent=2) + "\n"
        with a.report.open("x", encoding="utf-8") as stream:
            stream.write(result)
        print(result, end="")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        ap.exit(1, f"Trophy runtime inventory refused: {exc}\n")


if __name__ == "__main__":
    main()
