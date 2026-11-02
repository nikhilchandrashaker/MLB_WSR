"""Player/team season and career WSR summaries."""
import pandas as pd
from .config import PROCESSED

CLASSES = ["WALL_SCRAPER","STANDARD","NO_DOUBTER"]
def _summarize(df, keys):
    work = df.copy()
    work["is_wall_scraper"] = work["wsr_classification"].eq("WALL_SCRAPER").astype(int)
    work["is_standard"] = work["wsr_classification"].eq("STANDARD").astype(int)
    work["is_no_doubter"] = work["wsr_classification"].eq("NO_DOUBTER").astype(int)
    work["is_modeled"] = work["wsr_classification"].isin(CLASSES).astype(int)
    out = work.groupby(keys, dropna=False).agg(
        total_hr=("hr_record_id","count"),
        wall_scraper_hr=("is_wall_scraper","sum"),
        standard_hr=("is_standard","sum"),
        no_doubter_hr=("is_no_doubter","sum"),
        modeled_hr=("is_modeled","sum")
    ).reset_index()
    out["unmodeled_hr"] = out["total_hr"] - out["modeled_hr"]
    out["wsr_pct"] = (100*out["wall_scraper_hr"]/out["total_hr"]).round(2).where(out["modeled_hr"].eq(out["total_hr"]))
    out["modeled_wsr_pct"] = (100*out["wall_scraper_hr"]/out["modeled_hr"]).round(2).where(out["modeled_hr"].gt(0))
    out["model_coverage_pct"] = (100*out["modeled_hr"]/out["total_hr"]).round(2)
    return out

def build_summaries(df):
    PROCESSED.mkdir(parents=True, exist_ok=True)
    player_keys = [c for c in ["season","batter_id","player_name"] if c in df.columns]
    if not {"season","batter_id"}.issubset(player_keys):
        raise ValueError("Normalized data must include season and batter_id.")
    player = _summarize(df, player_keys)
    player.to_csv(PROCESSED/"player_season_wsr.csv", index=False)
    career_keys = [c for c in ["batter_id","player_name"] if c in df.columns]
    career = _summarize(df, career_keys)
    career.to_csv(PROCESSED/"player_career_wsr.csv", index=False)
    if "batting_team" in df:
        team = _summarize(df, ["season","batting_team"])
        team.to_csv(PROCESSED/"team_season_wsr.csv", index=False)
    return player
