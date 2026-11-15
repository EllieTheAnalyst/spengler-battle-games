"""Helpers for the bronze to silver step."""

from pathlib import Path
from pyspark.sql import DataFrame, functions as F
from pyspark.sql.types import NumericType


# ---------- column helpers ----------

def q(c: str):
    """Column with any name (spaces, dots, %)."""
    return F.col(f"`{c}`")


def jersey(c: str):
    """'#18 Firstname Lastname' -> 18; no leading number -> null."""
    number = F.regexp_extract(q(c), r"^#(\d+)", 1)
    return F.when(number != "", number).cast("int")


def to_bool(c: str):
    """'True'/'False' (any case) -> booleans; anything else -> null."""
    s = F.lower(F.trim(q(c).cast("string")))
    return F.when(s == "true", True).when(s == "false", False)


# ---------- reading ----------

def find_bronze_file(folder: Path, pattern: str) -> Path:
    """Return the one file in folder matching pattern; raise if zero or several."""
    files = sorted(Path(folder).glob(pattern))
    if len(files) != 1:
        raise ValueError(f"Expected exactly 1 file matching '{pattern}' in {folder}, "
                         f"found {[f.name for f in files]}")
    return files[0]


def read_bronze_csv(spark, path: Path) -> DataFrame:
    """Read a bronze CSV: detect , or ; and remove the byte-order mark from column names."""
    header = Path(path).read_text(encoding="utf-8-sig").splitlines()[0]
    sep = ";" if header.count(";") > header.count(",") else ","
    df = spark.read.csv(str(path), header=True, inferSchema=True, sep=sep)
    return df.toDF(*[c.replace("\ufeff", "").strip() for c in df.columns])


# ---------- cleaning ----------

def clean_stats(st: DataFrame, year: int, game: int) -> DataFrame:
    """Trim names, add jersey as int, player_key (team#jersey), year and game."""
    return (st.withColumns({c: F.trim(q(c)) for c in ["Team", "LastName", "FirstName"]})
              .withColumns({"Jersey": q("Jersey").cast("int"), "year": F.lit(year), "game": F.lit(game)})
              .withColumn("player_key", F.concat_ws("#", "Team", F.col("Jersey").cast("string"))))


def clean_events(ev: DataFrame, year: int, game: int) -> DataFrame:
    """IDs as long, xG and velocities as double, goalie flags as booleans. Keeps Home/Away."""
    id_cols = ["EventPrimaryPlayerId", "EventSecondaryPlayerId"] + [c for c in ev.columns if c.startswith("StartPlayerId")]
    num_cols = ["ShotXG"] + [c for c in ev.columns if c.startswith("StartPlayerVelocity")]
    return (ev.withColumns({c: q(c).cast("double").cast("long") for c in id_cols})
              .withColumns({c: q(c).cast("double") for c in num_cols})
              .withColumns({c: to_bool(c) for c in ["HomeGoalieOnIce", "AwayGoalieOnIce"]})
              .withColumns({"year": F.lit(year), "game": F.lit(game)}))


# ---------- player mapping ----------

def match_sides(events: DataFrame, stats: DataFrame) -> dict:
    """Map Home/Away to team names: event shot totals per side = stats S per team."""
    side_shots = (events.filter(F.col("EventType") == "Shot")
                        .groupBy(F.col("EventPrimaryTeam").alias("side")).count())
    team_shots = stats.groupBy("Team").agg(F.sum("S").alias("count"))
    sides = dict(side_shots.join(team_shots, "count").select("side", "Team").collect())
    if set(sides) != {"Home", "Away"} or len(set(sides.values())) != 2:
        raise ValueError(f"Could not match Home/Away to teams: {sides}")
    return sides


