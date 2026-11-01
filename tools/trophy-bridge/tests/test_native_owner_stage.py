"""Host-only fixtures for signed native-owner probe title package staging."""
import copy
import hashlib
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "stage_native_owner_probes.py"
spec = importlib.util.spec_from_file_location("owner_stage", SCRIPT)
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

PLAN = {
    "schema": "kb-rpcs3-safe-native-trophy-plan/v1",
    "registration_mode": "DISABLED_OFFLINE_PLANNING_ONLY",
    "console_firmware": "13.20",
    "writes_console": False,
    "creates_npbind": False,
    "used_ps5_title_ids_seen": ["PPSA80278"],
    "games": [
        {
            "ps5_title_id": "PPSA88395",
            "ps3_serial": "NPUB30702",
            "npwr": "NPWR00132_00",
            "ps3_game": "GTA IV",
            "registration_allowed": False,
            "ps5_title_status": "PLAN_ONLY_NOT_INSTALLED",
            "ps5_trophy_menu_ready": False,
            "identity_evidence": "installed_PS3_TROPDIR",
        },
        {
            "ps5_title_id": "PPSA85381",
            "ps3_serial": "BLES01739",
            "npwr": "NPWR03806_00",
            "ps3_game": "Dead Island Riptide",
            "registration_allowed": False,
            "ps5_title_status": "PLAN_ONLY_NOT_INSTALLED",
            "ps5_trophy_menu_ready": False,
            "identity_evidence": "verified_ISO_PS3_GAME_PARAM_SFO_and_TROPDIR",
        },
    ],
}


class OwnerStageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.built = self.root / "built"
        (self.built / "sce_module").mkdir(parents=True)
        (self.built / "eboot.bin").write_bytes(p.SIGNED_SELF_MAGIC + bytes(2048))
        (self.built / "sce_module/libc.prx").write_bytes(b"FAKE-DUMMY-LIBC" + bytes(2048))
        self.output = self.root / "staged"

    def test_stages_both_signed_native_owners_with_separate_identity(self):
        result = p.stage(copy.deepcopy(PLAN), self.built, self.output)
        self.assertEqual(len(result["apps"]), 2)
        self.assertEqual(result["status"], "HOST_ONLY_UNDEPLOYED_NO_TROPHY_REGISTRATION")
        self.assertFalse(result["ps5_files_changed"])
        for game in PLAN["games"]:
            tid = game["ps5_title_id"]
            folder = self.output / tid
            self.assertTrue((folder / "eboot.bin").exists())
            self.assertFalse((folder / "sce_sys/trophy2").exists())
            self.assertFalse((folder / "sce_sys/uds").exists())
            self.assertFalse((folder / "rpcs3").exists())
            self.assertEqual(
                (folder / "native-owner.txt").read_text(),
                f"{tid} {game['npwr']} {game['ps3_serial']}\n",
            )
            param = json.loads((folder / "sce_sys/param.json").read_text())
            self.assertEqual(param["titleId"], tid)
            self.assertEqual(len(param["contentId"]), 36)
            for name, dims in (("icon0.png", (512,512)), ("pic0.png", (3840,2160))):
                raw = (folder / "sce_sys" / name).read_bytes()
                self.assertTrue(raw.startswith(b"\x89PNG\r\n\x1a\n"))
                self.assertEqual(struct.unpack_from(">II", raw, 16), dims)
            records = next(x for x in result["apps"] if x["title_id"] == tid)
            for rel, sha in records["file_sha256"].items():
                self.assertEqual(
                    hashlib.sha256((folder / rel).read_bytes()).hexdigest(), sha
                )

    def test_refuses_second_run_over_same_output(self):
        p.stage(PLAN, self.built, self.output)
        with self.assertRaises(p.StageError):
            p.stage(PLAN, self.built, self.output)

    def test_rejects_wrong_firmware_or_registration_permissions(self):
        bad = copy.deepcopy(PLAN)
        bad["console_firmware"] = "12.70"
        with self.assertRaises(p.StageError):
            p.stage(bad, self.built, self.output)
        bad = copy.deepcopy(PLAN)
        bad["games"][0]["registration_allowed"] = True
        with self.assertRaises(p.StageError):
            p.stage(bad, self.built, self.output)

    def test_rejects_title_collisions(self):
        bad = copy.deepcopy(PLAN)
        bad["games"][1]["ps5_title_id"] = bad["games"][0]["ps5_title_id"]
        with self.assertRaises(p.StageError):
            p.stage(bad, self.built, self.output)
        bad = copy.deepcopy(PLAN)
        bad["used_ps5_title_ids_seen"] += [bad["games"][0]["ps5_title_id"]]
        with self.assertRaises(p.StageError):
            p.stage(bad, self.built, self.output)

    def test_rejects_non_self_binary(self):
        (self.built / "eboot.bin").write_bytes(b"\x7fELF" + bytes(2048))
        with self.assertRaisesRegex(p.StageError, "SELF"):
            p.stage(PLAN, self.built, self.output)

    def test_rejects_unverified_game_identity(self):
        bad = copy.deepcopy(PLAN)
        bad["games"][1]["identity_evidence"] = "filename_guess"
        with self.assertRaises(p.StageError):
            p.stage(bad, self.built, self.output)


if __name__ == "__main__":
    unittest.main()
