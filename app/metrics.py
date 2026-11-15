"""Reusable hockey KPI calculations using native PySpark expressions.

Raw Tier 1 statistics column names are a temporary input contract until the
team agrees on the silver schema. Required statistics must already have Spark
numeric types, with time on ice in seconds and percentages as fractions (0–1).
CSV ingestion and numeric conversion belong upstream in Bronze-to-Silver.
Null statistics are preserved; they are not interpreted as zero.
"""

import math
from decimal import Decimal
from numbers import Real

from pyspark.sql import DataFrame, functions as F
from pyspark.sql.types import NumericType


def calculate_skater_rates(df: DataFrame) -> DataFrame:
    """Add assists and blocked shots per 60 minutes, preserving input columns.

    Null, zero, or negative time on ice produces null rates. A null numerator
    remains null. Existing ``A_per60`` or ``BKS_per60`` columns are recalculated.

    Raises:
        ValueError: If any required Tier 1 input columns are missing.
    """
    required_columns = ("A", "BKS", "TOI (s)")
    missing_columns = [name for name in required_columns if name not in df.columns]
    if missing_columns:
        raise ValueError(
            "calculate_skater_rates requires missing input columns: "
            + ", ".join(missing_columns)
        )

    toi = F.col("TOI (s)")
    for numerator, output in (("A", "A_per60"), ("BKS", "BKS_per60")):
        df = df.withColumn(
            output,
            F.when(toi > 0, F.col(numerator) * F.lit(3600.0) / toi),
        )
    return df


def calculate_tier1_kpis(df: DataFrame) -> DataFrame:
    """Return the seven statistics-based KPIs, preserving original columns.

    Greatest Teamplayer:
        A_per60: calculated as A * 3600 / TOI (s).
        BKS_per60: calculated as BKS * 3600 / TOI (s).
        xGF-%: supplied unchanged in the source column xGF-%.
        PCW-%: supplied unchanged in the source column PCW-%.
    Most Dangerous Player:
        xGsum: supplied unchanged in the source column xGsum.
        S: supplied unchanged in the source column S.
        S (PRE): supplied unchanged; its definition is not yet confirmed.

    Inputs must follow the module's numeric contract. Supplied KPIs retain
    their names, types, nulls, and fractional percentage values. Rate behavior,
    including invalid TOI handling, follows calculate_skater_rates.

    Raises:
        ValueError: If any required source columns are missing.
    """
    required_columns = (
        "A", "BKS", "TOI (s)", "xGF-%", "PCW-%", "xGsum", "S", "S (PRE)"
    )
    missing_columns = [name for name in required_columns if name not in df.columns]
    if missing_columns:
        raise ValueError(
            "calculate_tier1_kpis requires missing input columns: "
            + ", ".join(missing_columns)
        )
    return calculate_skater_rates(df)


def _require_event_columns(df: DataFrame, required: tuple, function: str) -> None:
    missing = [name for name in required if name not in df.columns]
    if missing:
        raise ValueError(f"{function} missing required columns: {', '.join(missing)}")


def _valid_identifier(name: str):
    """Accept populated numeric or string identifiers; reject null/blank values."""
    return F.col(name).isNotNull() & (F.length(F.trim(F.col(name).cast("string"))) > 0)


def calculate_pass_partners(events_df: DataFrame) -> DataFrame:
    """Count distinct successful outgoing recipients per passer/team.

    This is a provisional project convention for a single-match input. Primary
    and secondary IDs denote passer and receiver. Null/blank IDs or teams,
    cross-team passes, and self-passes are excluded. IDs must be consistently
    typed and normalized upstream. Players with no qualifying passes require a
    separate roster join. No input columns are modified.

    Raises:
        ValueError: If required event columns are missing.
    """
    required = (
        "EventType", "PassResult", "EventPrimaryPlayerId", "EventPrimaryTeam",
        "EventSecondaryPlayerId", "EventSecondaryTeam",
    )
    _require_event_columns(events_df, required, "calculate_pass_partners")
    valid = (
        (F.col("EventType") == "Pass")
        & (F.col("PassResult") == "Successful")
        & (F.col("EventPrimaryTeam") == F.col("EventSecondaryTeam"))
        & (F.col("EventPrimaryPlayerId") != F.col("EventSecondaryPlayerId"))
    )
    for name in required[2:]:
        valid = valid & _valid_identifier(name)
    return events_df.filter(valid).groupBy(
        "EventPrimaryPlayerId", "EventPrimaryTeam"
    ).agg(F.countDistinct("EventSecondaryPlayerId").alias("Pass_partners"))


