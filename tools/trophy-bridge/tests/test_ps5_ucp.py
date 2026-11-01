"""Offline UCP tests with synthetic data (no console files, no PSN requests)."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "build_ps5_ucp_prototype.py"
spec = importlib.util.spec_from_file_location("ps5_ucp_prototype", MODULE)
ucp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ucp)

DUMMY_PNG = b"\x89PNG\r\n\x1a\n" + b"dummy fixture for format testing"


class UcpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "icons").mkdir()
        for icon in ("ICON0.PNG", "TROP000.PNG", "TROP001.PNG", "GR001.PNG"):
            (self.root / "icons" / icon).write_bytes(DUMMY_PNG)
        self.manifest = {
            "schema": "kb-rpcs3-ps3-trophy-export/v1",
            "communication_id": "NPWR01234_00",
            "game_title": "Dummy local test",
            "groups": [{"id": 1, "name": "DLC group", "icon": "icons/GR001.PNG"}],
            "trophies": [
                {"id": 0, "grade": "platinum", "hidden": False,
                 "platinum_link_id": None, "group_id": None,
                 "name": "All done", "description": "Everything",
                 "icon": "icons/TROP000.PNG"},
                {"id": 1, "grade": "bronze", "hidden": True,
                 "platinum_link_id": 0, "group_id": 1,
                 "name": "First", "description": "Completed",
                 "icon": "icons/TROP001.PNG"},
            ],
        }
        self.jsonpath = self.root / "manifest.json"
        self.jsonpath.write_text(json.dumps(self.manifest), encoding="utf-8")

    @staticmethod
    def json_entry(raw: bytes, target: str) -> dict:
        import struct
        for i in range(struct.unpack_from(">I", raw, 0x10)[0]):
            pos = 0x60 + 0x40 * i
            name = raw[pos:pos+32].partition(b"\0")[0].decode("ascii")
            if name == target:
                offset, size = struct.unpack_from(">QQ", raw, pos+32)
                return json.loads(raw[offset:offset+size])
        raise AssertionError(f"Entry missing: {target}")

    def test_ucp_round_trip_json_and_icons(self):
        entries = ucp.build_trophy_entries(self.jsonpath)
        result = ucp.pack_ucp(entries)
        info = ucp.inspect_ucp(result)
        self.assertEqual(info["count"], 6)
        self.assertIn("gr0001_en-US.png", info["files"])
        self.assertIn("tropconf.json", info["files"])
        conf = self.json_entry(result, "tropconf.json")
        meta = self.json_entry(result, "tropmeta_en-US.json")
        self.assertEqual(conf["trophies"][1]["groupId"], "0001")
        self.assertEqual(conf["trophies"][1]["platinumTrophyId"], "0000")
        self.assertEqual(conf["trophies"][1]["grade"], "B")
        self.assertTrue(conf["trophies"][1]["hidden"])
        self.assertEqual(meta["metadata"]["titleMetadata"]["name"], "Dummy local test")
        self.assertEqual(len(meta["metadata"]["trophyMetadata"]), 2)

    def test_corruption_rejected(self):
        raw = bytearray(ucp.pack_ucp(ucp.build_trophy_entries(self.jsonpath)))
        raw[-1] ^= 1
        with self.assertRaisesRegex(ucp.UcpFormatError, "SHA1"):
            ucp.inspect_ucp(bytes(raw))

    def test_reject_path_traversal(self):
        self.manifest["trophies"][0]["icon"] = "../private.png"
        self.jsonpath.write_text(json.dumps(self.manifest))
        with self.assertRaises(ucp.UcpFormatError):
            ucp.build_trophy_entries(self.jsonpath)

    def test_reject_unknown_platinum_id(self):
        self.manifest["trophies"][1]["platinum_link_id"] = 99
        self.jsonpath.write_text(json.dumps(self.manifest))
        with self.assertRaisesRegex(ucp.UcpFormatError, "Unknown platinum"):
            ucp.build_trophy_entries(self.jsonpath)

    def test_reject_duplicate_id(self):
        self.manifest["trophies"][1]["id"] = 0
        self.jsonpath.write_text(json.dumps(self.manifest))
        with self.assertRaises(ucp.UcpFormatError):
            ucp.build_trophy_entries(self.jsonpath)


if __name__ == "__main__":
    unittest.main()
