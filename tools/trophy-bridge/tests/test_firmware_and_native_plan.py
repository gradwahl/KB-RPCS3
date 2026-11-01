"""Offline tests for strict 13.20 firmware gate and collision-safe PS5 title plans."""
import importlib.util
import copy
import sys
import unittest
from pathlib import Path

DIR = Path(__file__).resolve().parents[1]
def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

p = load("safe_title_plan", "plan_native_title_registration.py")
fw = load("ps5_fw_response_parser", "run_firmware_probe.py")

PREFLIGHT = {
    "schema": "kb-rpcs3-trophy-registration-preflight/v1",
    "tile_records": {"NPEB00393": "PPSA80278"},
    "trophy_sets": [
        {"npwr": "NPWR00132_00", "game": "GTA IV", "verified_serial": "NPUB30702",
         "matching_installed_serials": ["NPUB30702"], "trophy_count": 66},
        {"npwr": "NPWR03806_00", "game": "Dead Island Riptide", "verified_serial": None,
         "matching_installed_serials": [], "trophy_count": 36}
    ],
}
ISO = {"source": "PS3_DISC_IMAGE_ISO9660", "identity_verified_from_iso": True,
       "serial": "BLES01739", "trophy_sets": ["NPWR03806_00"]}
FIRMWARE = {"schema": "kb-rpcs3-live-firmware/v1", "kernel_probe_verified": True,
            "firmware": "13.20", "sdk_hex": "0x13200006"}
STDOUT = """trophy-fw-probe: START
trophy-fw-probe: sdk=0x13200006
trophy-fw-probe: sdk_version_bcd=13.20
trophy-fw-probe: kernel_build=r228185/releases/13.20 Apr 16 2026 12:53:28
trophy-fw-probe: DONE
"""


class FirmwareAndTitlePlanTests(unittest.TestCase):
    def test_parses_real_shape_live_probe(self):
        out = fw.parse_result(STDOUT)
        self.assertEqual(out["firmware"], "13.20")
        self.assertEqual(out["sdk_hex"], "0x13200006")
        self.assertTrue(out["kernel_probe_verified"])

    def test_rejects_mismatched_firmware_data(self):
        with self.assertRaises(fw.ProbeError):
            fw.parse_result(STDOUT.replace("13.20 Apr", "13.60 Apr"))

    def test_rejects_incomplete_firmware_probe(self):
        with self.assertRaises(fw.ProbeError):
            fw.parse_result(STDOUT.replace("trophy-fw-probe: DONE", ""))

    def test_plan_all_two_game_identities_and_strict_gate(self):
        result = p.make_plan(PREFLIGHT, ISO, FIRMWARE, ["PPSA80278"])
        gta, dead = result["games"]
        self.assertEqual((gta["ps3_serial"], gta["ps5_title_id"]),
                         ("NPUB30702", "PPSA88395"))
        self.assertEqual((dead["ps3_serial"], dead["ps5_title_id"]),
                         ("BLES01739", "PPSA85381"))
        self.assertEqual(dead["identity_evidence"], "verified_ISO_PS3_GAME_PARAM_SFO_and_TROPDIR")
        self.assertFalse(result["writes_console"])
        self.assertFalse(result["creates_npbind"])
        self.assertTrue(all(not x["registration_allowed"] for x in result["games"]))
        self.assertTrue(all("UNSUPPORTED_FIRMWARE_13_20_FOR_PUBLISHED_PHU_PATCHES" in x["blockers"] for x in result["games"]))

    def test_collision_probes_next_free_id(self):
        normal = p.make_plan(PREFLIGHT, ISO, FIRMWARE, ["PPSA80278"])
        reserved = ["PPSA80278", normal["games"][0]["ps5_title_id"]]
        altered = p.make_plan(PREFLIGHT, ISO, FIRMWARE, reserved)
        self.assertEqual(altered["games"][0]["ps5_title_id"], "PPSA88396")

    def test_unverified_firmware_rejected(self):
        v = dict(FIRMWARE, kernel_probe_verified=False)
        with self.assertRaises(p.PlanError):
            p.make_plan(PREFLIGHT, ISO, v, ["PPSA80278"])

    def test_iso_and_installed_serial_conflict_rejected(self):
        v = copy.deepcopy(PREFLIGHT)
        v["trophy_sets"][1]["verified_serial"] = "NPUB30702"
        v["trophy_sets"][1]["matching_installed_serials"] = ["NPUB30702"]
        with self.assertRaises(p.PlanError):
            p.make_plan(v, ISO, FIRMWARE, [])


if __name__ == "__main__":
    unittest.main()
