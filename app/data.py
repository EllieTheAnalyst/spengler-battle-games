"""Data for the app: reads the YAML config and gold."""
from pathlib import Path
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]          # project folder (one level above app/)
CONFIG = ROOT / "config" / "keyplayer_battle.yaml"


def load_config() -> dict:
    """The whole YAML as a dict."""
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def load_gold(cfg: dict) -> pd.DataFrame:
    """Gold player metrics for the active game (one row per player)."""
    year, game = cfg["active_game"]["year"], cfg["active_game"]["game"]
    path = cfg["data"]["gold"]["player_metrics"].format(year=year, game=game)
    return pd.read_parquet(ROOT / cfg["data"]["root"] / path)
def _value(v):
    """Gold value → plain Python number, or None if missing."""
    return None if pd.isna(v) else float(v)


def _leader(a, b, higher_is_better: bool):
    """0 = first player is better, 1 = second, None = tie or missing."""
    if a is None or b is None or a == b:
        return None
    first_better = a > b if higher_is_better else a < b
    return 0 if first_better else 1


def load_battle(cfg: dict, gold: pd.DataFrame, battle_id: str) -> dict:
    """Everything one battle screen needs: question, both players, stats with labels."""
    battle = next((b for b in cfg["battles"] if b["battle_id"] == battle_id), None)
    if battle is None:
        raise ValueError(f"Unknown battle: {battle_id}")
    category = cfg["categories"][battle["category"]]
    rows = gold.set_index("player_id").loc[battle["player_ids"]]   # keeps the YAML order

    players = [{"player_id": int(pid), "name": r["name"], "team": r["Team"]}
               for pid, r in rows.iterrows()]

    stats = []
    for key in category["metrics"]:
        m = cfg["metrics"][key]
        values = [_value(v) for v in rows[m["column"]]]
        notes = [None, None]

        # Missing xG: use the known subtotal + a note (missing_data in YAML)
        rule = cfg.get("missing_data", {}).get(key)
        if rule and rule.get("when_shot_xg_missing") == "use_known_subtotal":
            for i, (_, r) in enumerate(rows.iterrows()):
                if r["Missing_xG_count"] > 0:
                    values[i] = _value(r["Known_xG_subtotal"])
                    notes[i] = rule["show_note"].format(Missing_xG_count=int(r["Missing_xG_count"]))

        a, b = values
        stats.append({
            "key": key,
            "label": m["label"],
            "unit": m["unit"],
            "higher_is_better": m["higher_is_better"],
            "values": [a, b],
            "notes": notes,
            "leader": _leader(a, b, m["higher_is_better"]),
        })

    return {"battle_id": battle_id, "title": category["title"],
            "question": category["question"], "players": players, "stats": stats}