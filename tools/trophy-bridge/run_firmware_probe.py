#!/usr/bin/env python3
"""Execute ONLY the reviewed read-only firmware probe ELF through PS5 ELF loader.

The ELF calls sysctl to print PS5 SDK/kernel version; it does not write to the
console, touch the PS5 trophy service, or stop processes. Save the result on PC.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import socket
from pathlib import Path

SDK_RE = re.compile(r"^trophy-fw-probe: sdk=0x([0-9a-f]{8})$", re.M)
BUILD_RE = re.compile(r"^trophy-fw-probe: kernel_build=([^\r\n]+)$", re.M)
VERSION_RE = re.compile(r"^trophy-fw-probe: sdk_version_bcd=([0-9a-f]{2})\.([0-9a-f]{2})$", re.M)
SENTINEL = "trophy-fw-probe: DONE"


class ProbeError(RuntimeError):
    pass


def parse_result(raw: str) -> dict:
    sdk = SDK_RE.findall(raw)
    build = BUILD_RE.findall(raw)
    versions = VERSION_RE.findall(raw)
    if SENTINEL not in raw.splitlines() or len(sdk) != 1 or len(build) != 1 or len(versions) != 1:
        raise ProbeError("Incomplete or invalid console firmware probe response")
    major, minor = versions[0]
    sdk_hex = sdk[0]
    if sdk_hex[:4] != major + minor:
        raise ProbeError("Kernel SDK value does not match BCD version")
    version = f"{major}.{minor}"
    if f"/{version}" not in build[0]:
        raise ProbeError("Kernel build reports a different firmware")
    return {
        "schema": "kb-rpcs3-live-firmware/v1",
        "source": "live_ps5_read_only_sysctl_payload",
        "firmware": version,
        "sdk_hex": "0x" + sdk_hex,
        "kernel_build": build[0],
        "kernel_probe_verified": True,
        "trophy_registration_performed": False,
    }


def run(host: str, port: int, elf: Path) -> dict:
    data = elf.read_bytes()
    if len(data) < 1000 or len(data) > 1024 * 1024 or data[:4] != b"\x7fELF":
        raise ProbeError("Expected a small, compiled firmware probe ELF")
    if b"trophy-fw-probe: START" not in data or b"trophy-fw-probe: DONE" not in data:
        raise ProbeError("Incorrect firmware-probe ELF: missing markers")
    with socket.create_connection((host, port), timeout=10) as sock:
        sock.settimeout(12)
        sock.sendall(data)
        sock.shutdown(socket.SHUT_WR)
        buffer = bytearray()
        while SENTINEL.encode() not in buffer and len(buffer) < 32 * 1024:
            block = sock.recv(2048)
            if not block:
                break
            buffer.extend(block)
    parsed = parse_result(buffer.decode("ascii", "replace"))
    parsed["elf_sha256"] = hashlib.sha256(data).hexdigest()
    return parsed


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", required=True)
    p.add_argument("--port", type=int, default=9021)
    p.add_argument("--elf", required=True, type=Path)
    p.add_argument("--output", type=Path, help="New PC-side report path")
    args = p.parse_args()
    if args.output and args.output.exists():
        p.error("Report already exists; refusing to overwrite")
    try:
        obj = run(args.host, args.port, args.elf)
        result = json.dumps(obj, indent=2) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as out:
                out.write(result)
        print(result, end="")
    except (ProbeError, OSError) as exc:
        p.exit(1, f"Firmware probe: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