def calculate_shots_on_target_percentage(events_df: DataFrame) -> DataFrame:
    """Aggregate shot attempts and on-target fractions per player/team.

    Provisional project convention for a single-match input: Saved and Goal
    are on target; Missed and Blocked are off target. Only Shot rows count,
    excluding separate Goal events. Players with no shots require a separate
    roster join; their percentage is undefined. IDs must be normalized upstream.

    Validation executes a Spark action before returning the aggregate. Rejects
    Shot rows with null/blank primary IDs or teams, or outcomes outside the four
    accepted values (including missing outcomes), rather than dropping attempts.

    Raises:
        ValueError: If required columns or valid shot values are missing.
    """
    required = ("EventType", "EventPrimaryPlayerId", "EventPrimaryTeam", "ShotResult")
    _require_event_columns(events_df, required, "calculate_shots_on_target_percentage")
    shots = events_df.filter(F.col("EventType") == "Shot")
    valid = (
        _valid_identifier("EventPrimaryPlayerId")
        & _valid_identifier("EventPrimaryTeam")
        & F.col("ShotResult").isNotNull()
        & F.col("ShotResult").isin("Saved", "Goal", "Missed", "Blocked")
    )
    if shots.filter(~valid).limit(1).count():
        raise ValueError(
            "calculate_shots_on_target_percentage requires populated primary player "
            "IDs/teams and ShotResult in Saved, Goal, Missed, Blocked on every Shot row"
        )
    return shots.groupBy("EventPrimaryPlayerId", "EventPrimaryTeam").agg(
        F.count(F.lit(1)).alias("Shot_attempts"),
        F.sum(F.when(F.col("ShotResult").isin("Saved", "Goal"), 1).otherwise(0))
        .alias("Shots_on_target"),
    ).withColumn(
        "Shots_on_target_pct", F.col("Shots_on_target") / F.col("Shot_attempts")
    )


