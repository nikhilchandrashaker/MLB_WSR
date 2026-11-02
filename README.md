# Wall-Scraper Rate (WSR): Complete Research Project

**Target coverage:** 2015–2026 (2026 is year-to-date when downloaded).  
**Purpose:** create an auditable, park-adjusted MLB home-run classification and player leaderboard.

> **Data-integrity notice:** This repository is a complete, runnable research pipeline and schema package. It does not pretend that a historical Statcast download or verified 30-park wall survey has already been completed. The raw and processed data folders start empty. Run the ingestion command to populate them. The park wall profile template must be populated from verified, season-specific geometry before official classifications can be produced.

## Definition

For each home run, count the number of MLB parks in which its modeled trajectory clears the outfield wall:

- `WALL_SCRAPER`: clears in 1–5 parks
- `STANDARD`: clears in 6–29 parks
- `NO_DOUBTER`: clears in all 30 parks
- `UNMODELED`: insufficient tracking, geometry, or validated trajectory

Player-season rate:

`WSR% = 100 × WALL_SCRAPER HR / Total HR`

Always publish `modeled_hr` and `model_coverage_pct` beside WSR%. Do not quietly remove unmodeled HR from the denominator.

## Included

- Statcast historical downloader (2015 through current date; chunked, resumable)
- Raw source archive and normalized one-row-per-HR output
- Player-season and team-season leaderboard builder
- Park directory for all 30 MLB clubs
- Park wall-profile template (30 parks × 19 spray-angle bins)
- Park-wall evaluator that tests a supplied trajectory against season-specific wall profiles
- Conservative classification rules
- Data-quality checks and unit tests
- Data dictionary, methodology, reproducibility and research-paper outline
- Synthetic example clearly separated from real MLB data

## Quick start

Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Download all available Statcast home-run events from 2015 through 2026-to-date
python run_pipeline.py ingest --start-year 2015 --end-year 2026

# Build summary files (will show unmodeled HR until the park model is calibrated)
python run_pipeline.py summarize

# Run tests
python -m pytest
```

The default `savant` engine asks Baseball Savant for home runs only, one calendar month at a time (about 100 requests for 2015–2026, minutes rather than hours). Every raw response is archived untouched in `data/raw/chunks/`, completed months are skipped on restart, the still-open current month is always refreshed, and any response that hits Savant's 25,000-row cap is split automatically. Failed months are listed in `data/raw/download_manifest.json` and in the coverage report. Use `--game-types R,F,D,L,W` to add postseason, or `--engine pybaseball` for the legacy all-pitch pull. Do not launch multiple simultaneous downloads.

After ingest, `python run_pipeline.py coverage` writes `data/processed/coverage_by_season.csv` and `DATA_COVERAGE.md` (HR counts, missing tracking fields, empty months, failed windows). Compare season totals to Savant's published leaderboard before trusting the archive.

## Critical modeling requirements

The public Statcast feed supplies useful fields such as game date, batter, pitcher, event, launch speed, launch angle, hit coordinates, and hit distance. It does **not** hand us a complete 3D batted-ball trajectory plus a verified 30-park geometry table. `hc_x/hc_y` are hit-location coordinates, not a universally documented spray-angle field.

For defensible WSR classification, the project requires:
1. a calibrated trajectory/carry model (or full tracked 3D trajectory),
2. park wall distances and heights by spray angle,
3. foul-pole/corner handling and park coordinate transforms,
4. a declared policy for altitude, weather, roof, and ball conditions,
5. validation against observed outcomes and sensitivity analysis.

Until those inputs are present and validated, the correct result is `UNMODELED`, not a guessed class. A synthetic test fixture verifies code mechanics only; it is not MLB evidence.

## Output files

| File | Contents |
|---|---|
| `data/raw/statcast_home_runs.csv` | Downloaded Statcast source rows |
| `data/processed/home_runs.csv` | Normalized one-row-per-HR records |
| `data/processed/park_simulations.csv` | HR × park results, only when model inputs exist |
| `data/processed/player_season_wsr.csv` | Player-season totals, classifications, WSR, coverage |
| `data/processed/team_season_wsr.csv` | Team-season equivalents |
| `data/processed/player_career_wsr.csv` | Career totals across downloaded seasons |
| `data/reference/mlb_park_directory.csv` | Team/park identity register |
| `data/reference/park_wall_profiles_template.csv` | Empty season-specific geometry template |

## Reproducibility

Every output carries the source and model status. Preserve the raw Statcast file and retrieval timestamp. The source may be revised. Record package versions, download date, geometry sources, model parameters, and validation results in any publication.

## Built-in model run (recommended)

`python run_pipeline.py geometry` -> `model` -> `sensitivity` -> `figures`. See `docs/RUNBOOK.md` and METHODOLOGY section 9. The legacy `simulate` command (externally supplied trajectories) is retained below.

## Simulation stage (externally supplied trajectories)

The simulation command requires three research inputs that cannot responsibly be fabricated:

- `data/processed/trajectory_points.csv`: one or more ordered rows per `hr_record_id`, with `distance_ft` and `height_ft` generated by a calibrated trajectory model.
- `data/processed/spray_angles.csv`: one verified `spray_angle_deg` per HR, derived using a documented coordinate transform; `calibration_status` must equal `VERIFIED`.
- `data/reference/park_wall_profiles_template.csv`: complete wall distance and height profiles for each park, season, and spray angle; geometry rows must have `geometry_status=VERIFIED`.

After those are populated, run:

```bash
python run_pipeline.py simulate
```

This evaluates each trajectory against all 30 park profiles, classifies only complete 30-park results, and rebuilds the player/team/career leaderboards. Missing inputs remain `UNMODELED`.

A fourth required input is `data/reference/team_park_seasons.csv`, copied from `team_park_seasons_template.csv`. It must map exactly 30 teams to 30 verified physical parks for each season. This is essential because clubs can use temporary venues, move, or change park configurations across 2015–2026. Franchise IDs must not be mistaken for permanent stadium IDs.
