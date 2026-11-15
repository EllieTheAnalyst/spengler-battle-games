# Spengler Battle Games

A mobile fan app that makes hockey stats engaging for new fans. Built for SIC DataHack 2026 (Spengler Cup, Davos).

- **Live prototype:** https://sprengler-battle-games.lovable.app

## Idea

Fans pick between two players in a battle (e.g. *"Who was the most dangerous player tonight?"*), first on instinct, then after seeing the real stats in plain words. They can keep or switch their pick, vote, and see how other fans voted.

The prototype covers one game, HC Davos vs U.S. Collegiate Selects (31 December 2025), with three battles: Greatest Teamplayer, Most Dangerous Player and Best Goalkeeper.

## Architecture

```
Raw CSVs → bronze → silver → gold (PySpark) → app/data.py (pandas) → battles.json → Lovable app
```

- **Bronze:** raw event and statistics data
- **Silver:** cleaned, typed, players linked, home/away and goalies derived
- **Gold:** one row per player with role and all KPIs
- **YAML config:** single source of rules: metrics, fan labels, categories, battles
- **`load_battle()`:** returns everything one battle screen needs (players, stats, labels, leader)

## Repository

```
app/        data.py (data layer), metrics.py (KPIs), app.py (first Streamlit draft)
config/     keyplayer_battle.yaml
pipeline/   bronze_to_silver, silver_to_gold, run_pipeline notebooks + utility.py
tests/      51 unit tests
```

## Run it

Requirements: Python 3.11, Java 17.

```bash
pip install -r requirements.txt
```

The raw game data is not included (provided for the DataHack only). Place the CSVs in `data/bronze/events/year=2025/game=11/` and `data/bronze/stats/year=2025/game=11/`, then run `pipeline/run_pipeline.ipynb`.

Export the battles for the app:

```bash
python -c "import json; from app.data import *; cfg = load_config(); g = load_gold(cfg); json.dump([load_battle(cfg, g, b['battle_id']) for b in cfg['battles']], open('battles.json', 'w'), indent=2)"
```

## Tests

```bash
python -m unittest discover -s tests
```

51 tests cover cleaning edge cases, full-match reconciliation against the original data (e.g. 112 shots), config consistency and the app data layer. Tests needing the real data skip when it is absent.

A new battle needs no code: add three lines (`battle_id`, `category`, `player_ids`) to the YAML.

## Status

- Done: tested pipeline, fan-friendly labels, app data layer, Lovable prototype with real game stats.
- Demo only: fan vote percentages.
- Next: build our own frontend (replacing the Lovable prototype) directly on the data layer, then more games, persistent voting and 1–3 stats per battle

## Team

- Ellie (data pipeline, backend, project management)
- Fara (KPIs, Streamlit prototype)
- Aïda (UX/UI, user testing, Lovable prototype)
