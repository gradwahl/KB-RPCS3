"""Synthetic fixtures for ISO9660 range parsing, never real PS3 game content."""
import importlib.util
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("iso_metadata_only", SCRIPTS / "read_ps3_iso_identity_ftp.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def make_sfo():
    values = [("TITLE_ID", b"BLES01739\0"), ("TITLE", b"Dead Island: Riptide\0"), ("CATEGORY", b"DG\0")]
    keyblob = b"".join(k.encode() + b"\0" for k,_ in values)
    valueblob = b"".join(v for _,v in values)
    keyoff = 20 + len(values) * 16
    dataoff = keyoff + len(keyblob)
    rows = b""
    ki = vi = 0
    for k,v in values:
        rows += struct.pack("<HHIII", ki, 0x0204, len(v), len(v), vi)
        ki += len(k) + 1
        vi += len(v)
    return struct.pack("<4sIIII", b"\0PSF", 0x101, keyoff, dataoff, len(values)) + rows + keyblob + valueblob


def dir_entry(name: bytes, sector: int, size: int, is_dir: bool) -> bytes:
    length = 33 + len(name) + (0 if len(name) % 2 == 1 else 1)
    data = bytearray(length)
    data[0] = length
    struct.pack_into("<I", data, 2, sector)
    struct.pack_into(">I", data, 6, sector)
    struct.pack_into("<I", data, 10, size)
    struct.pack_into(">I", data, 14, size)
    data[25] = 2 if is_dir else 0
    struct.pack_into("<H", data, 28, 1)
    data[30:32] = (1).to_bytes(2, "big")
    data[32] = len(name)
    data[33:33 + len(name)] = name
    return bytes(data)


def fixture_iso():
    b = bytearray(100 * m.SECTOR)
    pvd = 16 * m.SECTOR
    b[pvd] = 1
    b[pvd+1:pvd+6] = b"CD001"
    root = dir_entry(b"\0", 20, 2048, True)
    b[pvd+156:pvd+156+len(root)] = root
    lists = {
        20: [dir_entry(b"\0", 20, 2048, True), dir_entry(b"PS3_GAME", 21, 2048, True)],
        21: [dir_entry(b"\0", 21, 2048, True),
             dir_entry(b"PARAM.SFO;1", 31, len(make_sfo()), False),
             dir_entry(b"TROPDIR", 22, 2048, True)],
        22: [dir_entry(b"\0", 22, 2048, True),
             dir_entry(b"NPWR03806_00", 23, 2048, True)],
    }
    for sector, items in lists.items():
        encoded = b"".join(items)
        b[sector * m.SECTOR:sector * m.SECTOR + len(encoded)] = encoded
    sf = make_sfo()
    b[31 * m.SECTOR:31 * m.SECTOR + len(sf)] = sf
    return bytes(b)


class BufferReader:
    def __init__(self, data):
        self.data = data
        self.requests = 0
        self.transferred = 0
    def read(self, offset, n):
        self.requests += 1
        self.transferred += n
        return self.data[offset:offset+n]


class IsoTests(unittest.TestCase):
    def test_proves_title_and_trophy_from_iso(self):
        reader = BufferReader(fixture_iso())
        result = m.get_identity(reader)
        self.assertEqual(result["serial"], "BLES01739")
        self.assertEqual(result["trophy_sets"], ["NPWR03806_00"])
        self.assertEqual(result["title"], "Dead Island: Riptide")
        self.assertEqual(result["ftp_range_reads"], 6)
        self.assertTrue(result["identity_verified_from_iso"])

    def test_reject_noniso(self):
        with self.assertRaises(m.IsoError):
            m.get_identity(BufferReader(bytes(100 * m.SECTOR)))

    def test_reject_bad_serial(self):
        bad = fixture_iso().replace(b"BLES01739", b"BAD!01739")
        with self.assertRaises(m.IsoError):
            m.get_identity(BufferReader(bad))

    def test_reject_invalid_filename(self):
        for name in ("../example.iso", "dir\\game.iso", "", "abc.txt"):
            with self.subTest(name=name), self.assertRaises(m.IsoError):
                m.FTPPartialISO("127.0.0.1", 2121, name)


if __name__ == "__main__":
    unittest.main()
