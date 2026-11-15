"""Run with: python -m unittest discover -s tests -v."""

import unittest
from pathlib import Path

import yaml
from pyspark.sql import SparkSession, functions as F

from pipeline.utility import (build_gold, build_players, clean_events, clean_stats,
                              find_bronze_file, read_bronze_csv)

ROOT = Path(__file__).resolve().parents[1]
YEAR, GAME = 2025, 11
STATS_DIR = ROOT / f"data/bronze/stats/year={YEAR}/game={GAME:02d}"
EVENTS_DIR = ROOT / f"data/bronze/events/year={YEAR}/game={GAME:02d}"

EVENT_COLUMNS = (
    [("EventType", "string"), ("PassResult", "string"), ("ShotResult", "string"),
     ("ShotXG", "double"), ("EventPrimaryPlayerId", "long"), ("EventPrimaryPlayerName", "string"),
     ("EventPrimaryTeam", "string"), ("EventSecondaryPlayerId", "long"),
     ("EventSecondaryPlayerName", "string"), ("EventSecondaryTeam", "string"),
     ("HomeGoalieOnIce", "boolean"), ("AwayGoalieOnIce", "boolean"),
     ("BluelineCrossingDirection", "string")]
    + [(f"StartPlayerId{i}", "long") for i in range(1, 13)]
    + [(f"StartPlayerVelocity{i}", "double") for i in range(1, 13)]
)


class GoldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = (
            SparkSession.builder.master("local[1]")
            .appName("gold-tests")
            .config("spark.ui.enabled", "false")
            .config("spark.sql.ansi.enabled", "true")
            .getOrCreate()
        )
        cls.spark.sparkContext.setLogLevel("ERROR")

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def events_frame(self, rows):
        """Events with the full silver schema; unspecified columns are null."""
        names = [name for name, _ in EVENT_COLUMNS]
        schema = ", ".join(f"{name} {kind}" for name, kind in EVENT_COLUMNS)
        return self.spark.createDataFrame([tuple(row.get(n) for n in names) for row in rows], schema)

    # ---------- synthetic match ----------

    def synthetic_inputs(self):
        stats = self.spark.createDataFrame([
            ("Team A", 18, "Team A#18", 1, 2, 1800, 0.6, 0.5, 0.4, 2, 1, 4000),
            ("Team A", 9, "Team A#9", 0, 0, 1200, 0.4, 0.3, 0.0, 0, 0, 2500),
        ], "Team string, Jersey int, player_key string, A long, BKS long, `TOI (s)` long, "
           "`xGF-%` double, `PCW-%` double, xGsum double, S long, `S (PRE)` long, `Dist (m)` long")

        players = self.spark.createDataFrame([
            (1, "#18 A One", "Home", "Team A", 18, "Team A#18", True),
            (2, "#9 B Two", "Home", "Team A", 9, "Team A#9", True),
            (99, "#30 Goal Keeper", "Away", "Team B", 30, None, False),
        ], "player_id long, name string, side string, Team string, Jersey int, "
           "player_key string, in_stats boolean")

        shooter = {"EventPrimaryPlayerId": 1, "EventPrimaryTeam": "Home",
                   "EventSecondaryPlayerId": 99, "EventSecondaryTeam": "Away",
                   "HomeGoalieOnIce": True, "AwayGoalieOnIce": True}
        crossing = {"EventType": "BluelineCrossing", "EventPrimaryPlayerId": 1,
                    "EventPrimaryTeam": "Home", "BluelineCrossingDirection": "TowardsOpponent",
                    "StartPlayerId1": 1}
        events = self.events_frame([
            {"EventType": "Pass", "PassResult": "Successful", "EventPrimaryPlayerId": 1,
             "EventPrimaryTeam": "Home", "EventSecondaryPlayerId": 2, "EventSecondaryTeam": "Home"},
            {**shooter, "EventType": "Shot", "ShotResult": "Saved", "ShotXG": 0.3},
            {**shooter, "EventType": "Shot", "ShotResult": "Goal", "ShotXG": 0.5},
            {**crossing, "StartPlayerVelocity1": 8.0},
            {**crossing, "StartPlayerVelocity1": 5.0},
        ])
        return stats, events, players

    def test_build_gold_synthetic_match(self):
        stats, events, players = self.synthetic_inputs()
        gold = build_gold(stats, events, players, 7, "TowardsOpponent", YEAR, GAME)
        rows = {r.player_id: r for r in gold.collect()}
        self.assertEqual(set(rows), {1, 2, 99})

        expected_identity = {
            1: ("A One", "skater", "Team A", 18),
            2: ("B Two", "skater", "Team A", 9),
            99: ("Goal Keeper", "goalie", "Team B", 30),
        }
        for pid, values in expected_identity.items():
            with self.subTest(identity=pid):
                r = rows[pid]
                self.assertEqual((r.name, r.role, r.Team, r.Jersey), values)
                self.assertEqual((r.year, r.game), (YEAR, GAME))

        one, two, keeper = rows[1], rows[2], rows[99]
        # Skater with events
        self.assertEqual((one.A_per60, one.BKS_per60), (2.0, 4.0))
        self.assertEqual((one.Pass_partners, one.Shots_on_target_pct, one.Fast_blueline_crossings),
                         (1, 1.0, 1))
        self.assertEqual((one["xGF-%"], one.xGsum, one["S (PRE)"]), (0.6, 0.4, 1))
        self.assertEqual((one["TOI (s)"], one["Dist (m)"]), (1800, 4000))
        self.assertIsNone(one.SA)
        # Skater without events: counts 0, percentage empty
        self.assertEqual((two.Pass_partners, two.Fast_blueline_crossings), (0, 0))
        self.assertIsNone(two.Shots_on_target_pct)
        self.assertEqual(two.A_per60, 0.0)
        # Goalie: goalie KPIs filled, skater stats empty
        self.assertEqual((keeper.SA, keeper.GA, keeper.SV_pct), (2, 1, 0.5))
        self.assertAlmostEqual(keeper.xGa, 0.8)
        self.assertAlmostEqual(keeper.xG_Diff, -0.2)
        self.assertEqual(keeper.Missing_xG_count, 0)
        self.assertIsNone(keeper.A_per60)
        self.assertEqual((keeper.Pass_partners, keeper.Fast_blueline_crossings), (0, 0))

    def test_build_gold_one_row_per_player(self):
        stats, events, players = self.synthetic_inputs()
        gold = build_gold(stats, events, players, 7, "TowardsOpponent", YEAR, GAME)
        self.assertEqual(gold.count(), players.count())
        self.assertEqual(gold.select("player_id").distinct().count(), gold.count())

    def test_role_skater_missing_from_stats_is_unknown(self):
        stats, events, players = self.synthetic_inputs()
        lost = self.spark.createDataFrame(
            [(3, "#7 Lost Skater", "Home", "Team A", 7, "Team A#7", False)], players.schema)
        gold = build_gold(stats, events, players.unionByName(lost), 7, "TowardsOpponent", YEAR, GAME)
        roles = {r.player_id: r.role for r in gold.collect()}
        self.assertEqual(roles, {1: "skater", 2: "skater", 99: "goalie", 3: "unknown"})

    # ---------- full match ----------

    @unittest.skipUnless(STATS_DIR.exists() and EVENTS_DIR.exists(), "game 11 bronze data not available")
    def test_full_match_gold(self):
        cfg = yaml.safe_load((ROOT / "config/keyplayer_battle.yaml").read_text(encoding="utf-8"))
        blc = cfg["events"]["blueline_crossing"]

        st = clean_stats(read_bronze_csv(self.spark, find_bronze_file(STATS_DIR, "*Statistics*.csv")), YEAR, GAME)
        ev = clean_events(read_bronze_csv(self.spark, find_bronze_file(EVENTS_DIR, "*Events*.csv")), YEAR, GAME)
        players = build_players(ev, st, YEAR, GAME)
        gold = build_gold(st, ev, players, blc["fast_threshold"], blc["direction"], YEAR, GAME)

        # One row per player: 40 skaters + 2 goalies
        self.assertEqual(gold.count(), 42)
        self.assertEqual(gold.select("player_id").distinct().count(), 42)
        roles = {r.role: r["count"] for r in gold.groupBy("role").count().collect()}
        self.assertEqual(roles, {"skater": 40, "goalie": 2})

        # Totals survive the joins
        skaters = gold.filter("role = 'skater'")
        self.assertEqual(skaters.agg(F.sum("S")).first()[0], 112)                       # 70 + 42 shots
        self.assertEqual(gold.agg(F.sum("Fast_blueline_crossings")).first()[0], 143)    # matches test_metrics
        self.assertEqual(skaters.filter(F.col("A_per60").isNull()).count(), 0)          # every skater has stats

        # Goalies: match reports, no skater stats
        goalies = {r.player_id: r for r in gold.filter("role = 'goalie'").collect()}
        self.assertEqual(set(goalies), {888057597, 150983})
        for pid, sa, ga in [(888057597, 31, 5), (150983, 23, 3)]:
            with self.subTest(goalkeeper=pid):
                self.assertEqual((goalies[pid].SA, goalies[pid].GA), (sa, ga))
                self.assertIsNone(goalies[pid].A_per60)
        self.assertIsNone(goalies[150983].xGa)                                          # buzzer shot without xG

        # Names: jersey prefix removed
        self.assertEqual(gold.filter(F.col("name").startswith("#")).count(), 0)


if __name__ == "__main__":
    unittest.main()