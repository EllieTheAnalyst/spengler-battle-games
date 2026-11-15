"""Run with: python -m unittest discover -s tests -v."""
import unittest
from pathlib import Path

from app.data import _leader, load_battle, load_config, load_gold

ROOT = Path(__file__).resolve().parents[1]
GOLD_DIR = ROOT / "data/gold/player_metrics/year=2025/game=11"


class LeaderTests(unittest.TestCase):
    def test_leader_rules(self):
        self.assertEqual(_leader(5, 3, True), 0)       # higher is better
        self.assertEqual(_leader(3, 5, False), 0)      # fewer is better (goals let in)
        self.assertIsNone(_leader(2, 2, True))         # tie
        self.assertIsNone(_leader(None, 2, True))      # missing


@unittest.skipUnless(GOLD_DIR.exists(), "gold not built")
class BattleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config()
        cls.gold = load_gold(cls.cfg)

    def test_every_battle_loads(self):
        for b in self.cfg["battles"]:
            with self.subTest(battle=b["battle_id"]):
                battle = load_battle(self.cfg, self.gold, b["battle_id"])
                self.assertEqual([p["player_id"] for p in battle["players"]], b["player_ids"])
                metrics = self.cfg["categories"][b["category"]]["metrics"]
                self.assertEqual([s["key"] for s in battle["stats"]], metrics)
                for s in battle["stats"]:
                    self.assertEqual(s["label"], self.cfg["metrics"][s["key"]]["label"])

    def test_missing_xg_fallback(self):
        battle = load_battle(self.cfg, self.gold, "2025-11-goalkeeper")
        xga = next(s for s in battle["stats"] if s["key"] == "xga")
        self.assertAlmostEqual(xga["values"][0], 1.715)                 # known subtotal
        self.assertEqual(xga["notes"][0], "1 shot(s) without xG data")
        self.assertIsNone(xga["notes"][1])

    def test_unknown_battle(self):
        with self.assertRaises(ValueError):
            load_battle(self.cfg, self.gold, "does-not-exist")


if __name__ == "__main__":
    unittest.main()