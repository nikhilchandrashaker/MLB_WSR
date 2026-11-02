"""Monte Carlo sensitivity of WSR classes to input uncertainty.

Perturbs, per draw: exit velocity, launch angle, spray angle, tracked distance, and every park's
wall distance and height; refits backspin, re-flies, and re-classifies. Reports how often each HR's
class survives and how the headline Wall-Scraper share moves.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import flight
from .classify import classify_parks_cleared
from .config import PROCESSED
from .geometry import season_park_arrays
from .model import GRID, _height_at, load_inputs

SIGMA = {"ev_mph": 1.0, "la_deg": 1.0, "spray_deg": 2.0, "dist_ft": 4.0, "wall_dist_ft": 2.0, "wall_ht_ft": 0.5}


def run_sensitivity(n_sample: int = 600, draws: int = 20, seed: int = 7, allow_provisional: bool = False):
    outdir = PROCESSED / ("provisional" if allow_provisional else "")
    hrs, profiles, park_map, _ = load_inputs(allow_provisional)
    done = pd.read_csv(outdir / "home_runs.csv", low_memory=False)
    done = done[done.model_status.astype(str).str.startswith("MODELED")]
    if done.empty:
        raise RuntimeError("No modeled HRs; run the model first.")
    rng = np.random.default_rng(seed)
    sample = done.sample(min(n_sample, len(done)), random_state=seed).reset_index(drop=True)
    allowed = ("VERIFIED", "PROVISIONAL") if allow_provisional else ("VERIFIED",)
    ev0 = sample.exit_velocity_mph.to_numpy(float); la0 = sample.launch_angle_deg.to_numpy(float)
    d0 = sample.tracked_distance_ft.to_numpy(float); sp0 = sample.spray_angle_deg.to_numpy(float)
    cd = json.loads((outdir / "model_diagnostics.json").read_text())["cd"]
    base_k = sample.parks_cleared.to_numpy(int)
    stay = np.zeros(len(sample)); ws_share = []
    for _ in range(draws):
        ev = ev0 + rng.normal(0, SIGMA["ev_mph"], len(sample)); la = la0 + rng.normal(0, SIGMA["la_deg"], len(sample))
        d = d0 + rng.normal(0, SIGMA["dist_ft"], len(sample))
        sp = np.clip(sp0 + rng.normal(0, SIGMA["spray_deg"], len(sample)), -45, 45)
        rpm, st = flight.fit_backspin(ev, la, d, cd=cd)
        ok = st == "OK"
        k = np.full(len(sample), -1)
        for season in sorted(sample.season.unique()):
            m = (sample.season.to_numpy() == season) & ok
            if not m.any():
                continue
            pids = park_map[(park_map.season == season) & (park_map.mapping_status == "VERIFIED")].park_id.astype(str).unique().tolist()
            arrays = season_park_arrays(profiles, int(season), pids, allowed)
            grid = flight.height_grid_ft(ev[m], la[m], rpm[m], GRID, cd=cd)
            cnt = np.zeros(m.sum(), int)
            for pid in pids:
                ang, wd, wh = arrays[pid]
                w_d = np.interp(sp[m], ang, wd) + rng.normal(0, SIGMA["wall_dist_ft"])
                w_h = np.interp(sp[m], ang, wh) + rng.normal(0, SIGMA["wall_ht_ft"])
                cnt += (_height_at(grid, w_d) - w_h) > 0
            k[m] = cnt
        cls = np.array([classify_parks_cleared(x) if x >= 0 else "UNMODELED" for x in k])
        base_cls = np.array([classify_parks_cleared(x) for x in base_k])
        stay += (cls == base_cls)
        ws_share.append(float(np.mean(cls == "WALL_SCRAPER")))
    out = sample[["hr_record_id", "season", "player_name", "parks_cleared", "wsr_classification"]].copy()
    out["class_stability"] = stay / draws
    out.to_csv(outdir / "sensitivity_by_hr.csv", index=False)
    summary = {"n_sample": len(sample), "draws": draws, "sigma": SIGMA,
               "baseline_wall_scraper_share": float(np.mean(base_k <= 5)),
               "perturbed_wall_scraper_share_mean": float(np.mean(ws_share)),
               "perturbed_wall_scraper_share_sd": float(np.std(ws_share)),
               "mean_class_stability": float(out.class_stability.mean()),
               "share_hr_stable_ge_90pct": float((out.class_stability >= 0.9).mean())}
    (outdir / "sensitivity_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return summary
