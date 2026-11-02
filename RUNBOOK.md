# Runbook: from empty repo to WSR results

1. `pip install -r requirements.txt`
2. `python run_pipeline.py ingest --start-year 2015 --end-year 2026` then `python run_pipeline.py coverage`; check season totals vs Savant.
3. Geometry: review `data/reference/park_geometry_candidates_UNVERIFIED.csv` (29 current parks, one secondary source, undated, some estimated). Verify each park/season against primary or official sources, add rows for Oakland Coliseum, Sutter Health Park, Steinbrenner Field, Globe Life Park (Arlington), and every season range where fences moved, then copy to `park_geometry_inputs.csv` with `status=VERIFIED`, `source_url`, `verified_by`, `verification_date`. Run `python run_pipeline.py geometry`.
4. Copy `team_park_seasons_template.csv` to `team_park_seasons.csv`; for each season map 30 teams to physical parks, `mapping_status=VERIFIED`.
5. `python run_pipeline.py model` (use `--allow-provisional` for a clearly-labeled preview).
6. `python run_pipeline.py sensitivity`, then `python run_pipeline.py figures`.
7. Write up using the validation checklist in METHODOLOGY section 9. Publish leaderboards only for rows with 100% model coverage and the minimum HR count.

## No local machine? Use GitHub Actions
1. Create a new GitHub repo and upload this project's contents (drag the folder into the web uploader).
2. Repo > Actions > "Download Statcast home runs" > Run workflow.
3. When it finishes (minutes), download the `wsr-statcast-data` artifact or pull the committed `data/` folder, and send it back to Claude to continue with geometry, model, and results.
