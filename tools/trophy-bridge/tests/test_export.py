"""Offline tests: fake RPCS3 fixtures, never console or real trophy files."""
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "export_rpc3_trophies.py"
spec = importlib.util.spec_from_file_location("rpc3_trophy_bridge", MODULE_PATH)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

XML = """<?xml version="1.0" encoding="utf-8"?>
<trophyconf>
  <npcommid>NPWR01234_00</npcommid>
  <title-name>Sample PS3 Game</title-name>
  <title-detail>Local test fixture</title-detail>
  <trophy id="0" ttype="B" hid="no" pid="-1">
    <name>First Trophy</name><detail>Finish a task</detail>
  </trophy>
  <trophy id="1" ttype="P" hid="yes" pid="-1">
    <name>Platinum</name><detail>Get everything</detail>
  </trophy>
</trophyconf>
"""


def make_tropusr(*, corrupt=False, missing_state=False):
    # Mirrors RPCS3's big-endian structs: header 0x30; table headers 0x20;
    # type-6 rows 0x70 bytes, payload size 0x60.
    header = struct.pack(">IIII", bridge.MAGIC, 0x10000, 1, 0) + bytes(32)
    offset = 0x30 + 0x20
    table_header = struct.pack(">IIIIQQ", 6, 0x60, 1, 1 if missing_state else 2, offset, 0)
    def entry(index, state, timestamp):
        prefix = struct.pack(">IIIIIIIIQQ", 6, 0x60, index, 0, index, state, 0, 0, timestamp, timestamp)
        return prefix + bytes(64)
    data = header + table_header + entry(0, 1, 63850000000000000)
    if not missing_state:
        data += entry(1, 0, 0)
    return data[:-2] if corrupt else data


class TrophyBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.folder = self.base / "source" / "NPWR01234_00"
        self.folder.mkdir(parents=True)
        (self.folder / "TROPCONF.SFM").write_text(XML, encoding="utf-8")
        (self.folder / "TROPUSR.DAT").write_bytes(make_tropusr())
        (self.folder / "ICON0.PNG").write_bytes(b"png placeholder test fixture")

    def test_complete_export_tracks_unlocks_and_icons(self):
        result = bridge.export(self.base / "source", self.base / "output")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["unlocked"], 1)
        output = self.base / "output" / "NPWR01234_00"
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["communication_id"], "NPWR01234_00")
        self.assertEqual(manifest["registration_status"], "NOT_REGISTERED_WITH_PS5")
        self.assertTrue(manifest["trophies"][0]["unlocked"])
        self.assertFalse(manifest["trophies"][1]["unlocked"])
        self.assertEqual(manifest["trophies"][0]["ps3_tick"], 63850000000000000)
        self.assertTrue(manifest["trophies"][1]["hidden"])
        self.assertEqual(manifest["trophies"][1]["grade"], "platinum")
        self.assertTrue((output / "icons" / "ICON0.PNG").exists())

    def test_dry_run_makes_no_files(self):
        result = bridge.export(self.base / "source", self.base / "output", dry_run=True)
        self.assertEqual(result[0]["trophies"], 2)
        self.assertFalse((self.base / "output").exists())

    def test_no_user_file_keeps_unknown_not_locked(self):
        (self.folder / "TROPUSR.DAT").unlink()
        bridge.export(self.base / "source", self.base / "output")
        manifest = json.loads((self.base / "output" / "NPWR01234_00" / "manifest.json").read_text())
        self.assertFalse(manifest["has_unlock_database"])
        self.assertIsNone(manifest["trophies"][0]["unlocked"])

    def test_malformed_input_prevents_output(self):
        (self.folder / "TROPUSR.DAT").write_bytes(make_tropusr(corrupt=True))
        with self.assertRaises(bridge.TrophyFormatError):
            bridge.export(self.base / "source", self.base / "output")
        self.assertFalse((self.base / "output").exists())

    def test_mismatch_prevents_output(self):
        (self.folder / "TROPUSR.DAT").write_bytes(make_tropusr(missing_state=True))
        with self.assertRaisesRegex(bridge.TrophyFormatError, "do not match"):
            bridge.export(self.base / "source", self.base / "output")

    def test_no_icons_does_not_reference_absent_files(self):
        bridge.export(self.base / "source", self.base / "output", no_icons=True)
        output = self.base / "output" / "NPWR01234_00"
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        self.assertIsNone(manifest["trophies"][0]["icon"])
        self.assertFalse((output / "icons").exists())

    def test_existing_export_never_overwritten(self):
        bridge.export(self.base / "source", self.base / "output")
        with self.assertRaises(bridge.TrophyFormatError):
            bridge.export(self.base / "source", self.base / "output")


if __name__ == "__main__":
    unittest.main()
