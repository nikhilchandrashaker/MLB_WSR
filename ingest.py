"""Resumable Statcast home-run downloader."""
from __future__ import annotations
from datetime import date, timedelta
import json, time
from pathlib import Path
import pandas as pd
from .config import RAW

RAW.mkdir(parents=True, exist_ok=True)
CHECKPOINT = RAW / "download_checkpoint.json"
RAW_FILE = RAW / "statcast_home_runs.csv"

def date_chunks(start: date, end: date, days: int = 5):
    cur = start
    while cur <= end:
        nxt = min(cur + timedelta(days=days-1), end)
        yield cur, nxt
        cur = nxt + timedelta(days=1)

def season_window(year: int, today: date):
    start, end = date(year, 1, 1), min(date(year, 12, 31), today)
    # 2020's delayed MLB season; querying the whole year is harmless but wasteful.
    if year == 2020:
        start = date(2020, 7, 23)
    return start, end

def ingest(start_year=2015, end_year=None, chunk_days=5, pause=0.5, refresh=False):
    end_year = end_year or date.today().year
    if start_year < 2015:
        raise ValueError("Statcast WSR coverage starts in 2015.")
    if end_year < start_year:
        raise ValueError("end_year must be >= start_year.")
    try:
        from pybaseball import statcast
    except ImportError as e:
        raise RuntimeError("Install requirements.txt first.") from e

    state = json.loads(CHECKPOINT.read_text()) if CHECKPOINT.exists() else {"completed": []}
    completed = set(state.get("completed", []))
    frames = []
    if RAW_FILE.exists() and not refresh:
        frames.append(pd.read_csv(RAW_FILE, low_memory=False))

    today = date.today()
    for year in range(start_year, end_year+1):
        first, last = season_window(year, today)
        if first > last:
            continue
        for a, b in date_chunks(first, last, chunk_days):
            key = f"{a}_{b}"
            if key in completed and not refresh:
                continue
            print(f"Statcast request: {key}", flush=True)
            try:
                chunk = statcast(start_dt=a.isoformat(), end_dt=b.isoformat(), verbose=False, parallel=False)
                if chunk is not None and not chunk.empty and "events" in chunk:
                    hr = chunk.loc[chunk["events"].astype("string").str.lower().eq("home_run")].copy()
                    if not hr.empty:
                        hr["wsr_retrieved_at_utc"] = pd.Timestamp.now(tz="UTC").isoformat()
                        hr["wsr_window_start"] = a.isoformat()
                        hr["wsr_window_end"] = b.isoformat()
                        frames.append(hr)
                completed.add(key)
                CHECKPOINT.write_text(json.dumps({"completed": sorted(completed)}, indent=2))
            except Exception as exc:
                print(f"FAILED {key}: {exc}. It will retry on the next run.", flush=True)
            time.sleep(pause)

    if not frames:
        raise RuntimeError("No Statcast rows retrieved. Check network access and source availability.")
    out = pd.concat(frames, ignore_index=True, sort=False)
    keys = [c for c in ["game_pk", "at_bat_number", "batter"] if c in out.columns]
    if keys:
        out = out.drop_duplicates(keys, keep="last")
    out.to_csv(RAW_FILE, index=False)
    print(f"Saved {len(out):,} unique home-run plate appearances to {RAW_FILE}")
    return out
