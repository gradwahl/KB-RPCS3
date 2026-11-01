"""Synthetic npbind fixtures only. Never include copied game secrets in tests."""
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "inspect_existing_npbind.py"
spec = importlib.util.spec_from_file_location("readonly_npbind", PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def fake_npbind(npwr="NPWR12345_00", *, bad_size=False, invalid_tag=False):
    blob = bytearray(0x80)
    entries = [
        (0x10, npwr.encode("ascii")),
        (0x11, b"x" * 12),
        (0x12, b"placeholder" * 16),
        (0x13, b"w" * 16),
    ]
    for tag, body in entries:
        blob.extend(struct.pack(">HH", tag, len(body)))
        blob.extend(body)
    blob.extend(struct.pack(">HH", 0, 0))
    blob.extend(bytes(8))
    struct.pack_into(">IIII", blob, 0, m.NPBIND_MAGIC, 1, 0, len(blob) + (1 if bad_size else 0))
    if invalid_tag:
        struct.pack_into(">H", blob, 0x82, 0xFFFF)
    return bytes(blob)


class FakeFTP:
    def __init__(self, raw, *, title_id="PPSA12345", param_title=None):
        base = f"/data/etaHEN/games/{title_id}/sce_sys"
        self.urls = {
            base + "/param.json": json.dumps({"titleId": param_title or title_id}).encode("utf-8"),
            base + "/trophy2/npbind.dat": raw,
        }
        self.commands = []

    def retrbinary(self, command, callback):
        self.commands.append(command)
        callback(self.urls[command.removeprefix("RETR ")])


class BindingTests(unittest.TestCase):
    def test_valid_npwr_extract_without_secrets(self):
        result = m.inspect_npbind(fake_npbind())
        self.assertEqual(result["npwr"], "NPWR12345_00")
        self.assertFalse(result["reusable_as_new_game_binding"])
        self.assertNotIn("placeholder", json.dumps(result))
        self.assertEqual([item["tag"] for item in result["tlv_layout"]], [16,17,18,19])

    def test_bad_length_rejected(self):
        with self.assertRaisesRegex(m.BindingFormatError, "declared size"):
            m.inspect_npbind(fake_npbind(bad_size=True))

    def test_bad_tlv_rejected(self):
        with self.assertRaisesRegex(m.BindingFormatError, "TLV length"):
            m.inspect_npbind(fake_npbind(invalid_tag=True))

    def test_not_npwr_rejected(self):
        with self.assertRaisesRegex(m.BindingFormatError, "Invalid NPWR"):
            m.inspect_npbind(fake_npbind(npwr="FOOB12345_00"))

    def test_missing_magic_rejected(self):
        blob = bytearray(fake_npbind())
        blob[0] = 0
        with self.assertRaisesRegex(m.BindingFormatError, "magic"):
            m.inspect_npbind(bytes(blob))

    def test_ftp_inspection_read_only(self):
        ftp = FakeFTP(fake_npbind())
        result = m.inspect_existing_title(ftp, "PPSA12345")
        self.assertEqual(result["npwr"], "NPWR12345_00")
        self.assertEqual(len(ftp.commands), 2)
        self.assertTrue(all(command.startswith("RETR ") for command in ftp.commands))
        self.assertFalse(result["supports_synthetic_ps3_trophy_registration"])

    def test_mismatched_title_rejected(self):
        ftp = FakeFTP(fake_npbind(), title_id="PPSA10000", param_title="PPSA12345")
        with self.assertRaises(m.BindingFormatError):
            m.inspect_existing_title(ftp, "PPSA10000")


if __name__ == "__main__":
    unittest.main()
