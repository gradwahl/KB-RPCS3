"""Offline ELF fingerprint tests; no Sony library bytes in repository."""
import importlib.util
import struct
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "fingerprint_native_trophy_runtime.py"
spec = importlib.util.spec_from_file_location("native_library_fingerprint", SRC)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def synthetic_sprx() -> bytes:
    raw = bytearray(256)
    raw[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<HH", raw, 16, 0xFE18, 62)
    struct.pack_into("<Q", raw, 32, 64)
    struct.pack_into("<HH", raw, 54, 56, 2)
    struct.pack_into("<IIQQQQQQ", raw, 64, 1, 4, 180, 0, 0, 32, 32, 16)
    struct.pack_into("<IIQQQQQQ", raw, 120, 2, 6, 212, 0, 0, 32, 32, 16)
    return bytes(raw)


class FakeFTP:
    def __init__(self):
        self.bytes = synthetic_sprx()
        self.ops = []
    def cwd(self, path):
        self.ops.append(("CWD", path))
    def retrlines(self, command, cb):
        self.ops.append(("LIST", command))
        for name in m.LIBRARIES:
            cb(f"-rwxrwxrwx 1 0 0 {len(self.bytes)} Jan 01 00:00 {name}")
    def retrbinary(self, command, cb, blocksize=None):
        self.ops.append(("RETR", command))
        cb(self.bytes)


class TrophyRuntimeTests(unittest.TestCase):
    def test_reads_four_only_and_fingerprints(self):
        result = m.inventory(FakeFTP(), {
            "schema":"kb-rpcs3-live-firmware/v1",
            "firmware":"13.20",
            "sdk_hex":"0x13200006",
            "kernel_probe_verified": True
        })
        self.assertEqual(len(result["libraries"]), 4)
        self.assertEqual(result["libraries"][0]["load_segment_count"], 1)
        self.assertFalse(result["trophy_service_patched"])
        self.assertFalse(result["trophy_registration_api_called"])

    def test_rejects_bogus_elf_type(self):
        data=bytearray(synthetic_sprx())
        data[16:18]=b"\x02\x00"
        with self.assertRaises(m.FingerprintError):
            m.inspect_elf(bytes(data))

    def test_rejects_no_dynamic(self):
        data=bytearray(synthetic_sprx())
        struct.pack_into("<I", data, 120, 1)
        with self.assertRaises(m.FingerprintError):
            m.inspect_elf(bytes(data))

    def test_rejects_unverified_firmware(self):
        with self.assertRaises(m.FingerprintError):
            m.inventory(FakeFTP(), {"schema":"kb-rpcs3-live-firmware/v1","kernel_probe_verified":False})


if __name__ == "__main__":
    unittest.main()
