"""WSR classification logic and an intentionally conservative simulation interface."""
from __future__ import annotations
import pandas as pd

def classify_parks_cleared(k):
    if pd.isna(k):
        return "UNMODELED"
    k = int(k)
    if k < 1 or k > 30:
        return "REVIEW_REQUIRED"
    if k <= 5:
        return "WALL_SCRAPER"
    if k <= 29:
        return "STANDARD"
    return "NO_DOUBTER"

def attach_classifications(home_runs: pd.DataFrame, simulations: pd.DataFrame):
    """Attach results only if every required park outcome is known for that HR.

    Required simulation columns: hr_record_id, park_id, would_be_home_run.
    Exactly 30 distinct parks must be present per HR.
    """
    required = {"hr_record_id","park_id","would_be_home_run"}
    if not required.issubset(simulations.columns):
        raise ValueError(f"Simulation table requires {sorted(required)}")
    rows = []
    for hr_id, group in simulations.groupby("hr_record_id"):
        if group["park_id"].nunique() != 30 or group["would_be_home_run"].isna().any():
            rows.append((hr_id, pd.NA, "UNMODELED"))
            continue
        k = int(group.drop_duplicates("park_id")["would_be_home_run"].astype(bool).sum())
        rows.append((hr_id, k, classify_parks_cleared(k)))
    result = pd.DataFrame(rows, columns=["hr_record_id","parks_cleared","wsr_classification"])
    out = home_runs.drop(columns=["parks_cleared","wsr_classification"], errors="ignore").merge(
        result, on="hr_record_id", how="left"
    )
    out["wsr_classification"] = out["wsr_classification"].fillna("UNMODELED")
    return out
