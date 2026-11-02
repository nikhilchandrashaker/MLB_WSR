"""Historical coverage and missing-data report for the HR archive."""
from __future__ import annotations

import json

import pandas as pd

from .config import PROCESSED, RAW

TRACKING_FIELDS = {
    "launch_speed": ["exit_velocity_mph", "launch_speed"],
    "launch_angle": ["launch_angle_deg", "launch_angle"],
    "hit_coord_x": ["hit_coord_x", "hc_x"],
    "hit_coord_y": ["hit_coord_y", "hc_y"],
    "hit_distance": ["tracked_distance_ft", "hit_distance_sc"],
}
# Months in which an MLB regular season normally has games (2020 = Jul-Sep only).
EXPECTED_MONTHS = {"default": [4, 5, 6, 7, 8, 9], "2020": [7, 8, 9]}


def _col(df: pd.DataFrame, names: list[str]):
    for n in names:
        if n in df.columns:
            return df[n]
    return None


def coverage_tables(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (season_summary, month_gaps)."""
    d = df.copy()
    dates = pd.to_datetime(d["date"], errors="coerce")
    d["_season"] = dates.dt.year
    d["_month"] = dates.dt.month
    rows = []
    for season, g in d.groupby("_season"):
        row = {"season": int(season), "total_hr": len(g),
               "duplicate_hr_ids": int(g["hr_record_id"].duplicated().sum()) if "hr_record_id" in g else None}
        complete = pd.Series(True, index=g.index)
        for label, names in TRACKING_FIELDS.items():
            col = _col(g, names)
            if col is None:
                row[f"pct_missing_{label}"] = 100.0
                complete &= False
            else:
                row[f"pct_missing_{label}"] = round(100 * col.isna().mean(), 2)
                if label != "hit_distance":
                    complete &= col.notna()
        row["pct_tracking_core_complete"] = round(100 * complete.mean(), 2)
        rows.append(row)
    season_summary = pd.DataFrame(rows).sort_values("season")

    gaps = []
    present = d.groupby(["_season", "_month"]).size()
    for season in sorted(d["_season"].dropna().unique()):
        months = EXPECTED_MONTHS.get(str(int(season)), EXPECTED_MONTHS["default"])
        for m in months:
            if (season, m) not in present.index:
                gaps.append({"season": int(season), "month": m, "issue": "NO_HOME_RUNS_FOUND"})
    return season_summary, pd.DataFrame(gaps, columns=["season", "month", "issue"])


def write_coverage_report() -> str:
    """Write data/processed/coverage_by_season.csv and data/processed/DATA_COVERAGE.md."""
    path = PROCESSED / "home_runs.csv"
    if not path.exists():
        raise FileNotFoundError("Run ingest/normalize first.")
    df = pd.read_csv(path, low_memory=False)
    season_summary, gaps = coverage_tables(df)
    season_summary.to_csv(PROCESSED / "coverage_by_season.csv", index=False)

    manifest_path = RAW / "download_manifest.json"
    failed = []
    if manifest_path.exists():
        windows = json.loads(manifest_path.read_text()).get("windows", {})
        failed = [k for k, v in windows.items() if v.get("status") != "ok"]

    lines = ["# Data coverage report", "",
             f"Total home runs in archive: **{len(df):,}**", "",
             "## By season", "", "```", season_summary.to_string(index=False), "```", "",
             "## Month gaps (expected months with zero home runs)", ""]
    lines.append("```\n" + gaps.to_string(index=False) + "\n```" if not gaps.empty else "None.")
    lines += ["", "## Failed download windows (not in archive)", ""]
    lines.append("\n".join(f"- {k}" for k in failed) if failed else "None.")
    lines += ["", "Compare season totals against Baseball Savant's published HR leaderboard before using the archive.", ""]
    report = "\n".join(lines)
    (PROCESSED / "DATA_COVERAGE.md").write_text(report)
    print(report)
    return report
