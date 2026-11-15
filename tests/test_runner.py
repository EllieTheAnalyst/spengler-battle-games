"""Run with: python -m unittest discover -s tests -v."""

import shutil
import tempfile
import unittest
from pathlib import Path

import yaml
from pyspark.sql import SparkSession

from pipeline.utility import discover_games, layer_path, process_game

ROOT = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((ROOT / "config/keyplayer_battle.yaml").read_text(encoding="utf-8"))
REAL_BASE = ROOT / CFG["data"]["root"]


def bronze_dir(base, kind, year, game):
    return layer_path(CFG, base, "bronze", kind, year, game)


@unittest.skipUnless(bronze_dir(REAL_BASE, "stats", 2025, 11).exists()
                     and bronze_dir(REAL_BASE, "events", 2025, 11).exists(),
                     "game 11 bronze data not available")
class RunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = (
            SparkSession.builder.master("local[1]")
            .appName("runner-tests")
            .config("spark.ui.enabled", "false")
            .config("spark.sql.ansi.enabled", "true")
            .getOrCreate()
        )
        cls.spark.sparkContext.setLogLevel("ERROR")

        # Fake data folder: two complete games, one half-delivered, one empty
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.tmp.name) / "data"
        for kind in ["stats", "events"]:
            source = bronze_dir(REAL_BASE, kind, 2025, 11)
            for year, game in [(2025, 11), (2026, 1)]:
                shutil.copytree(source, bronze_dir(cls.base, kind, year, game))
            bronze_dir(cls.base, kind, 2026, 3).mkdir(parents=True)              # empty game
        shutil.copytree(bronze_dir(REAL_BASE, "stats", 2025, 11),
                        bronze_dir(cls.base, "stats", 2026, 2))                  # stats only
        bronze_dir(cls.base, "events", 2026, 2).mkdir(parents=True)

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()
        cls.tmp.cleanup()

    def test_discover_only_complete_games(self):
        self.assertEqual(discover_games(CFG, self.base), [(2025, 11), (2026, 1)])

    def test_process_every_discovered_game(self):
        results = [process_game(self.spark, CFG, self.base, year, game)
                   for year, game in discover_games(CFG, self.base)]

        self.assertEqual(results, [
            {"year": 2025, "game": 11, "players": 42, "skaters": 40, "goalies": 2, "unknown": 0},
            {"year": 2026, "game": 1, "players": 42, "skaters": 40, "goalies": 2, "unknown": 0},
        ])   

        for year, game in [(2025, 11), (2026, 1)]:
            with self.subTest(year=year, game=game):
                for kind in ["stats", "events", "players"]:
                    self.assertTrue(layer_path(CFG, self.base, "silver", kind, year, game).exists())
                gold_path = layer_path(CFG, self.base, "gold", "player_metrics", year, game)
                gold = self.spark.read.parquet(str(gold_path))
                self.assertEqual({(r.year, r.game) for r in gold.select("year", "game").distinct().collect()},
                                 {(year, game)})                                 # each game tagged correctly

        for year, game in [(2026, 2), (2026, 3)]:
            with self.subTest(skipped=(year, game)):
                self.assertFalse(layer_path(CFG, self.base, "gold", "player_metrics", year, game).exists())


if __name__ == "__main__":
    unittest.main()