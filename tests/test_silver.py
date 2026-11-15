"""Run with: python -m unittest discover -s tests -v."""

import csv
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from pyspark.sql import SparkSession, functions as F

from pipeline.utility import (
    build_players, clean_events, clean_stats, find_bronze_file,
    jersey, match_sides, read_bronze_csv, to_bool,
)

ROOT = Path(__file__).resolve().parents[1]
YEAR, GAME = 2025, 11
STATS_DIR = ROOT / f"data/bronze/stats/year={YEAR}/game={GAME:02d}"
EVENTS_DIR = ROOT / f"data/bronze/events/year={YEAR}/game={GAME:02d}"


class SilverPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = (
            SparkSession.builder.master("local[1]")
            .appName("silver-pipeline-tests")
            .config("spark.ui.enabled", "false")
            .config("spark.sql.ansi.enabled", "true")
            .getOrCreate()
        )
        cls.spark.sparkContext.setLogLevel("ERROR")

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    # ---------- helpers ----------

    def test_jersey_and_to_bool(self):
        records = [
            ("#18 Max Muster", "True", 18, True),
            ("#7 A.B. Name", "false", 7, False),
            ("No number", " TRUE ", None, True),
            ("18 without hash", "maybe", None, None),
            (None, None, None, None),
        ]
        df = self.spark.createDataFrame(records, "name string, flag string, j int, b boolean")
        rows = df.select("name", jersey("name").alias("got_j"), to_bool("flag").alias("got_b")).collect()
        for record, row in zip(records, rows):
            with self.subTest(name=record[0], flag=record[1]):
                self.assertEqual((row.got_j, row.got_b), (record[2], record[3]))

    def test_find_bronze_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            with self.assertRaisesRegex(ValueError, r"\*Events\*\.csv"):
                find_bronze_file(folder, "*Events*.csv")                     # zero files
            (folder / "Match_Events_x.csv").touch()
            (folder / "Match_Statistics_x.csv").touch()
            self.assertEqual(find_bronze_file(folder, "*Events*.csv").name, "Match_Events_x.csv")
            (folder / "Match_Events_y.csv").touch()
            with self.assertRaisesRegex(ValueError, "Match_Events_y.csv"):
                find_bronze_file(folder, "*Events*.csv")                     # two files

    def test_read_bronze_csv_separator_and_bom(self):
        for sep in [",", ";"]:
            with self.subTest(sep=sep), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "file.csv"
                path.write_text(f"Team{sep}Jersey{sep}xGF-%\nHC Davos{sep}18{sep}0.5\n", encoding="utf-8-sig")
                df = read_bronze_csv(self.spark, path)
                self.assertEqual(df.columns, ["Team", "Jersey", "xGF-%"])     # no \ufeff
                self.assertEqual(tuple(df.first()), ("HC Davos", 18, 0.5))

    # ---------- cleaning ----------

    def test_clean_stats(self):
        df = self.spark.createDataFrame(
            [(" HC Davos ", 18, " Max ", " Muster ", 0.53), ("Selects", 23, "Ann", "Doe", None)],
            "Team string, Jersey long, FirstName string, LastName string, `xGF-%` double",
        )
        result = clean_stats(df, YEAR, GAME)
        self.assertEqual(result.columns, df.columns + ["year", "game", "player_key"])
        rows = {r.player_key: r for r in result.collect()}
        self.assertEqual(set(rows), {"HC Davos#18", "Selects#23"})
        davos = rows["HC Davos#18"]
        self.assertEqual((davos.Team, davos.FirstName, davos.LastName), ("HC Davos", "Max", "Muster"))
        self.assertEqual((davos["xGF-%"], davos.year, davos.game), (0.53, YEAR, GAME))
        self.assertIsNone(rows["Selects#23"]["xGF-%"])                         # null stays null

    def test_clean_events(self):
        df = self.spark.createDataFrame([
            ("Shot", "Home", "123", "456.0", "0.25", "True", "false", "789", "6.5"),
            ("Pass", "Away", "124", None, None, "FALSE", None, None, None),
        ], "EventType string, EventPrimaryTeam string, EventPrimaryPlayerId string, "
           "EventSecondaryPlayerId string, ShotXG string, HomeGoalieOnIce string, "
           "AwayGoalieOnIce string, StartPlayerId1 string, StartPlayerVelocity1 string")
        result = clean_events(df, YEAR, GAME)
        types = dict(result.dtypes)
        for name, expected in [("EventPrimaryPlayerId", "bigint"), ("EventSecondaryPlayerId", "bigint"),
                               ("StartPlayerId1", "bigint"), ("ShotXG", "double"),
                               ("StartPlayerVelocity1", "double"), ("HomeGoalieOnIce", "boolean"),
                               ("AwayGoalieOnIce", "boolean")]:
            with self.subTest(column=name):
                self.assertEqual(types[name], expected)
        shot, passed = result.orderBy("EventPrimaryPlayerId").collect()
        self.assertEqual((shot.EventPrimaryPlayerId, shot.EventSecondaryPlayerId, shot.ShotXG),
                         (123, 456, 0.25))
        self.assertEqual((shot.HomeGoalieOnIce, shot.AwayGoalieOnIce), (True, False))
        self.assertEqual((passed.EventSecondaryPlayerId, passed.ShotXG, passed.AwayGoalieOnIce),
                         (None, None, None))                                   # nulls preserved
        self.assertEqual((shot.EventPrimaryTeam, passed.EventPrimaryTeam), ("Home", "Away"))  # kept

    # ---------- player mapping ----------

    events_schema = (
        "EventType string, EventPrimaryPlayerId long, EventPrimaryPlayerName string, "
        "EventPrimaryTeam string, EventSecondaryPlayerId long, "
        "EventSecondaryPlayerName string, EventSecondaryTeam string"
    )
    stats_schema = "Team string, Jersey int, S long, player_key string"

    def stats_frame(self):
        return self.spark.createDataFrame(
            [("Team A", 18, 1, "Team A#18"), ("Team B", 18, 2, "Team B#18"), ("Team B", 9, 0, "Team B#9")],
            self.stats_schema)

    def test_match_sides(self):
        events = self.spark.createDataFrame([
            ("Shot", 1, "#18 A", "Home", None, None, None),
            ("Shot", 2, "#18 B", "Away", None, None, None),
            ("Shot", 2, "#18 B", "Away", None, None, None),
            ("Pass", 1, "#18 A", "Home", 3, "#9 C", "Home"),
        ], self.events_schema)
        self.assertEqual(match_sides(events, self.stats_frame()), {"Home": "Team A", "Away": "Team B"})
        for records in [
            [("Shot", 1, "#18 A", "Home", None, None, None), ("Shot", 2, "#18 B", "Away", None, None, None)],
            [("Shot", 1, "#18 A", "Home", None, None, None)],
        ]:
            with self.subTest(records=len(records)):
                stats = self.spark.createDataFrame(
                    [("Team A", 18, 1, "a"), ("Team B", 18, 1, "b")], self.stats_schema)
                with self.assertRaisesRegex(ValueError, "Could not match"):
                    match_sides(self.spark.createDataFrame(records, self.events_schema), stats)

    def test_build_players(self):
        events = self.spark.createDataFrame([
            ("Shot", 1, "#18 A", "Home", 99, "#30 Goalie", "Away"),
            ("Shot", 2, "#18 B", "Away", 98, "#1 Goalie", "Home"),
            ("Shot", 2, "#18 B", "Away", 98, "#1 Goalie", "Home"),
            ("Pass", 2, "#18 B", "Away", 3, "#9 C", "Away"),
            ("Faceoff", None, None, None, None, None, None),
        ], self.events_schema)
        rows = {r.player_id: r for r in build_players(events, self.stats_frame(), YEAR, GAME).collect()}
        self.assertEqual(set(rows), {1, 2, 3, 98, 99})
        expected = {
            1: ("Team A", 18, "Team A#18", True), 2: ("Team B", 18, "Team B#18", True),
            3: ("Team B", 9, "Team B#9", True), 98: ("Team A", 1, None, False),
            99: ("Team B", 30, None, False),
        }
        for pid, values in expected.items():
            with self.subTest(player_id=pid):
                r = rows[pid]
                self.assertEqual((r.Team, r.Jersey, r.player_key, r.in_stats), values)

    def test_build_players_rejects_unknown_side(self):
        events = self.spark.createDataFrame([
            ("Shot", 1, "#18 A", "Home", None, None, None),
            ("Shot", 2, "#18 B", "Away", None, None, None),
            ("Shot", 2, "#18 B", "Away", None, None, None),
            ("Pass", 1, "#18 A", "Home", 3, "#9 C", "Neutral"),
        ], self.events_schema)
        with self.assertRaisesRegex(ValueError, "Neutral"):
            build_players(events, self.stats_frame(), YEAR, GAME)

    # ---------- full match ----------

    @unittest.skipUnless(STATS_DIR.exists() and EVENTS_DIR.exists(), "game 11 bronze data not available")
    def test_full_match_reconciliation(self):
        from app.metrics import aggregate_goalkeeper_shots, calculate_goalkeeper_kpis

        stats_path = find_bronze_file(STATS_DIR, "*Statistics*.csv")
        events_path = find_bronze_file(EVENTS_DIR, "*Events*.csv")
        st = clean_stats(read_bronze_csv(self.spark, stats_path), YEAR, GAME)
        ev = clean_events(read_bronze_csv(self.spark, events_path), YEAR, GAME)
        players = build_players(ev, st, YEAR, GAME)

        # Independent CSV row-by-row oracle (no Spark).
        with events_path.open(encoding="utf-8-sig", newline="") as source:
            rows = list(csv.DictReader(source))
        shots = [r for r in rows if r["EventType"] == "Shot"]
        side_shots = Counter(r["EventPrimaryTeam"] for r in shots)
        with stats_path.open(encoding="utf-8-sig", newline="") as source:
            stats_rows = list(csv.DictReader(source))
        team_shots = Counter()
        for r in stats_rows:
            team_shots[r["Team"].strip()] += int(r["S"])

        # Row counts and cleaning
        self.assertEqual((st.count(), ev.count()), (len(stats_rows), len(rows)))
        self.assertEqual((st.count(), ev.count()), (40, 4458))
        self.assertEqual(st.select("player_key").distinct().count(), 40)
        pct_cols = [c for c in st.columns if "%" in c]
        maxima = st.select(*[F.max(F.abs(F.col(f"`{c}`"))).alias(c) for c in pct_cols]).first()
        for c in pct_cols:
            with self.subTest(percentage=c):
                self.assertLessEqual(maxima[c] or 0, 1)

        # Shots: Spark result == oracle == known values
        spark_results = {r.ShotResult: r["count"] for r in
                         ev.filter(F.col("EventType") == "Shot").groupBy("ShotResult").count().collect()}
        self.assertEqual(spark_results, dict(Counter(r["ShotResult"] for r in shots)))
        self.assertEqual(spark_results, {"Saved": 46, "Goal": 9, "Missed": 36, "Blocked": 21})
        self.assertEqual(ev.filter((F.col("EventType") == "Shot") & F.col("ShotXG").isNull()).count(),
                         sum(1 for r in shots if not r["ShotXG"].strip()))

        # Home/Away mapping: oracle (equal shot totals) and known teams
        oracle_sides = {side: team for side, n in side_shots.items()
                        for team, m in team_shots.items() if n == m}
        self.assertEqual(match_sides(ev, st), oracle_sides)
        self.assertEqual(oracle_sides, {"Home": "U.S. Collegiate Selects", "Away": "HC Davos"})

        # Players: every skater linked once, the two goalies not in stats
        self.assertEqual(players.select("player_id").distinct().count(), players.count())
        self.assertEqual(players.filter("in_stats").count(), 40)
        self.assertEqual({r.player_id for r in players.filter("NOT in_stats").collect()},
                         {888057597, 150983})

        # Silver feeds metrics.py: goalie numbers match the match reports
        gk = {r.GoalkeeperId: r for r in calculate_goalkeeper_kpis(aggregate_goalkeeper_shots(ev)).collect()}
        for pid, saves, ga, sa in [(888057597, 26, 5, 31), (150983, 20, 3, 23)]:
            with self.subTest(goalkeeper=pid):
                self.assertEqual((gk[pid].Saves, gk[pid].GA, gk[pid].SA), (saves, ga, sa))


if __name__ == "__main__":
    unittest.main()