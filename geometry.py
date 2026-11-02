"""Park geometry intake: compact per-park measurements -> 19-bin wall profiles.

Input  : data/reference/park_geometry_inputs.csv  (one row per park x season range)
Output : data/reference/park_wall_profiles.csv    (park_id x season range x 19 spray bins)

Anchor points are the five standard marked distances at spray angles -45 (LF pole),
-22.5 (left-center), 0 (center), +22.5 (right-center) and +45 (RF pole). Bins between
anchors are linearly interpolated and tagged ``profile_method=INTERPOLATED_5PT``; wall
irregularities that sit between anchors (e.g. Green Monster's shape, Crawford Boxes,
Tal's Hill, Oracle Park's triples alley) are NOT captured until extra anchor columns
are supplied. Status gating: only rows with status VERIFIED flow into official results.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import REFERENCE

ANCHORS = [-45.0, -22.5, 0.0, 22.5, 45.0]
DIST_COLS = ["lf_line_ft", "lcf_ft", "cf_ft", "rcf_ft", "rf_line_ft"]
HT_COLS = ["wall_ht_lf_ft", "wall_ht_lcf_ft", "wall_ht_cf_ft", "wall_ht_rcf_ft", "wall_ht_rf_ft"]
BINS = np.arange(-45, 46, 5)
REQUIRED = ["park_id", "club", "venue_name", "season_start", "season_end", *DIST_COLS, *HT_COLS,
            "source_url", "status"]
OUT_COLS = ["park_id", "club", "venue_reference_name", "season_start", "season_end", "spray_angle_deg",
            "wall_distance_ft", "wall_height_ft", "foul_pole_or_corner_flag", "geometry_source_url",
            "geometry_verified_by", "geometry_verification_date", "geometry_status", "profile_method"]


def build_profiles(inputs: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in REQUIRED if c not in inputs.columns]
    if missing:
        raise ValueError(f"geometry inputs missing columns: {missing}")
    rows = []
    for _, r in inputs.iterrows():
        d = pd.to_numeric(r[DIST_COLS], errors="coerce").to_numpy(float)
        h = pd.to_numeric(r[HT_COLS], errors="coerce").to_numpy(float)
        # Sources often give wall height only at LF/CF/RF; fill the gaps by averaging neighbors.
        if np.isnan(h[1]) and not np.isnan(h[[0, 2]]).any():
            h[1] = h[[0, 2]].mean()
        if np.isnan(h[3]) and not np.isnan(h[[2, 4]]).any():
            h[3] = h[[2, 4]].mean()
        status = str(r["status"]).strip().upper()
        if np.isnan(d).any() or np.isnan(h).any() or not str(r["source_url"]).startswith("http"):
            status = "MISSING_VERIFIED_MEASUREMENT"
        if (d < 250).any() or (d > 520).any() or (h < 2).any() or (h > 60).any():
            raise ValueError(f"implausible geometry for {r['park_id']} {r['season_start']}-{r['season_end']}")
        dist = np.interp(BINS, ANCHORS, np.nan_to_num(d)) if status != "MISSING_VERIFIED_MEASUREMENT" else np.full(len(BINS), np.nan)
        ht = np.interp(BINS, ANCHORS, np.nan_to_num(h)) if status != "MISSING_VERIFIED_MEASUREMENT" else np.full(len(BINS), np.nan)
        for a, wd, wh in zip(BINS, dist, ht):
            rows.append({
                "park_id": r["park_id"], "club": r["club"], "venue_reference_name": r["venue_name"],
                "season_start": r["season_start"], "season_end": r["season_end"], "spray_angle_deg": int(a),
                "wall_distance_ft": wd, "wall_height_ft": wh,
                "foul_pole_or_corner_flag": "POLE" if abs(a) == 45 else "",
                "geometry_source_url": r["source_url"], "geometry_verified_by": r.get("verified_by", ""),
                "geometry_verification_date": r.get("verification_date", ""),
                "geometry_status": status, "profile_method": "INTERPOLATED_5PT",
            })
    return pd.DataFrame(rows, columns=OUT_COLS)


def build_profiles_file() -> pd.DataFrame:
    src = REFERENCE / "park_geometry_inputs.csv"
    if not src.exists():
        raise FileNotFoundError(f"Fill in {src} (see park_geometry_inputs_template.csv).")
    out = build_profiles(pd.read_csv(src))
    out.to_csv(REFERENCE / "park_wall_profiles.csv", index=False)
    return out


def season_park_arrays(profiles: pd.DataFrame, season: int, park_ids: list[str], allowed=("VERIFIED",)):
    """Return {park_id: (angles, dist, height)} or None for any park lacking allowed geometry."""
    out = {}
    for pid in park_ids:
        p = profiles[(profiles.park_id.astype(str) == str(pid))
                     & (pd.to_numeric(profiles.season_start, errors="coerce") <= season)
                     & (pd.to_numeric(profiles.season_end, errors="coerce") >= season)]
        if p.empty or not p.geometry_status.astype(str).isin(allowed).all():
            out[pid] = None
            continue
        p = p.dropna(subset=["wall_distance_ft", "wall_height_ft"]).sort_values("spray_angle_deg")
        out[pid] = None if len(p) < 2 else (p.spray_angle_deg.to_numpy(float),
                                            p.wall_distance_ft.to_numpy(float),
                                            p.wall_height_ft.to_numpy(float))
    return out
