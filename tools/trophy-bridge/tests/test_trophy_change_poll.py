"""Offline-only unlock delta checks: no trophy writes and no PSN API calls."""
import importlib.util
import sys
import unittest
from pathlib import Path

D = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(D))
spec = importlib.util.spec_from_file_location("trophy_change_poll", D / "poll_ps3_trophy_changes.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

BASE = {
    "schema": "kb-rpcs3-ps3-trophy-export/v1",
    "communication_id": "NPWR12345_00",
    "game_title": "Test PS3 Game",
    "has_unlock_database": True,
    "trophies": [
        {"id": 0, "name": "Bronze", "grade": "bronze", "unlocked": False},
        {"id": 1, "name": "Gold", "grade": "gold", "unlocked": True},
    ],
}
STATES = {
    0: {"unlocked": True, "ps3_tick": 63790000123456789},
    1: {"unlocked": True, "ps3_tick": 63790000123456788},
}
PLAN = {
    "schema": "kb-rpcs3-safe-native-trophy-plan/v1",
    "games": [{"npwr": "NPWR12345_00", "ps5_title_id": "PPSA81234", "registration_allowed": False}],
}


class TrophyChangeTests(unittest.TestCase):
    def test_new_unlock_event_offline(self):
        obj = p.compare_progress(BASE, STATES, PLAN)
        self.assertEqual(len(obj["new_unlock_events"]), 1)
        self.assertEqual(obj["new_unlock_events"][0]["ps3_trophy_id"], 0)
        self.assertEqual(obj["new_unlock_events"][0]["proposed_ps5_title_id_NOT_REGISTERED"], "PPSA81234")
        self.assertEqual(obj["ps5_events_delivered"], 0)
        self.assertFalse(obj["native_trophy_registration_performed"])

    def test_no_changes_is_empty(self):
        no_change = {0: {"unlocked": False}, 1: {"unlocked": True}}
        obj = p.compare_progress(BASE, no_change)
        self.assertEqual(obj["new_unlock_events"], [])
        self.assertEqual(obj["current_unlocked"], 1)

    def test_reversal_only_warns(self):
        reversed_status = {0: {"unlocked": False}, 1: {"unlocked": False}}
        obj = p.compare_progress(BASE, reversed_status)
        self.assertEqual(obj["reversed_unlocks_warning"], [1])
        self.assertEqual(obj["new_unlock_events"], [])

    def test_mismatched_trophy_id_rejected(self):
        with self.assertRaises(p.DiffError):
            p.compare_progress(BASE, {0: {"unlocked": True}})

    def test_plan_cannot_claim_registration_allowed(self):
        plan = {"schema": PLAN["schema"], "games": [dict(PLAN["games"][0], registration_allowed=True)]}
        with self.assertRaises(p.DiffError):
            p.compare_progress(BASE, STATES, plan)

    def test_unknown_baseline_not_translated_to_new_unlock(self):
        manifest = dict(BASE, has_unlock_database=False)
        with self.assertRaises(p.DiffError):
            p.compare_progress(manifest, STATES)

    def test_bad_npwr_blocked_before_ftp(self):
        for value in ("../NPWR12345_00", "NPWR12345_00/..", "NPWR1234_00"):
            with self.subTest(value=value), self.assertRaises(p.DiffError):
                p.retr_tropusr(None, value)


if __name__ == "__main__":
    unittest.main()
