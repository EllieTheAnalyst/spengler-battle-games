"""Run with: python -m unittest discover -s tests -v."""

import unittest
from pathlib import Path

import yaml
from pyspark.sql import SparkSession, functions as F

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/keyplayer_battle.yaml"
GOLD_DIR = ROOT / "data/gold/player_metrics/year=2025/game=11"


class ConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))

    def test_main_sections_exist(self):
        for section in ["data", "active_game", "events", "metrics", "categories", "normalisation", "voting", "battles"]:
            with self.subTest(section=section):
                self.assertIn(section, self.cfg)

    def test_every_metric_is_complete(self):
        for key, metric in self.cfg["metrics"].items():
            with self.subTest(metric=key):
                self.assertTrue({"column", "label", "unit", "higher_is_better"} <= set(metric))
                self.assertIn(metric["unit"], {"fraction", "number", "count"})
                self.assertIsInstance(metric["higher_is_better"], bool)

    def test_categories_use_defined_metrics(self):
        for key, category in self.cfg["categories"].items():
            with self.subTest(category=key):
                self.assertIn(category["players"], {"skater", "goalie"})
                self.assertEqual(len(category["metrics"]), 5)          # five radar axes
                for metric in category["metrics"]:
                    self.assertIn(metric, self.cfg["metrics"])

    def test_battles_are_well_formed(self):
        battles = self.cfg["battles"]
        self.assertEqual(len({b["battle_id"] for b in battles}), len(battles))   # unique ids
        for battle in battles:
            with self.subTest(battle=battle["battle_id"]):
                self.assertIn(battle["category"], self.cfg["categories"])
                self.assertEqual(len(battle["player_ids"]), 2)
                self.assertNotEqual(*battle["player_ids"])                         # two different players    


@unittest.skipUnless(GOLD_DIR.exists(), "gold for game 11 not built yet")
class ConfigMatchesGoldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        cls.spark = (SparkSession.builder.master("local[1]").appName("config-gold-tests")
                     .config("spark.ui.enabled", "false").getOrCreate())
        cls.spark.sparkContext.setLogLevel("ERROR")
        cls.gold = cls.spark.read.parquet(str(GOLD_DIR))

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def test_metric_columns_exist_in_gold(self):
        for key, metric in self.cfg["metrics"].items():
            with self.subTest(metric=key):
                self.assertIn(metric["column"], self.gold.columns)

    def test_category_roles_exist_in_gold(self):
        roles = {r.role for r in self.gold.select("role").distinct().collect()}
        for key, category in self.cfg["categories"].items():
            with self.subTest(category=key):
                self.assertIn(category["players"], roles)

    def test_fraction_metrics_are_between_0_and_1(self):
        for key, metric in self.cfg["metrics"].items():
            if metric["unit"] != "fraction":
                continue
            with self.subTest(metric=key):
                low, high = self.gold.select(F.min(F.col(f"`{metric['column']}`")),
                                             F.max(F.col(f"`{metric['column']}`"))).first()
                self.assertGreaterEqual(low, 0)
                self.assertLessEqual(high, 1)

    def test_battle_players_exist_and_fit_category(self):
        rows = {r.player_id: r for r in self.gold.select("player_id", "role", "Team").collect()}
        for battle in self.cfg["battles"]:
            role = self.cfg["categories"][battle["category"]]["players"]
            with self.subTest(battle=battle["battle_id"]):
                a, b = (rows.get(pid) for pid in battle["player_ids"])
                self.assertIsNotNone(a, "player not in gold")
                self.assertIsNotNone(b, "player not in gold")
                self.assertEqual((a.role, b.role), (role, role))                  # skaters vs skaters, goalies vs goalies
                self.assertNotEqual(a.Team, b.Team)                               # one player per team

    def test_name_corrections_applied(self):
        names = {r.player_id: r.name for r in self.gold.select("player_id", "name").collect()}
        for pid, correct in (self.cfg.get("name_corrections") or {}).items():
            with self.subTest(player_id=pid):
                self.assertEqual(names.get(pid), correct)


if __name__ == "__main__":
    unittest.main()