"""End-to-end WSR model run: spray angle -> fitted trajectory -> 30-park evaluation -> classes.

    python run_pipeline.py model [--allow-provisional]

Official outputs are produced ONLY when every park-season used has geometry_status=VERIFIED and
season-park mapping_status=VERIFIED. With --allow-provisional, results go to data/processed/provisional/
and are labeled PROVISIONAL; nothing official is overwritten.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import flight
from .aggregate import build_summaries
from .classify import classify_parks_cleared
from .config import PROCESSED, REFERENCE
from .geometry import season_park_arrays

GRID_STEP = 2.0
GRID = np.arange(0.0, 620.0 + GRID_STEP, GRID_STEP)
BATCH = 3000


def _height_at(hgrid: np.ndarray, wall_d: np.ndarray) -> np.ndarray:
    """Linear interpolation of per-HR height grids at per-HR wall distances (both length N)."""
    pos = np.clip(wall_d / GRID_STEP, 0, len(GRID) - 1.001)
    i = pos.astype(int); f = pos - i
    r = np.arange(len(wall_d))
    h0, h1 = hgrid[r, i], hgrid[r, i + 1]
    with np.errstate(invalid="ignore"):
        out = h0 + f * (h1 - h0)
    out[~np.isfinite(h0) | ~np.isfinite(h1)] = -np.inf
    return out


def load_inputs(allow_provisional: bool):
    hrs = pd.read_csv(PROCESSED / "home_runs.csv", low_memory=False)
    prof_path = REFERENCE / "park_wall_profiles.csv"
    if not prof_path.exists():
        prof_path = REFERENCE / "park_wall_profiles_template.csv"
    profiles = pd.read_csv(prof_path)
    pm_path = REFERENCE / "team_park_seasons.csv"
    park_map = pd.read_csv(pm_path) if pm_path.exists() else pd.DataFrame()
    env_path = REFERENCE / "park_environment.csv"
    env = pd.read_csv(env_path) if env_path.exists() else pd.DataFrame(columns=["park_id", "altitude_ft"])
    return hrs, profiles, park_map, env


def run_model(allow_provisional: bool = False, max_hr: int | None = None):
    hrs, profiles, park_map, env = load_inputs(allow_provisional)
    if max_hr:
        hrs = hrs.head(max_hr).copy()
    allowed = ("VERIFIED", "PROVISIONAL") if allow_provisional else ("VERIFIED",)
    outdir = PROCESSED / ("provisional" if allow_provisional else "")
    outdir.mkdir(parents=True, exist_ok=True)

    ev = pd.to_numeric(hrs.get("exit_velocity_mph", hrs.get("launch_speed")), errors="coerce").to_numpy(float)
    la = pd.to_numeric(hrs.get("launch_angle_deg", hrs.get("launch_angle")), errors="coerce").to_numpy(float)
    dist = pd.to_numeric(hrs.get("tracked_distance_ft", hrs.get("hit_distance_sc")), errors="coerce").to_numpy(float)
    hcx = pd.to_numeric(hrs.get("hit_coord_x", hrs.get("hc_x")), errors="coerce").to_numpy(float)
    hcy = pd.to_numeric(hrs.get("hit_coord_y", hrs.get("hc_y")), errors="coerce").to_numpy(float)
    spray = flight.spray_angle_deg(hcx, hcy)

    fair = np.isfinite(spray)
    fair_share = np.mean(np.abs(spray[fair]) <= 45.5) if fair.any() else 0.0
    spray_ok = fair & (np.abs(spray) <= 45.5)
    spray_status = np.where(spray_ok, "VERIFIED", "OUT_OF_FAIR_TERRITORY_OR_MISSING")
    pd.DataFrame({"hr_record_id": hrs.hr_record_id, "spray_angle_deg": spray,
                  "calibration_status": spray_status}).to_csv(outdir / "spray_angles.csv", index=False)

    cd = flight.calibrate_cd(ev, la, dist)
    rpm, fit_status = flight.fit_backspin(ev, la, dist, cd=cd)
    fit_ok = fit_status == "OK"
    print(f"cd={cd:.3f}; spray in-fair share={fair_share:.3%}; spin fit OK for {fit_ok.mean():.2%} of HRs")

    seasons = pd.to_numeric(hrs["season"], errors="coerce").to_numpy()
    sim_rows = []
    status_by_hr = np.array(["UNMODELED_TRACKING_OR_FIT"] * len(hrs), dtype=object)
    for season in sorted(set(seasons[np.isfinite(seasons)])):
        season = int(season)
        smap = park_map[(pd.to_numeric(park_map.get("season"), errors="coerce") == season)] if len(park_map) else park_map
        smap = smap[(smap.get("mapping_status", pd.Series(dtype=str)).astype(str) == "VERIFIED")] if len(smap) else smap
        park_ids = smap["park_id"].astype(str).drop_duplicates().tolist() if len(smap) else []
        arrays = season_park_arrays(profiles, season, park_ids, allowed) if park_ids else {}
        complete = len(park_ids) == 30 and all(v is not None for v in arrays.values())
        idx_all = np.flatnonzero(seasons == season)
        if not complete:
            status_by_hr[idx_all] = "UNMODELED_PARK_GEOMETRY_OR_MAPPING_NOT_VERIFIED"
            continue
        env_alt = dict(zip(env.park_id.astype(str), env.altitude_ft)) if len(env) else {}
        for s in range(0, len(idx_all), BATCH):
            idx = idx_all[s:s + BATCH]
            ok = fit_ok[idx] & spray_ok[idx]
            status_by_hr[idx[~ok]] = np.where(~spray_ok[idx[~ok]], "UNMODELED_SPRAY", "UNMODELED_TRACKING_OR_FIT")
            sel = idx[ok]
            if len(sel) == 0:
                continue
            rho_groups: dict[float, np.ndarray] = {}
            for pid in park_ids:
                rho = flight.air_density_at_altitude(env_alt[pid]) if pid in env_alt else flight.RHO_NEUTRAL
                rho_groups.setdefault(round(rho, 4), None)
            grids = {rho: flight.height_grid_ft(ev[sel], la[sel], rpm[sel], GRID, rho=rho, cd=cd) for rho in rho_groups}
            for pid in park_ids:
                rho = round(flight.air_density_at_altitude(env_alt[pid]) if pid in env_alt else flight.RHO_NEUTRAL, 4)
                ang, wd, wh = arrays[pid]
                w_d = np.interp(spray[sel], ang, wd); w_h = np.interp(spray[sel], ang, wh)
                h = _height_at(grids[rho], w_d)
                margin = h - w_h
                sim_rows.append(pd.DataFrame({
                    "hr_record_id": hrs.hr_record_id.to_numpy()[sel], "park_id": pid, "season": season,
                    "wall_distance_ft": w_d, "wall_height_ft": w_h,
                    "height_at_wall_ft": np.where(np.isfinite(h), h, np.nan), "margin_ft": np.where(np.isfinite(margin), margin, np.nan),
                    "would_be_home_run": margin > 0,
                    "simulation_status": "MODELED_FITTED_TRAJECTORY" + ("_PROVISIONAL" if allow_provisional else ""),
                }))
            status_by_hr[sel] = "MODELED"

    sims = pd.concat(sim_rows, ignore_index=True) if sim_rows else pd.DataFrame(
        columns=["hr_record_id", "park_id", "season", "would_be_home_run", "simulation_status"])
    sims.to_csv(outdir / "park_simulations.csv", index=False)

    # Classification: only HRs with all 30 parks modeled.
    if len(sims):
        k = sims.groupby("hr_record_id").agg(n=("park_id", "nunique"), cleared=("would_be_home_run", "sum"))
        k = k[k.n == 30]
        k["parks_cleared"] = k.cleared.astype(int)
        k["wsr_classification"] = k.parks_cleared.map(classify_parks_cleared)
        k = k[["parks_cleared", "wsr_classification"]].reset_index()
    else:
        k = pd.DataFrame(columns=["hr_record_id", "parks_cleared", "wsr_classification"])
    out = hrs.drop(columns=["parks_cleared", "wsr_classification", "model_status"], errors="ignore").merge(
        k, on="hr_record_id", how="left")
    out["wsr_classification"] = out["wsr_classification"].fillna("UNMODELED")
    out["backspin_fit_rpm"] = rpm
    out["spray_angle_deg"] = spray
    out["model_status"] = status_by_hr
    if allow_provisional:
        out["model_status"] = out["model_status"].replace({"MODELED": "MODELED_PROVISIONAL_GEOMETRY"})
    out.to_csv(outdir / "home_runs.csv", index=False)
    if not allow_provisional:
        build_summaries(out)
    else:
        import wsr.aggregate as agg
        orig = agg.PROCESSED
        agg.PROCESSED = outdir
        try:
            build_summaries(out)
        finally:
            agg.PROCESSED = orig

    diag = {"cd": cd, "target_median_backspin_rpm": flight.TARGET_MEDIAN_RPM,
            "spray_in_fair_share": float(fair_share), "fit_status_counts": pd.Series(fit_status).value_counts().to_dict(),
            "model_status_counts": pd.Series(status_by_hr).value_counts().to_dict(),
            "median_fit_rpm": float(np.nanmedian(rpm)) if np.isfinite(rpm).any() else None,
            "allow_provisional": allow_provisional, "n_hr": int(len(hrs))}
    (outdir / "model_diagnostics.json").write_text(json.dumps(diag, indent=2, default=str))
    print(json.dumps(diag, indent=2, default=str))
    return out, sims
