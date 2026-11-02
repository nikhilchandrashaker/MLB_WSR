"""Normalize raw Statcast home-run rows without fabricating missing measurements."""
import pandas as pd
from .config import RAW, PROCESSED

ALIASES = {
    "game_date":"date", "game_year":"season", "batter":"batter_id",
    "pitcher":"pitcher_id", "launch_speed":"exit_velocity_mph",
    "launch_angle":"launch_angle_deg", "hit_distance_sc":"tracked_distance_ft",
    "hit_distance":"tracked_distance_ft", "hc_x":"hit_coord_x", "hc_y":"hit_coord_y"
}
# Statcast team abbreviations -> franchise codes used in data/reference/mlb_park_directory.csv.
# Franchise code is NOT a park id (see METHODOLOGY section 8).
TEAM_CODE_MAP = {"AZ": "ARI", "CWS": "CHW", "OAK": "ATH", "WSN": "WSH", "KCR": "KC",
                 "SDP": "SD", "SFG": "SF", "TBR": "TB"}

def normalize(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    # Resolve duplicate aliases safely; prefer Statcast's hit_distance_sc when available.
    for old, new in ALIASES.items():
        if old in df.columns and new not in df.columns:
            df = df.rename(columns={old:new})
    if "date" in df:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        df["season"] = pd.to_datetime(df["date"], errors="coerce").dt.year.astype("Int64")
    # Batting side's team is inferred from inning half, not always the home team.
    if {"inning_topbot","home_team","away_team"}.issubset(df.columns):
        df["batting_team"] = df["home_team"].where(
            df["inning_topbot"].astype(str).str.lower().eq("bot"), df["away_team"]
        )
    for col in ["home_team", "away_team", "batting_team"]:
        if col in df.columns:
            df[f"{col}_franchise"] = df[col].astype("string").replace(TEAM_CODE_MAP)
    df["tracking_core_complete"] = df.reindex(
        columns=["exit_velocity_mph","launch_angle_deg","hit_coord_x","hit_coord_y"]
    ).notna().all(axis=1)
    df["parks_cleared"] = pd.Series(pd.NA, index=df.index, dtype="Int64")
    df["wsr_classification"] = "UNMODELED"
    df["model_status"] = "PENDING_VALIDATED_TRAJECTORY_AND_PARK_GEOMETRY"
    df["hr_record_id"] = (
        df.get("game_pk", pd.Series(index=df.index, dtype="object")).astype(str) + "_" +
        df.get("at_bat_number", pd.Series(index=df.index, dtype="object")).astype(str) + "_" +
        df.get("batter_id", pd.Series(index=df.index, dtype="object")).astype(str)
    )
    return df

def normalize_file():
    raw_path = RAW / "statcast_home_runs.csv"
    if not raw_path.exists():
        raise FileNotFoundError("Run the ingest command first.")
    df = normalize(pd.read_csv(raw_path, low_memory=False))
    PROCESSED.mkdir(parents=True, exist_ok=True)
    df.to_csv(PROCESSED / "home_runs.csv", index=False)
    return df
