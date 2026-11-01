"""Synthetic UDS/PS5 trophy linking tests. No real console files involved."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("paired_ps5_uds", SCRIPTS / "build_paired_uds_prototype.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class PairedUDSTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.icons = self.folder / "icons"
        self.icons.mkdir()
        (self.icons / "ICON0.PNG").write_bytes(b"\x89PNG\r\n\x1a\nplaceholder")
        self.manifest = self.folder / "manifest.json"
        self.base = {
            "schema": "kb-rpcs3-ps3-trophy-export/v1",
            "communication_id": "NPWR01234_00",
            "game_title": "Dummy",
            "groups": [],
            "trophies": [
                {"id": 0, "grade": "platinum", "name": "Master", "description": "",
                 "platinum_link_id": None, "hidden": False},
                {"id": 1, "grade": "bronze", "name": "One", "description": "",
                 "platinum_link_id": 0, "hidden": False},
                {"id": 2, "grade": "silver", "name": "Two", "description": "",
                 "platinum_link_id": 0, "hidden": True},
            ],
        }
        self.save()

    def save(self):
        self.manifest.write_text(json.dumps(self.base), encoding="utf-8")

    def test_builds_two_roundtrippable_ucps_with_correct_crosslinks(self):
        trophy, uds, links = m.build_pair(self.manifest)
        self.assertEqual(links["trophies"], 3)
        self.assertEqual(links["stat_definitions"], 2)
        self.assertTrue(links["ids_linked"])
        self.assertTrue(m.inspect_ucp(trophy)["sha1_valid"])
        self.assertTrue(m.inspect_ucp(uds)["sha1_valid"])

    def test_platinum_has_no_unlock_rule(self):
        entries = m.build_trophy_entries(self.manifest, experimental_uds_conditions=True)
        conf = json.loads(entries["tropconf.json"])
        self.assertNotIn("unlockCondition", conf["trophies"][0])
        self.assertEqual(conf["trophies"][1]["unlockCondition"]["udsStatId"], "1001")
        uds = m.uds_files(self.base)
        stats = json.loads(uds["stats_definition.json"])
        self.assertEqual({item["statId"] for item in stats["statDefinitionArray"]}, {1001,1002})

    def test_missing_stat_makes_validation_fail(self):
        entries = m.build_trophy_entries(self.manifest, experimental_uds_conditions=True)
        uds = m.uds_files(self.base)
        stats = json.loads(uds["stats_definition.json"])
        stats["statDefinitionArray"].pop()
        uds["stats_definition.json"] = json.dumps(stats).encode()
        with self.assertRaisesRegex(m.UcpFormatError, "Unmatched"):
            m.validate_links(entries, uds)

    def test_bad_trophy_id_rejected(self):
        self.base["trophies"][2]["id"] = 1
        self.save()
        with self.assertRaises(m.UcpFormatError):
            m.build_pair(self.manifest)

    def test_bad_comm_id_rejected(self):
        self.base["communication_id"] = "FAKE000000_00"
        self.save()
        with self.assertRaises(m.UcpFormatError):
            m.build_pair(self.manifest)


if __name__ == "__main__":
    unittest.main()