def aggregate_goalkeeper_shots(events_df: DataFrame) -> DataFrame:
    """Aggregate a single match's Shot rows by secondary goalkeeper ID/team.

    Output: GoalkeeperId, GoalkeeperTeam, Shot_attempts, Saves, GA,
    Known_xG_subtotal, Missing_xG_count. ShotXG must be numeric, with missing
    values represented as null upstream. Team-approved convention: only Saved
    and Goal shots contribute to the subtotal and missing-xG count, matching SA.
    Wisehockey distinguishes xGa from on-goal-only xGSA; the project's xGa label
    intentionally follows this on-target-only convention. A subtotal with no
    known qualifying xG remains null. Missed/Blocked still count as attempts.

    No on-ice slot match is required. An unattributed Goal is excluded only if
    both secondary ID/team are absent and the defending goalie flag is false.
    Other invalid attribution, unknown outcomes, and contradictory defending
    goalie flags raise ValueError via an eager Spark validation action. Teams
    must be Home/Away and goalie flags boolean. Players with no attributed shots
    require a separate roster join. CSV conversion belongs upstream.
    """
    required = (
        "EventType", "ShotResult", "ShotXG", "EventPrimaryTeam",
        "EventSecondaryPlayerId", "EventSecondaryTeam",
        "HomeGoalieOnIce", "AwayGoalieOnIce",
    )
    _require_event_columns(events_df, required, "aggregate_goalkeeper_shots")
    shots = events_df.filter(F.col("EventType") == "Shot")
    shooter_team = F.col("EventPrimaryTeam")
    defender_team = F.col("EventSecondaryTeam")
    defending_goalie = F.when(
        shooter_team == "Home", F.col("AwayGoalieOnIce")
    ).when(shooter_team == "Away", F.col("HomeGoalieOnIce"))
    attributed = (
        _valid_identifier("EventSecondaryPlayerId")
        & defender_team.isin("Home", "Away")
        & (defender_team != shooter_team)
        & (defending_goalie == F.lit(True))
    )
    empty_net = (
        (F.col("ShotResult") == "Goal")
        & ~_valid_identifier("EventSecondaryPlayerId")
        & ~_valid_identifier("EventSecondaryTeam")
        & (defending_goalie == F.lit(False))
    )
    valid = (
        shooter_team.isin("Home", "Away")
        & F.col("ShotResult").isin("Saved", "Goal", "Missed", "Blocked")
        & (attributed | empty_net)
    )
    if shots.filter(~F.coalesce(valid, F.lit(False))).limit(1).count():
        raise ValueError(
            "aggregate_goalkeeper_shots: invalid ShotResult or ambiguous goalkeeper "
            "attribution/defending goalie flag; expected Saved, Goal, Missed, Blocked "
            "and opposing Home/Away teams, or an explicitly unattributed empty-net Goal"
        )
    on_target = F.col("ShotResult").isin("Saved", "Goal")
    return shots.filter(attributed).groupBy(
        F.col("EventSecondaryPlayerId").alias("GoalkeeperId"),
        F.col("EventSecondaryTeam").alias("GoalkeeperTeam"),
    ).agg(
        F.count(F.lit(1)).alias("Shot_attempts"),
        F.sum(F.when(F.col("ShotResult") == "Saved", 1).otherwise(0)).alias("Saves"),
        F.sum(F.when(F.col("ShotResult") == "Goal", 1).otherwise(0)).alias("GA"),
        F.sum(F.when(on_target, F.col("ShotXG"))).alias("Known_xG_subtotal"),
        F.sum(F.when(on_target & F.col("ShotXG").isNull(), 1).otherwise(0))
        .alias("Missing_xG_count"),
    )


def calculate_goalkeeper_kpis(goalkeeper_shot_totals_df: DataFrame) -> DataFrame:
    """Add SA, SV_pct, xGa and xG_Diff to aggregate_goalkeeper_shots output.

    Preserves all totals, including GA. SA = Saves + GA; SV_pct is a fraction
    and null for zero SA. Team-approved xGa uses only Saved/Goal shots, matching
    SA, although Wisehockey distinguishes xGa from on-goal-only xGSA. Missing xG
    on a qualifying shot makes xGa and xG_Diff null; Known_xG_subtotal remains
    available for fallback display. Missing off-target xG has no effect.
    xG_Diff = xGa - GA. No known qualifying xG leaves the subtotal/xGa null.
    Input is numeric, one row per goalkeeper/team for a single match.
    """
    required = (
        "GoalkeeperId", "GoalkeeperTeam", "Shot_attempts", "Saves", "GA",
        "Known_xG_subtotal", "Missing_xG_count",
    )
    _require_event_columns(
        goalkeeper_shot_totals_df, required, "calculate_goalkeeper_kpis"
    )
    return goalkeeper_shot_totals_df.withColumn(
        "SA", F.col("Saves") + F.col("GA")
    ).withColumn(
        "SV_pct", F.when(F.col("SA") > 0, F.col("Saves") / F.col("SA"))
    ).withColumn(
        "xGa", F.when(F.col("Missing_xG_count") == 0, F.col("Known_xG_subtotal"))
    ).withColumn("xG_Diff", F.col("xGa") - F.col("GA"))


