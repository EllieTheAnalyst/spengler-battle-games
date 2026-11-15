"""Run with: python -m unittest discover -s tests -v."""

import unittest

from pyspark.sql import SparkSession
from pathlib import Path

from app.metrics import (
    calculate_skater_rates, calculate_tier1_kpis,
    calculate_pass_partners, calculate_shots_on_target_percentage,
    aggregate_goalkeeper_shots, calculate_goalkeeper_kpis,
    calculate_fast_blueline_crossings,
)


class SkaterRatesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spark = (
            SparkSession.builder.master("local[1]")
            .appName("skater-rates-tests")
            .config("spark.ui.enabled", "false")
            .config("spark.sql.ansi.enabled", "true")
            .getOrCreate()
        )
        cls.spark.sparkContext.setLogLevel("ERROR")

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def test_rates_and_original_columns(self):
        records = [
            ("normal", 2, 3, 1200),
            ("zero_counts", 0, 0, 600),
            ("zero_toi", 2, 3, 0),
            ("negative_toi", 2, 3, -600),
            ("missing_toi", 2, 3, None),
            ("missing_assists", None, 3, 1200),
            ("missing_blocks", 2, None, 1200),
            ("missing_both", None, None, 1200),
        ]
        df = self.spark.createDataFrame(
            records, "player string, A long, BKS long, `TOI (s)` long"
        )
        result = calculate_skater_rates(df)
        self.assertEqual(result.columns, df.columns + ["A_per60", "BKS_per60"])
        rows = {row.player: row for row in result.collect()}
        for record in records:
            self.assertEqual(tuple(rows[record[0]])[:4], record)

        expected = {
            "normal": (6.0, 9.0),
            "zero_counts": (0.0, 0.0),
            "zero_toi": (None, None),
            "negative_toi": (None, None),
            "missing_toi": (None, None),
            "missing_assists": (None, 9.0),
            "missing_blocks": (6.0, None),
            "missing_both": (None, None),
        }
        for player, rates in expected.items():
            with self.subTest(player=player):
                self.assertEqual(
                    (rows[player].A_per60, rows[player].BKS_per60), rates
                )

    def test_missing_required_columns(self):
        for missing in (("A",), ("BKS",), ("TOI (s)",), ("A", "BKS", "TOI (s)")):
            with self.subTest(missing=missing):
                df = self.spark.createDataFrame(
                    [(1, 2, 600)], "A long, BKS long, `TOI (s)` long"
                ).drop(*missing)
                with self.assertRaises(ValueError) as caught:
                    calculate_skater_rates(df)
                for name in missing:
                    self.assertIn(name, str(caught.exception))

    def test_tier1_preserves_supplied_values_and_original_columns(self):
        records = [
            ("normal", 2, 3, 1200, 0.53, 0.375, 0.211, 5, 2),
            ("null_supplied", 2, 3, 1200, None, None, None, None, None),
            ("null_assists", None, 3, 1200, 0.53, 0.375, 0.211, 5, 2),
            ("null_blocks", 2, None, 1200, 0.53, 0.375, 0.211, 5, 2),
            ("null_toi", 2, 3, None, 0.53, 0.375, 0.211, 5, 2),
            ("zero_toi", 2, 3, 0, 0.53, 0.375, 0.211, 5, 2),
            ("negative_toi", 2, 3, -1, 0.53, 0.375, 0.211, 5, 2),
        ]
        df = self.spark.createDataFrame(
            records,
            "player string, A long, BKS long, `TOI (s)` long, "
            "`xGF-%` double, `PCW-%` double, xGsum double, S long, `S (PRE)` long",
        )
        result = calculate_tier1_kpis(df)
        self.assertEqual(result.columns, df.columns + ["A_per60", "BKS_per60"])
        self.assertEqual(result.schema.fields[:len(df.columns)], df.schema.fields)
        rows = {row.player: row for row in result.collect()}
        expected_rates = [
            (6.0, 9.0), (6.0, 9.0), (None, 9.0), (6.0, None),
            (None, None), (None, None), (None, None),
        ]
        for record, rates in zip(records, expected_rates):
            with self.subTest(player=record[0]):
                row = rows[record[0]]
                self.assertEqual(tuple(row)[:len(record)], record)
                self.assertEqual((row.A_per60, row.BKS_per60), rates)

    def test_tier1_missing_source_columns(self):
        df = self.spark.createDataFrame(
            [(2, 3, 1200, 0.53, 0.375, 0.211, 5, 2)],
            "A long, BKS long, `TOI (s)` long, `xGF-%` double, "
            "`PCW-%` double, xGsum double, S long, `S (PRE)` long",
        )
        for missing in [(name,) for name in df.columns] + [tuple(df.columns)]:
            with self.subTest(missing=missing):
                with self.assertRaises(ValueError) as caught:
                    calculate_tier1_kpis(df.drop(*missing))
                self.assertEqual(
                    str(caught.exception),
                    "calculate_tier1_kpis requires missing input columns: "
                    + ", ".join(missing),
                )


    def test_pass_partners(self):
        records = [
            ("Pass", "Successful", "p1", "Home", "p2", "Home"),
            ("Pass", "Successful", "p1", "Home", "p2", "Home"),
            ("Pass", "Successful", "p1", "Home", "p3", "Home"),
            ("Pass", "Successful", "p2", "Home", "p1", "Home"),
            ("Pass", "Successful", "p1", "Away", "p4", "Away"),
            ("Pass", "Failed", "p1", "Home", "p5", "Home"),
            ("Pass", "Intercepted", "p1", "Home", "p6", "Away"),
            ("Shot", "Successful", "p1", "Home", "p7", "Home"),
            ("Pass", "Successful", "p1", "Home", "p1", "Home"),
            ("Pass", "Successful", "p1", "Home", "p8", "Away"),
            ("Pass", "Successful", "p1", "Home", None, "Home"),
            ("Pass", "Successful", "p1", "Home", "  ", "Home"),
            ("Pass", "Successful", None, "Home", "p2", "Home"),
            ("Pass", "Successful", "p1", None, "p2", None),
            ("Pass", "Successful", "p1", " ", "p2", " "),
        ]
        df = self.spark.createDataFrame(records, self.pass_schema)
        result = calculate_pass_partners(df)
        self.assertEqual(result.columns, [
            "EventPrimaryPlayerId", "EventPrimaryTeam", "Pass_partners"
        ])
        self.assertEqual(set(map(tuple, result.collect())), {
            ("p1", "Home", 2), ("p2", "Home", 1), ("p1", "Away", 1)
        })

    pass_schema = (
        "EventType string, PassResult string, EventPrimaryPlayerId string, "
        "EventPrimaryTeam string, EventSecondaryPlayerId string, EventSecondaryTeam string"
    )
    shot_schema = (
        "EventType string, EventPrimaryPlayerId string, "
        "EventPrimaryTeam string, ShotResult string"
    )

    def test_shots_on_target(self):
        df = self.spark.createDataFrame([
            ("Shot", "p1", "Home", "Saved"),
            ("Shot", "p1", "Home", "Goal"),
            ("Shot", "p1", "Home", "Missed"),
            ("Shot", "p1", "Home", "Blocked"),
            ("Goal", "p1", "Home", None),
            ("Shot", "p2", "Away", "Saved"),
            ("Shot", "p1", "Away", "Missed"),
        ], self.shot_schema)
        result = calculate_shots_on_target_percentage(df)
        self.assertEqual(result.columns, [
            "EventPrimaryPlayerId", "EventPrimaryTeam", "Shot_attempts",
            "Shots_on_target", "Shots_on_target_pct",
        ])
        self.assertEqual(set(map(tuple, result.collect())), {
            ("p1", "Home", 4, 2, 0.5), ("p2", "Away", 1, 1, 1.0),
            ("p1", "Away", 1, 0, 0.0),
        })

    def test_invalid_shots_rejected(self):
        for record in [
            ("Shot", "p1", "Home", None),
            ("Shot", "p1", "Home", ""),
            ("Shot", "p1", "Home", "Unknown"),
            ("Shot", None, "Home", "Saved"),
            ("Shot", " ", "Home", "Saved"),
            ("Shot", "p1", None, "Saved"),
            ("Shot", "p1", " ", "Saved"),
        ]:
            with self.subTest(record=record):
                df = self.spark.createDataFrame([record], self.shot_schema)
                with self.assertRaisesRegex(ValueError, "every Shot row"):
                    calculate_shots_on_target_percentage(df)

    def test_event_required_columns_and_empty_inputs(self):
        for function, schema in [
            (calculate_pass_partners, self.pass_schema),
            (calculate_shots_on_target_percentage, self.shot_schema),
        ]:
            df = self.spark.createDataFrame([], schema)
            self.assertEqual(function(df).count(), 0)
            for column in df.columns:
                with self.subTest(function=function.__name__, missing=column):
                    with self.assertRaisesRegex(ValueError, "missing required columns") as caught:
                        function(df.drop(column))
                    self.assertIn(column, str(caught.exception))


    goalie_schema = (
        "EventType string, ShotResult string, ShotXG double, EventPrimaryTeam string, "
        "EventSecondaryPlayerId string, EventSecondaryTeam string, "
        "HomeGoalieOnIce boolean, AwayGoalieOnIce boolean"
    )

    def test_goalkeeper_kpis(self):
        # No on-ice slots are provided: secondary attribution is sufficient.
        df = self.spark.createDataFrame([
            ("Shot", "Saved", 0.2, "Home", "g1", "Away", True, True),
            ("Shot", "Goal", 0.3, "Home", "g1", "Away", True, True),
            ("Shot", "Missed", 0.1, "Home", "g1", "Away", True, True),
            ("Shot", "Blocked", 0.4, "Home", "g1", "Away", True, True),
            ("Shot", "Blocked", None, "Home", "g1", "Away", True, True),
            ("Shot", "Missed", None, "Home", "g1", "Away", True, True),
            ("Goal", None, None, "Home", "g1", "Away", True, True),
            ("Shot", "Goal", None, "Away", None, None, False, False),
            ("Shot", "Saved", None, "Away", "g2", "Home", True, True),
            ("Shot", "Missed", 0.5, "Away", "g2", "Home", True, True),
            ("Shot", "Blocked", None, "Home", "g3", "Away", True, True),
            ("Shot", "Missed", 0.25, "Home", "g4", "Away", True, True),
        ], self.goalie_schema)
        rows = {r.GoalkeeperId: r for r in calculate_goalkeeper_kpis(
            aggregate_goalkeeper_shots(df)
        ).collect()}
        self.assertEqual(set(rows), {"g1", "g2", "g3", "g4"})
        g1 = rows['g1']
        self.assertEqual((g1.Shot_attempts, g1.Saves, g1.GA, g1.SA), (6, 1, 1, 2))
        self.assertEqual(g1.SV_pct, 0.5)
        self.assertAlmostEqual(g1.Known_xG_subtotal, 0.5)
        self.assertEqual(g1.Missing_xG_count, 0)
        self.assertAlmostEqual(g1.xGa, 0.5)
        self.assertAlmostEqual(g1.xG_Diff, -0.5)
        self.assertEqual(rows['g2'].Missing_xG_count, 1)
        self.assertIsNone(rows['g2'].Known_xG_subtotal)
        self.assertIsNone(rows['g2'].xGa)
        self.assertIsNone(rows['g2'].xG_Diff)
        self.assertEqual(rows['g2'].SA, 1)
        self.assertIsNone(rows['g3'].Known_xG_subtotal)
        self.assertEqual(rows['g3'].Missing_xG_count, 0)
        self.assertIsNone(rows['g3'].SV_pct)
        self.assertEqual(rows['g4'].SA, 0)
        self.assertIsNone(rows['g4'].SV_pct)
        self.assertIsNone(rows['g4'].Known_xG_subtotal)
        self.assertIsNone(rows['g4'].xG_Diff)

    def test_goalkeeper_invalid_inputs(self):
        valid = ("Shot", "Saved", 0.2, "Home", "g1", "Away", True, True)
        df = self.spark.createDataFrame([valid], self.goalie_schema)
        for name in df.columns:
            with self.subTest(missing=name):
                with self.assertRaises(ValueError):
                    aggregate_goalkeeper_shots(df.drop(name))
        totals = aggregate_goalkeeper_shots(df)
        for name in totals.columns:
            with self.subTest(missing_total=name):
                with self.assertRaises(ValueError):
                    calculate_goalkeeper_kpis(totals.drop(name))
        for index, value in [(1, None), (1, 'Unknown'), (4, None),
                             (5, None), (5, 'Home'), (7, False), (7, None)]:
            row = list(valid)
            row[index] = value
            with self.subTest(index=index, value=value):
                with self.assertRaisesRegex(ValueError, 'ambiguous'):
                    aggregate_goalkeeper_shots(
                        self.spark.createDataFrame([tuple(row)], self.goalie_schema)
                    )
        empty = self.spark.createDataFrame([], self.goalie_schema)
        self.assertEqual(calculate_goalkeeper_kpis(aggregate_goalkeeper_shots(empty)).count(), 0)

    def test_goalkeeper_full_match_reconciliation(self):
        path = next((Path(__file__).resolve().parents[1] / 'data/bronze/events').rglob('*.csv'))
        # CSV loading/casting is test integration setup, outside metrics.py.
        from pyspark.sql import functions as F
        raw = self.spark.read.option('header', True).csv(str(path))
        df = raw.withColumn('ShotXG', F.col('ShotXG').cast('double'))
        for name in ['HomeGoalieOnIce', 'AwayGoalieOnIce']:
            df = df.withColumn(name, F.col(name).cast('boolean'))
        rows = {r.GoalkeeperId: r for r in calculate_goalkeeper_kpis(
            aggregate_goalkeeper_shots(df)
        ).collect()}
        self.assertEqual(set(rows), {'888057597', '150983'})
        for pid, saves, ga, sa, subtotal, missing in [
            ('888057597', 26, 5, 31, 2.788, 0),
            ('150983', 20, 3, 23, 1.715, 1),
        ]:
            r = rows[pid]
            self.assertEqual((r.Saves, r.GA, r.SA, r.Missing_xG_count), (saves, ga, sa, missing))
            self.assertAlmostEqual(r.Known_xG_subtotal, subtotal)
            self.assertAlmostEqual(r.SV_pct, saves / sa)
        self.assertAlmostEqual(rows['888057597'].xGa, 2.788)
        self.assertAlmostEqual(rows['888057597'].xG_Diff, -2.212)
        self.assertIsNone(rows['150983'].xGa)
        self.assertIsNone(rows['150983'].xG_Diff)


    def crossing_frame(self, records):
        schema = (
            "EventType string, EventPrimaryPlayerId string, EventPrimaryTeam string, "
            "BluelineCrossingDirection string, "
            + ", ".join(
                f"StartPlayerId{i} string, StartPlayerVelocity{i} double"
                for i in range(1, 13)
            )
        )
        return self.spark.createDataFrame(records, schema)

    def crossing_record(self, slot=1, velocity=5.0, direction='TowardsOpponent'):
        row = ['BluelineCrossing', 'p1', 'Home', direction]
        for i in range(1, 13):
            row.extend(['p1' if i == slot else f'other{i}', velocity if i == slot else 100.0])
        return row

    def test_crossing_all_slots_threshold_and_direction(self):
        records = [self.crossing_record(slot=i) for i in range(1, 13)]
        records += [self.crossing_record(velocity=4.9),
                    self.crossing_record(velocity=5.1, direction='TowardsHome')]
        other = self.crossing_record()
        other[1] = 'p2'
        other[4] = 'p2'
        records.append(other)
        unrelated = self.crossing_record()
        unrelated[0] = 'Pass'
        records.append(unrelated)
        df = self.crossing_frame(records)
        rows = {r.EventPrimaryPlayerId: r for r in calculate_fast_blueline_crossings(
            df, speed_threshold=5
        ).collect()}
        self.assertEqual((rows['p1'].Crossing_attempts,
                          rows['p1'].Fast_blueline_crossings,
                          rows['p1'].Missing_velocity_count), (14, 13, 0))
        self.assertEqual(rows['p2'].Fast_blueline_crossings, 1)
        filtered = calculate_fast_blueline_crossings(
            df, speed_threshold=5, crossing_direction='TowardsHome'
        ).collect()
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].Fast_blueline_crossings, 1)

    def test_crossing_missing_velocity_and_no_match(self):
        df = self.crossing_frame([
            self.crossing_record(velocity=None), self.crossing_record(slot=0),
            self.crossing_record(velocity=0.0),
        ])
        r = calculate_fast_blueline_crossings(df, speed_threshold=0).first()
        self.assertEqual((r.Crossing_attempts, r.Fast_blueline_crossings,
                          r.Missing_velocity_count), (3, 1, 2))
        empty = self.crossing_frame([])
        self.assertEqual(calculate_fast_blueline_crossings(empty, speed_threshold=5).count(), 0)

    def test_crossing_ellie_settings_boundary(self):
        df = self.crossing_frame([
            self.crossing_record(velocity=6.999),
            self.crossing_record(velocity=7.0),
            self.crossing_record(velocity=7.001),
            self.crossing_record(velocity=8.0, direction='TowardsHome'),
        ])
        r = calculate_fast_blueline_crossings(
            df, speed_threshold=7, crossing_direction='TowardsOpponent'
        ).first()
        self.assertEqual((r.Crossing_attempts, r.Fast_blueline_crossings,
                          r.Missing_velocity_count), (3, 2, 0))

    def test_ellie_full_match_event_reconciliation(self):
        import csv
        from collections import defaultdict, Counter
        from pyspark.sql import functions as F

        path = next((Path(__file__).resolve().parents[1] / 'data/bronze/events').rglob('*.csv'))
        raw = self.spark.read.option('header', True).csv(str(path))
        df = raw
        for i in range(1, 13):
            name = f'StartPlayerVelocity{i}'
            df = df.withColumn(name, F.col(name).cast('double'))
        crossing_rows = calculate_fast_blueline_crossings(
            df, speed_threshold=7, crossing_direction='TowardsOpponent'
        ).collect()
        self.assertEqual(len(crossing_rows), 40)
        selected = sum(r.Crossing_attempts for r in crossing_rows)
        fast = sum(r.Fast_blueline_crossings for r in crossing_rows)
        missing = sum(r.Missing_velocity_count for r in crossing_rows)
        self.assertEqual((selected, fast, missing), (475, 143, 0))
        # Independent CSV row-by-row oracle, including per-player join keys.
        partners = defaultdict(set)
        attempts, on_target = Counter(), Counter()
        crossings = defaultdict(lambda: [0, 0, 0])
        with path.open(encoding='utf-8-sig', newline='') as source:
            for row in csv.DictReader(source):
                key = (row['EventPrimaryPlayerId'], row['EventPrimaryTeam'])
                if row['EventType'] == 'Pass' and row['PassResult'] == 'Successful':
                    if (all(row[c].strip() for c in [
                        'EventPrimaryPlayerId', 'EventPrimaryTeam',
                        'EventSecondaryPlayerId', 'EventSecondaryTeam'
                    ]) and row['EventPrimaryTeam'] == row['EventSecondaryTeam']
                            and row['EventPrimaryPlayerId'] != row['EventSecondaryPlayerId']):
                        partners[key].add(row['EventSecondaryPlayerId'])
                if row['EventType'] == 'Shot':
                    attempts[key] += 1
                    on_target[key] += row['ShotResult'] in ('Saved', 'Goal')
                if (row['EventType'] == 'BluelineCrossing'
                        and row['BluelineCrossingDirection'] == 'TowardsOpponent'):
                    values = [row[f'StartPlayerVelocity{i}'] for i in range(1, 13)
                              if row[f'StartPlayerId{i}'] == key[0]]
                    self.assertEqual(len(values), 1)
                    crossings[key][0] += 1
                    crossings[key][1] += bool(values[0]) and float(values[0]) >= 7
                    crossings[key][2] += not bool(values[0])
        self.assertEqual({(r.EventPrimaryPlayerId, r.EventPrimaryTeam):
                          [r.Crossing_attempts, r.Fast_blueline_crossings, r.Missing_velocity_count]
                          for r in crossing_rows}, dict(crossings))
        self.assertEqual({(r.EventPrimaryPlayerId, r.EventPrimaryTeam): r.Pass_partners
                          for r in calculate_pass_partners(raw).collect()},
                         {key: len(value) for key, value in partners.items()})
        self.assertEqual(sum(attempts.values()), 112)
        self.assertEqual(sum(on_target.values()), 55)
        for r in calculate_shots_on_target_percentage(raw).collect():
            key = (r.EventPrimaryPlayerId, r.EventPrimaryTeam)
            self.assertEqual((r.Shot_attempts, r.Shots_on_target), (attempts[key], on_target[key]))
            self.assertAlmostEqual(r.Shots_on_target_pct, on_target[key] / attempts[key])

    def test_crossing_invalid_inputs(self):
        df = self.crossing_frame([self.crossing_record()])
        for threshold in [None, True, '5', -1, float('nan'), float('inf'), float('-inf')]:
            with self.subTest(threshold=threshold):
                with self.assertRaisesRegex(ValueError, 'speed_threshold'):
                    calculate_fast_blueline_crossings(df, speed_threshold=threshold)
        for name in df.columns:
            with self.subTest(missing=name):
                with self.assertRaisesRegex(ValueError, 'missing required columns'):
                    calculate_fast_blueline_crossings(
                        df.drop(name), speed_threshold=5, crossing_direction='TowardsHome'
                    )
        duplicate = self.crossing_record()
        duplicate[6] = 'p1'  # Second aligned slot repeats the primary player.
        for row in [duplicate] + [
            self.crossing_record(velocity=v) for v in [-1.0, float('nan'), float('inf')]
        ]:
            with self.assertRaises(ValueError):
                calculate_fast_blueline_crossings(self.crossing_frame([row]), speed_threshold=5)
        for index in [1, 2]:
            for value in [None, ' ']:
                row = self.crossing_record()
                row[index] = value
                with self.assertRaisesRegex(ValueError, 'primary player'):
                    calculate_fast_blueline_crossings(self.crossing_frame([row]), speed_threshold=5)


if __name__ == "__main__":
    unittest.main()
