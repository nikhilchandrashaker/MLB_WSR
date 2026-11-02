
"""Park-wall evaluator for an externally generated, calibrated ball trajectory.

This module does not invent a flight path from EV/LA. It evaluates a supplied
trajectory against a season-specific wall profile. Trajectory points must be
ordered from the plate toward the outfield and expressed as radial distance
from home plate (ft) and ball height above ground (ft).
"""
from __future__ import annotations
import numpy as np
import pandas as pd

REQUIRED_PROFILE = {"park_id","season_start","season_end","spray_angle_deg",
                    "wall_distance_ft","wall_height_ft","geometry_status"}

def evaluate_trajectory_in_park(trajectory: pd.DataFrame, profile: pd.DataFrame,
                                park_id: str, season: int, spray_angle_deg: float):
    """Return True/False only when trajectory and park geometry are complete."""
    if not {"distance_ft","height_ft"}.issubset(trajectory.columns):
        return None
    if not REQUIRED_PROFILE.issubset(profile.columns):
        return None
    p = profile.loc[
        (profile.park_id.astype(str) == str(park_id)) &
        (pd.to_numeric(profile.season_start, errors="coerce") <= season) &
        (pd.to_numeric(profile.season_end, errors="coerce") >= season)
    ].copy()
    if p.empty or not p.geometry_status.astype(str).eq("VERIFIED").all():
        return None
    p["spray_angle_deg"] = pd.to_numeric(p["spray_angle_deg"], errors="coerce")
    p["wall_distance_ft"] = pd.to_numeric(p["wall_distance_ft"], errors="coerce")
    p["wall_height_ft"] = pd.to_numeric(p["wall_height_ft"], errors="coerce")
    p = p.dropna(subset=["spray_angle_deg","wall_distance_ft","wall_height_ft"])
    if len(p) < 2:
        return None
    angles = p["spray_angle_deg"].to_numpy(float)
    if spray_angle_deg < angles.min() or spray_angle_deg > angles.max():
        return None
    wall_dist = float(np.interp(spray_angle_deg, angles, p["wall_distance_ft"]))
    wall_height = float(np.interp(spray_angle_deg, angles, p["wall_height_ft"]))
    t = trajectory.sort_values("distance_ft")
    d = pd.to_numeric(t.distance_ft, errors="coerce").to_numpy(float)
    h = pd.to_numeric(t.height_ft, errors="coerce").to_numpy(float)
    valid = np.isfinite(d) & np.isfinite(h)
    d, h = d[valid], h[valid]
    if len(d) < 2 or np.any(np.diff(d) < 0):
        return None
    # Interpolate ball height exactly at the wall plane. If the ball lands before
    # reaching the wall, it cannot clear the fence.
    if d.max() < wall_dist:
        return False
    height_at_wall = float(np.interp(wall_dist, d, h))
    return bool(height_at_wall > wall_height)

def simulate_all_parks(hr_row, trajectory, profiles, expected_park_ids):
    """Return one row per park; missing/incomplete inputs remain UNMODELED."""
    season = int(hr_row["season"])
    spray = float(hr_row["spray_angle_deg"])
    hr_id = str(hr_row["hr_record_id"])
    output = []
    for park_id in expected_park_ids:
        result = evaluate_trajectory_in_park(trajectory, profiles, park_id, season, spray)
        output.append({
            "hr_record_id": hr_id, "park_id": park_id, "season": season,
            "would_be_home_run": result,
            "simulation_status": "MODELED_WITH_SUPPLIED_TRAJECTORY" if result is not None else "UNMODELED_MISSING_OR_UNVERIFIED_INPUT"
        })
    return pd.DataFrame(output)


def run_simulation_pipeline():
    """Run park tests from user-supplied trajectory, spray-angle, and geometry files."""
    from pathlib import Path
    from .config import PROCESSED, REFERENCE
    from .classify import attach_classifications
    from .aggregate import build_summaries

    hr_path = PROCESSED / "home_runs.csv"
    traj_path = PROCESSED / "trajectory_points.csv"
    spray_path = PROCESSED / "spray_angles.csv"
    profile_path = REFERENCE / "park_wall_profiles_template.csv"
    park_path = REFERENCE / "team_park_seasons.csv"
    for path in [hr_path, traj_path, spray_path, profile_path, park_path]:
        if not path.exists():
            raise FileNotFoundError(f"Required simulation input missing: {path}")

    hrs = pd.read_csv(hr_path, low_memory=False)
    trajectories = pd.read_csv(traj_path)
    sprays = pd.read_csv(spray_path)
    profiles = pd.read_csv(profile_path)
    park_map = pd.read_csv(park_path)
    if "calibration_status" not in sprays or not sprays["calibration_status"].astype(str).eq("VERIFIED").all():
        raise ValueError("Every spray angle must have calibration_status=VERIFIED.")
    if not {"hr_record_id","spray_angle_deg"}.issubset(sprays.columns):
        raise ValueError("spray_angles.csv needs hr_record_id and spray_angle_deg.")
    if not {"season","team_id","park_id","venue_name","mapping_status"}.issubset(park_map.columns):
        raise ValueError("team_park_seasons.csv needs season, team_id, park_id, venue_name, mapping_status.")
    if not {"hr_record_id","distance_ft","height_ft"}.issubset(trajectories.columns):
        raise ValueError("trajectory_points.csv needs hr_record_id, distance_ft, height_ft.")

    all_sims = []
    for _, hr in hrs.iterrows():
        hr_id = str(hr["hr_record_id"])
        t = trajectories.loc[trajectories.hr_record_id.astype(str).eq(hr_id)]
        s = sprays.loc[sprays.hr_record_id.astype(str).eq(hr_id)]
        if t.empty or len(s) != 1:
            all_sims.append(pd.DataFrame([{
                "hr_record_id":hr_id,"park_id":pid,"season":hr["season"],
                "would_be_home_run":pd.NA,"simulation_status":"UNMODELED_MISSING_TRAJECTORY_OR_SPRAY"
            } for pid in [f"UNMODELED_PARK_{i+1}" for i in range(30)]]))
            continue
        row = hr.to_dict()
        row["spray_angle_deg"] = float(s.iloc[0]["spray_angle_deg"])
        season_map = park_map.loc[pd.to_numeric(park_map["season"], errors="coerce").eq(int(hr["season"]))]
        verified_map = season_map.loc[
            season_map["mapping_status"].astype(str).eq("VERIFIED") &
            season_map["park_id"].notna() & season_map["park_id"].astype(str).ne("")
        ]
        park_ids = verified_map["park_id"].astype(str).drop_duplicates().tolist()
        if len(park_ids) != 30 or len(verified_map) != 30:
            all_sims.append(pd.DataFrame([{
                "hr_record_id":hr_id,"park_id":f"UNMODELED_PARK_MAPPING_{i+1}","season":hr["season"],
                "would_be_home_run":pd.NA,"simulation_status":"UNMODELED_SEASON_PARK_MAPPING_NOT_VERIFIED"
            } for i in range(30)]))
            continue
        all_sims.append(simulate_all_parks(row, t, profiles, park_ids))
    sims = pd.concat(all_sims, ignore_index=True) if all_sims else pd.DataFrame()
    sims.to_csv(PROCESSED/"park_simulations.csv", index=False)
    classified = attach_classifications(hrs, sims)
    classified.to_csv(hr_path, index=False)
    build_summaries(classified)
    print(f"Saved park simulations for {len(hrs):,} HRs. Unmodeled results remain explicit.")
    return sims