def build_players(ev: DataFrame, st: DataFrame, year: int, game: int) -> DataFrame:
    """One row per event player: ID, team, jersey, player_key; in_stats = False for goalies."""
    sides = match_sides(ev, st)

    def pick(role):
        return ev.select(F.col(f"Event{role}PlayerId").alias("player_id"),
                         F.col(f"Event{role}PlayerName").alias("name"),
                         F.col(f"Event{role}Team").alias("side"))

    players = (pick("Primary").union(pick("Secondary")).dropna(subset=["player_id"]).distinct()
               .withColumn("Jersey", jersey("name"))
               .withColumn("Team", F.when(F.col("side") == "Home", sides["Home"])
                                    .when(F.col("side") == "Away", sides["Away"])))
    unknown = players.filter(F.col("Team").isNull()).select("side").distinct().collect()
    if unknown:
        raise ValueError(f"Unexpected side values in events: {unknown}")

    return (players.join(st.select("Team", "Jersey", "player_key"), on=["Team", "Jersey"], how="left")
                   .withColumn("in_stats", F.col("player_key").isNotNull())
                   .withColumns({"year": F.lit(year), "game": F.lit(game)}))

def check_silver(st: DataFrame, ev: DataFrame, players: DataFrame) -> None:
    """Stop with a clear message if silver doesn't match what the KPI functions expect."""
    problems = []

    text_cols = {"Team", "LastName", "FirstName", "player_key"}
    bad_types = [f.name for f in st.schema.fields
                 if f.name not in text_cols and not isinstance(f.dataType, NumericType)]
    if bad_types:
        problems.append(f"stats columns not numeric: {bad_types}")

    pct_cols = [c for c in st.columns if "%" in c]
    pct_max = st.select(*[F.max(F.abs(q(c))).alias(c) for c in pct_cols]).first().asDict()
    if any(v is not None and v > 1 for v in pct_max.values()):
        problems.append(f"percentages not 0–1: {pct_max}")

    if st.select("player_key").distinct().count() != st.count():
        problems.append("duplicate team + jersey in stats")

    bad_shots = ev.filter((F.col("EventType") == "Shot") &
                          ~F.coalesce(F.col("ShotResult").isin("Saved", "Goal", "Missed", "Blocked"),
                                      F.lit(False))).count()
    if bad_shots:
        problems.append(f"{bad_shots} shots with unknown ShotResult")

    if players.groupBy("player_id").count().filter("count > 1").count():
        problems.append("player ID with several names/teams")

    if problems:
        raise ValueError("Silver checks failed: " + "; ".join(problems))

# ---------- paths ----------

def layer_path(cfg: dict, base: Path, layer: str, kind: str, year: int, game: int) -> Path:
    """Folder of a table from the YAML, e.g. layer_path(cfg, base, 'silver', 'stats', 2025, 11)."""
    return Path(base) / cfg["data"][layer][kind].format(year=year, game=game)

def discover_games(cfg: dict, base: Path) -> list[tuple[int, int]]:
    """All (year, game) pairs with a stats AND an events file in bronze, sorted. Empty folders are skipped."""
    import re

    def games_with_file(kind):
        root = Path(base) / cfg["data"]["bronze"][kind].split("/year=")[0]    # e.g. data/bronze/stats
        pattern = cfg["data"]["bronze_files"][kind]                           # e.g. *Statistics*.csv
        found = set()
        for folder in root.glob("year=*/game=*"):
            year = re.fullmatch(r"year=(\d+)", folder.parent.name)
            game = re.fullmatch(r"game=(\d+)", folder.name)
            if year and game and any(folder.glob(pattern)):
                found.add((int(year.group(1)), int(game.group(1))))
        return found

    return sorted(games_with_file("stats") & games_with_file("events"))


# ---------- gold ----------

def _by_player_id(df: DataFrame) -> DataFrame:
    """metrics.py event outputs → keyed by player_id only."""
    return df.withColumnRenamed("EventPrimaryPlayerId", "player_id").drop("EventPrimaryTeam")


def skater_event_kpis(ev: DataFrame, speed_threshold: float, direction: str) -> DataFrame:
    """Pass partners, shots-on-target % and fast blue line crossings per player_id."""
    from app.metrics import (calculate_fast_blueline_crossings, calculate_pass_partners,
                             calculate_shots_on_target_percentage)
    passes = _by_player_id(calculate_pass_partners(ev))
    shots = _by_player_id(calculate_shots_on_target_percentage(ev)).select("player_id", "Shots_on_target_pct")
    crossings = _by_player_id(calculate_fast_blueline_crossings(
        ev, speed_threshold=speed_threshold, crossing_direction=direction
    )).select("player_id", "Fast_blueline_crossings")
    return passes.join(shots, "player_id", "full").join(crossings, "player_id", "full")