def calculate_fast_blueline_crossings(
    events_df: DataFrame, *, speed_threshold, crossing_direction=None
) -> DataFrame:
    """Count fast crossings per player/team for a single match.

    Ellie confirmed project velocities in m/s and settings speed_threshold=7,
    crossing_direction="TowardsOpponent" (7 m/s described in review as the 75th
    percentile). These are caller-supplied settings, not function defaults or
    a percentile recalculated here. Threshold is required, finite and
    nonnegative, in the input velocity unit. Qualification uses >=. Optional
    direction is an exact source-value filter, not an offensive-entry claim.
    TowardsOpponent is not a verified offensive-zone-entry classification.

    Output: EventPrimaryPlayerId, EventPrimaryTeam, Crossing_attempts,
    Fast_blueline_crossings, Missing_velocity_count. All selected players appear,
    even with no fast crossings. No matching slot or a null matched velocity is
    reported as missing and excluded from the fast count, never imputed as zero.
    Players with no selected crossings require a separate roster join.

    IDs must be consistently typed/normalized and velocities numeric upstream.
    Missing columns, null/blank primary IDs/teams, multiple matching slots, and
    nonfinite/negative matched velocities raise ValueError. Validation executes
    Spark actions on selected crossing rows. Unrelated slot IDs need not be
    unique; only multiple matches to the attributed player are ambiguous.
    """
    if (
        isinstance(speed_threshold, bool)
        or not isinstance(speed_threshold, (Real, Decimal))
        or not math.isfinite(speed_threshold)
        or speed_threshold < 0
    ):
        raise ValueError("speed_threshold must be a finite nonnegative number")
    if crossing_direction is not None and (
        not isinstance(crossing_direction, str) or not crossing_direction.strip()
    ):
        raise ValueError("crossing_direction must be a nonblank string or None")
    required = ["EventType", "EventPrimaryPlayerId", "EventPrimaryTeam"]
    if crossing_direction is not None:
        required.append("BluelineCrossingDirection")
    for i in range(1, 13):
        required.extend((f"StartPlayerId{i}", f"StartPlayerVelocity{i}"))
    _require_event_columns(events_df, tuple(required), "calculate_fast_blueline_crossings")
    for i in range(1, 13):
        name = f"StartPlayerVelocity{i}"
        if not isinstance(events_df.schema[name].dataType, NumericType):
            raise ValueError(f"{name} must have a numeric Spark type; convert upstream")
    crossings = events_df.filter(F.col("EventType") == "BluelineCrossing")
    if crossing_direction is not None:
        crossings = crossings.filter(F.col("BluelineCrossingDirection") == crossing_direction)
    slots = F.array(*[
        F.struct(F.col(f"StartPlayerId{i}").alias("id"),
                 F.col(f"StartPlayerVelocity{i}").cast("double").alias("velocity"))
        for i in range(1, 13)
    ])
    matches = F.filter(slots, lambda slot: slot["id"] == F.col("EventPrimaryPlayerId"))
    selected = crossings.select(
        "EventPrimaryPlayerId", "EventPrimaryTeam", matches.alias("_matches")
    )
    invalid = (
        ~_valid_identifier("EventPrimaryPlayerId")
        | ~_valid_identifier("EventPrimaryTeam")
        | (F.size("_matches") > 1)
    )
    if selected.filter(invalid).limit(1).count():
        raise ValueError("Invalid primary player ID/team or ambiguous duplicate player-slot matches")
    selected = selected.withColumn(
        "_velocity", F.try_element_at("_matches", F.lit(1))["velocity"]
    )
    velocity = F.col("_velocity")
    if selected.filter(
        velocity.isNotNull() & (
            F.isnan(velocity) | (F.abs(velocity) == float("inf")) | (velocity < 0)
        )
    ).limit(1).count():
        raise ValueError("Matched velocity must be finite and nonnegative, or null")
    return selected.groupBy("EventPrimaryPlayerId", "EventPrimaryTeam").agg(
        F.count(F.lit(1)).alias("Crossing_attempts"),
        F.sum(F.when(velocity >= float(speed_threshold), 1).otherwise(0))
        .alias("Fast_blueline_crossings"),
        F.sum(F.when(velocity.isNull(), 1).otherwise(0)).alias("Missing_velocity_count"),
    )
