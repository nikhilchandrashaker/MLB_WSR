"""Data integrity checks for the WSR archive."""
import pandas as pd

def validate_home_runs(df):
    issues = []
    if df.empty:
        issues.append("No home-run rows found.")
    if "hr_record_id" in df and df["hr_record_id"].duplicated().any():
        issues.append("Duplicate hr_record_id values exist.")
    if "wsr_classification" in df:
        allowed = {"WALL_SCRAPER","STANDARD","NO_DOUBTER","UNMODELED","REVIEW_REQUIRED"}
        bad = set(df["wsr_classification"].dropna().unique()) - allowed
        if bad:
            issues.append(f"Unknown WSR classes: {sorted(bad)}")
    if "parks_cleared" in df:
        vals = pd.to_numeric(df["parks_cleared"], errors="coerce").dropna()
        if not vals.between(1,30).all():
            issues.append("parks_cleared must be 1–30 when present.")
    if {"season","date"}.issubset(df.columns):
        years = pd.to_datetime(df["date"], errors="coerce").dt.year
        mismatch = years.notna() & df["season"].notna() & years.ne(pd.to_numeric(df["season"], errors="coerce"))
        if mismatch.any():
            issues.append("Season does not match date on one or more rows.")
    return issues