def goalie_kpis(ev: DataFrame) -> DataFrame:
    """SA, SV%, GA, xGa, xG Diff per goalie player_id."""
    from app.metrics import aggregate_goalkeeper_shots, calculate_goalkeeper_kpis
    return (calculate_goalkeeper_kpis(aggregate_goalkeeper_shots(ev))
            .withColumnRenamed("GoalkeeperId", "player_id")
            .select("player_id", "SA", "SV_pct", "GA", "xGa", "xG_Diff",
                    "Known_xG_subtotal", "Missing_xG_count"))


def build_gold(st: DataFrame, ev: DataFrame, players: DataFrame,
               speed_threshold: float, direction: str, year: int, game: int,
               name_fixes: dict | None = None) -> DataFrame:
    """One row per player with identity, role and all KPIs."""
    from app.metrics import calculate_tier1_kpis
    tier1 = calculate_tier1_kpis(st).select(
        "player_key", "A_per60", "BKS_per60", "`xGF-%`", "`PCW-%`", "xGsum", "S", "`S (PRE)`",
        "`TOI (s)`", "`Dist (m)`")

    display_name = F.regexp_replace("name", r"^#\d+\s*", "")             # "#18 Max Muster" → "Max Muster"
    if name_fixes:                                                        # typo corrections from the YAML
        fix_map = F.create_map(*[x for pid, name in name_fixes.items()
                                 for x in (F.lit(pid).cast("long"), F.lit(name))])
        display_name = F.coalesce(fix_map[F.col("player_id")], display_name)

    return (players
        .select("player_id", "player_key", "Team", "Jersey", "in_stats",
                display_name.alias("name"))
        .join(tier1, "player_key", "left")
        .join(skater_event_kpis(ev, speed_threshold, direction), "player_id", "left")
        .join(goalie_kpis(ev), "player_id", "left")
        .withColumn("role",
            F.when(F.col("in_stats"), "skater")              # in the stats file
             .when(F.col("SA").isNotNull(), "goalie")        # faced shots as goalie
             .otherwise("unknown"))                          # neither → flagged by checks
        .drop("in_stats")
        .fillna({"Pass_partners": 0, "Fast_blueline_crossings": 0})            # no event = 0; % stays empty
        .withColumns({"year": F.lit(year), "game": F.lit(game)}))

# ---------- runner ----------

def process_game(spark, cfg: dict, base: Path, year: int, game: int) -> dict:
    """Bronze → silver → gold for one game. Returns a short summary."""
    def bronze(kind):
        folder = layer_path(cfg, base, "bronze", kind, year, game)
        return read_bronze_csv(spark, find_bronze_file(folder, cfg["data"]["bronze_files"][kind]))

    # silver
    st = clean_stats(bronze("stats"), year, game)
    ev = clean_events(bronze("events"), year, game)
    players = build_players(ev, st, year, game)
    check_silver(st, ev, players)
    for kind, df in [("stats", st), ("events", ev), ("players", players)]:
        df.write.mode("overwrite").parquet(str(layer_path(cfg, base, "silver", kind, year, game)))

    # gold
    blc = cfg["events"]["blueline_crossing"]
    gold = build_gold(st, ev, players, blc["fast_threshold"], blc["direction"], year, game,
                      name_fixes=cfg.get("name_corrections"))
    gold.write.mode("overwrite").parquet(str(layer_path(cfg, base, "gold", "player_metrics", year, game)))

    roles = {r.role: r["count"] for r in gold.groupBy("role").count().collect()}
    return {"year": year, "game": game, "players": gold.count(),
            "skaters": roles.get("skater", 0), "goalies": roles.get("goalie", 0),
            "unknown": roles.get("unknown", 0)}