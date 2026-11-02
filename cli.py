import argparse
from .ingest import ingest
from .normalize import normalize_file
from .aggregate import build_summaries
from .validate import validate_home_runs
from .config import PROCESSED

def main():
    p = argparse.ArgumentParser(description="Build the MLB Wall-Scraper Rate archive")
    sub = p.add_subparsers(dest="command", required=True)
    i = sub.add_parser("ingest")
    i.add_argument("--start-year", type=int, default=2015)
    i.add_argument("--end-year", type=int, default=None)
    i.add_argument("--chunk-days", type=int, default=5)
    i.add_argument("--pause", type=float, default=0.5)
    i.add_argument("--refresh", action="store_true")
    i.add_argument("--engine", choices=["savant", "pybaseball"], default="savant",
                   help="savant = HR-only monthly CSV export (fast, default); pybaseball = legacy all-pitch pull")
    i.add_argument("--game-types", default="R", help="Comma list: R,F,D,L,W (default regular season only)")
    sub.add_parser("normalize")
    sub.add_parser("summarize")
    sub.add_parser("validate")
    sub.add_parser("coverage")
    sub.add_parser("geometry", help="Build park_wall_profiles.csv from park_geometry_inputs.csv")
    m = sub.add_parser("model", help="Fit trajectories, simulate all 30 parks, classify, summarize")
    m.add_argument("--allow-provisional", action="store_true")
    sub.add_parser("figures")
    sn = sub.add_parser("sensitivity")
    sn.add_argument("--allow-provisional", action="store_true")
    sub.add_parser("simulate")
    a = p.parse_args()
    if a.command == "ingest":
        if a.engine == "savant":
            from .savant import download
            download(a.start_year, a.end_year, a.game_types, max(a.pause, 1.0), refresh=a.refresh)
        else:
            ingest(a.start_year, a.end_year, a.chunk_days, a.pause, a.refresh)
        normalize_file()
        from .coverage import write_coverage_report
        write_coverage_report()
    elif a.command == "normalize":
        normalize_file()
    elif a.command == "summarize":
        df = normalize_file()
        build_summaries(df)
    elif a.command == "simulate":
        from .simulation import run_simulation_pipeline
        run_simulation_pipeline()
    elif a.command == "geometry":
        from .geometry import build_profiles_file
        out = build_profiles_file()
        print(out.groupby(["park_id", "season_start", "season_end", "geometry_status"]).size())
    elif a.command == "model":
        from .model import run_model
        run_model(a.allow_provisional)
    elif a.command == "sensitivity":
        from .sensitivity import run_sensitivity
        run_sensitivity(allow_provisional=a.allow_provisional)
    elif a.command == "figures":
        from .figures import make_figures
        make_figures()
    elif a.command == "coverage":
        from .coverage import write_coverage_report
        write_coverage_report()
    elif a.command == "validate":
        import pandas as pd
        df = pd.read_csv(PROCESSED/"home_runs.csv", low_memory=False)
        problems = validate_home_runs(df)
        print("\n".join(problems) if problems else "Validation passed.")
