"""Figures from model outputs. Only draws what exists; never fabricates."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from .config import PROCESSED, ROOT

MIN_HR = 25          # minimum season HR for a leaderboard row
MIN_COVERAGE = 100.0 # official leaderboards require full model coverage


def leaderboard(player: pd.DataFrame, min_hr: int = MIN_HR, min_cov: float = MIN_COVERAGE) -> pd.DataFrame:
    ok = player[(player.total_hr >= min_hr) & (player.model_coverage_pct >= min_cov)]
    return ok.sort_values("wsr_pct", ascending=False)


def make_figures():
    fig_dir = ROOT / "figures"; fig_dir.mkdir(exist_ok=True)
    made = []
    p = PROCESSED / "player_season_wsr.csv"
    if p.exists():
        player = pd.read_csv(p)
        lb = leaderboard(player)
        lb.to_csv(PROCESSED / "leaderboard_player_season.csv", index=False)
        if len(lb):
            top = lb.head(15).iloc[::-1]
            fig, ax = plt.subplots(figsize=(8, 5))
            ax.barh([f"{n} {int(s)}" for n, s in zip(top.player_name, top.season)], top.wsr_pct, color="#2a6f97")
            ax.set_xlabel("WSR % (Wall-Scraper HR / total HR)"); ax.set_title(f"Top player-seasons (min {MIN_HR} HR, 100% coverage)")
            fig.tight_layout(); fig.savefig(fig_dir / "leaderboard_player_season.png", dpi=160); plt.close(fig)
            made.append("leaderboard_player_season.png")
        cov = player.groupby("season").apply(lambda g: 100*g.modeled_hr.sum()/g.total_hr.sum(), include_groups=False)
        fig, ax = plt.subplots(figsize=(7, 3.5)); cov.plot.bar(ax=ax, color="#6c757d")
        ax.set_ylabel("Model coverage %"); ax.set_title("Share of home runs modeled, by season"); ax.set_ylim(0, 100)
        fig.tight_layout(); fig.savefig(fig_dir / "model_coverage_by_season.png", dpi=160); plt.close(fig)
        made.append("model_coverage_by_season.png")
    sims = PROCESSED / "park_simulations.csv"
    if sims.exists():
        s = pd.read_csv(sims, usecols=["park_id", "would_be_home_run"])
        rate = s.groupby("park_id").would_be_home_run.mean().sort_values() * 100
        fig, ax = plt.subplots(figsize=(8, 6)); rate.plot.barh(ax=ax, color="#bc4749")
        ax.set_xlabel("% of all modeled HRs that clear this park"); ax.set_title("Park comparison (neutral-conditions flight model)")
        fig.tight_layout(); fig.savefig(fig_dir / "park_clearance_rates.png", dpi=160); plt.close(fig)
        made.append("park_clearance_rates.png")
    print("Figures:", made or "none (no model outputs yet)")
    return made
