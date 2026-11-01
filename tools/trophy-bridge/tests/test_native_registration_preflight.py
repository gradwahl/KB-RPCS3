"""Read-only preflight uses an in-memory FTP fake, never a PS5 write."""
import importlib.util
import json
import struct
import tempfile
import unittest
from ftplib import error_perm
from pathlib import Path

FILE = Path(__file__).resolve().parents[1] / "preflight_native_registration.py"
spec = importlib.util.spec_from_file_location("kb_preflight", FILE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class FakeFTP:
    def __init__(self, *, tile_records=b"PPSA80278 NPEB00393\n", add_collision=False):
        self.path = None
        self.commands = []
        self.records = tile_records
        game_id = m.suggested_tile_id("NPUB30702")
        if add_collision:
            self.records += (game_id + " NPEB00393\n").encode()
            self.records = self.records.replace(b"PPSA80278 NPEB00393\n", b"")
        self.file_data = {m.TILE_RECORD: self.records}
        self.entries = {
            m.TROPHY_ROOT: ["d NPWR00132_00", "d NPWR03806_00"],
            m.GAME_ROOT: ["d NPUB30702", "d NPEB00393"],
            m.GAME_ROOT + "/NPUB30702/TROPDIR": ["d NPWR00132_00"],
            m.ISO_ROOT: ["- Dead Island - Riptide.iso"],
        }
    def cwd(self, path):
        self.commands.append(("CWD", path))
        if path not in self.entries:
            raise error_perm("550 no such directory")
        self.path = path
    def retrlines(self, command, callback):
        self.commands.append(("LIST", command))
        for line in self.entries[self.path]:
            k, filename = line.split(" ", 1)
            callback(("-" if k == "-" else "d") + "rwxrwxrwx 2 0 0 140 Oct 1 12:00 " + filename)
    def retrbinary(self, command, callback):
        self.commands.append(("RETR", command))
        path = command.removeprefix("RETR ")
        if path not in self.file_data:
            raise error_perm("550 file missing")
        callback(self.file_data[path])


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "NPWR00132_00").mkdir()
        (self.root / "NPWR03806_00").mkdir()
        self.ucp = self.root / "ucp"
        (self.ucp / "NPWR00132_00").mkdir(parents=True)
        (self.ucp / "NPWR00132_00" / "trophy00.ucp").write_bytes(b"dummy")
        (self.ucp / "NPWR03806_00").mkdir(parents=True)
        (self.ucp / "NPWR03806_00" / "trophy00.ucp").write_bytes(b"dummy")
        for npwr in ("NPWR00132_00", "NPWR03806_00"):
            (self.root / npwr / "manifest.json").write_text(json.dumps({
                "schema": "kb-rpcs3-ps3-trophy-export/v1",
                "communication_id": npwr,
                "game_title": npwr,
                "groups": [],
                "trophies": [{"id": 1}],
            }))

    def test_live_style_gta_match_dead_island_unknown(self):
        ftp = FakeFTP()
        result = m.inspect(ftp, self.root, self.ucp)
        gta, dead = result["trophy_sets"]
        self.assertEqual(gta["verified_serial"], "NPUB30702")
        self.assertIsNone(gta["existing_tile"])
        self.assertTrue(gta["proposed_tile_id_only_not_installed"].startswith("PPSA8"))
        self.assertEqual(dead["matching_installed_serials"], [])
        self.assertIsNone(dead["proposed_tile_id_only_not_installed"])
        self.assertIn("NO_VERIFIED_INSTALLED_GAME_SERIAL; ISO identity not verified", dead["blockers"])
        self.assertIn("Dead Island - Riptide.iso", result["unmatched_iso_filenames"])
        self.assertTrue(all(not p[0].startswith(("STOR","DELE")) for p in ftp.commands))
        self.assertTrue(all(not item["ready_for_ps5_registration"] for item in result["trophy_sets"]))

    def test_iso_pseudo_game_is_only_a_weak_candidate(self):
        def make_sfo() -> bytes:
            name = b"Dead Island: Riptide\0"
            serial = b"XISO33006\0"
            keys = b"TITLE\0TITLE_ID\0"
            key_start = 20 + 2 * 16
            data_start = key_start + len(keys)
            index = (struct.pack("<HHIII", 0, 0x204, len(name), len(name), 0) +
                     struct.pack("<HHIII", 6, 0x204, len(serial), len(serial), len(name)))
            return (struct.pack("<4sIIII", b"\0PSF", 0x101, key_start, data_start, 2) +
                    index + keys + name + serial)

        (self.root / "NPWR03806_00" / "manifest.json").write_text(json.dumps({
            "schema": "kb-rpcs3-ps3-trophy-export/v1",
            "communication_id": "NPWR03806_00",
            "game_title": "Dead Island Riptide",
            "groups": [], "trophies": [{"id": 1}],
        }))
        ftp = FakeFTP()
        ftp.entries[m.GAME_ROOT].append("d XISO33006")
        source = m.GAME_ROOT + "/XISO33006"
        filename = "Dead Island - Riptide.iso"
        ftp.entries[m.ISO_ROOT] = ["- " + filename]
        ftp.file_data[source + "/PARAM.SFO"] = make_sfo()
        ftp.file_data[source + "/RPCS3_ISO_LINK.txt"] = (
            "RPCS3_XMB_ISO_V1\n/data/rpcs3/PS3ISO/" + filename + "\n"
        ).encode()
        data = m.inspect(ftp, self.root, self.ucp)
        target = data["trophy_sets"][1]
        self.assertEqual(target["possible_iso_launcher_caches_not_verified"][0]["cache_serial"], "XISO33006")
        self.assertIsNone(target["verified_serial"])
        self.assertFalse(target["ready_for_ps5_registration"])

    def test_collision_detected(self):
        result = m.inspect(FakeFTP(add_collision=True), self.root, self.ucp)
        gta = result["trophy_sets"][0]
        self.assertEqual(gta["collision_with_serial"], "NPEB00393")
        self.assertIn("CANDIDATE_TILE_ID_COLLISION", gta["blockers"])

    def test_malformed_or_duplicate_tile_mapping_rejected(self):
        for text in (b"PPSA80001 NPEB00393\nPPSA80001 NPEB00001\n",
                     b"PPSA80001 NPEB00393\nPPSA80002 NPEB00393\n",
                     b"bad-data"):
            with self.subTest(text=text):
                with self.assertRaises(m.PreflightError):
                    m.parse_tiles(text)

    def test_legacy_format_supported(self):
        self.assertEqual(m.parse_tiles(b"NPEB00393 PPSA80278\n"), {"NPEB00393":"PPSA80278"})

    def test_manifest_mismatch_rejected(self):
        (self.root / "NPWR00132_00" / "manifest.json").write_text(json.dumps({
            "schema": "kb-rpcs3-ps3-trophy-export/v1",
            "communication_id": "NPWR99999_00",
        }))
        with self.assertRaises(m.PreflightError):
            m.inspect(FakeFTP(), self.root, self.ucp)


if __name__ == "__main__":
    unittest.main()
