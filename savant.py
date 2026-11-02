"""Home-run-only Statcast downloader using the Baseball Savant CSV endpoint.

Why this exists: the pybaseball path pulls every pitch in each 5-day window
(~4-5 million pitches for 2015-2026) and then throws away ~99.5% of them.
Savant can filter to home runs server-side, so a whole season is only a few
thousand rows. Requests are made one calendar month at a time and every raw
response is archived untouched under data/raw/chunks/ before anything is merged.

Savant caps a CSV response at 25,000 rows. A monthly HR-only window is ~1,000
rows, but the splitter below halves any window that comes back at the cap, so a
silently truncated response can never be accepted.
"""
from __future__ import annotations

import io
import json
import time
from calendar import monthrange
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

from .config import RAW

SAVANT_CSV_URL = "https://baseballsavant.mlb.com/statcast_search/csv"
ROW_CAP = 25_000
CHUNK_DIR = RAW / "chunks"
MANIFEST = RAW / "download_manifest.json"
RAW_FILE = RAW / "statcast_home_runs.csv"
DEDUPE_KEYS = ["game_pk", "at_bat_number", "batter"]


def build_params(start: date, end: date, season: int, game_types: str = "R") -> dict:
    """Query parameters for a home-run-only, batter-level, pitch-detail export."""
    gt = "".join(f"{g}|" for g in game_types.split(",") if g)
    return {
        "all": "true",
        "hfAB": r"home\.\.run|",
        "hfGT": gt,
        "hfSea": f"{season}|",
        "player_type": "batter",
        "game_date_gt": start.isoformat(),
        "game_date_lt": end.isoformat(),
        "min_pitches": "0",
        "min_results": "0",
        "min_abs": "0",
        "type": "details",
    }


def http_fetch(params: dict, timeout: int = 120) -> str:
    """Default network fetcher (replaceable in tests)."""
    import requests

    resp = requests.get(
        SAVANT_CSV_URL,
        params=params,
        timeout=timeout,
        headers={"User-Agent": "wsr-research-pipeline/1.0 (academic research)"},
    )
    resp.raise_for_status()
    return resp.text


def month_windows(year: int, today: date) -> Iterable[tuple[date, date]]:
    """Calendar-month windows covering the MLB calendar for a season (Mar-Nov)."""
    for month in range(3, 12):
        first = date(year, month, 1)
        last = date(year, month, monthrange(year, month)[1])
        if first > today:
            return
        yield first, min(last, today)


def _fetch_with_retry(fetch: Callable[[dict], str], params: dict, retries: int, backoff: float, sleep) -> str:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            return fetch(params)
        except Exception as exc:  # network errors, 429/5xx
            last = exc
            sleep(backoff * (2**attempt))
    raise RuntimeError(f"Request failed after {retries} attempts: {last}")


def _parse(text: str) -> pd.DataFrame:
    if not text.strip():
        return pd.DataFrame()
    df = pd.read_csv(io.StringIO(text), low_memory=False)
    if df.empty:
        return df
    if "events" not in df.columns:
        raise ValueError("Savant response has no 'events' column; the export schema may have changed or the response was an error page.")
    return df


def _fetch_window(start, end, season, game_types, fetch, retries, backoff, sleep):
    """Fetch one window; split in half when the row cap is hit. Returns [(start, end, raw_text, df)]."""
    text = _fetch_with_retry(fetch, build_params(start, end, season, game_types), retries, backoff, sleep)
    df = _parse(text)
    if len(df) >= ROW_CAP:
        if start == end:
            raise RuntimeError(f"Single-day window {start} hit the {ROW_CAP}-row cap; cannot split further.")
        mid = start + (end - start) / 2
        left_end = date.fromordinal(mid.toordinal())
        right_start = date.fromordinal(left_end.toordinal() + 1)
        return (_fetch_window(start, left_end, season, game_types, fetch, retries, backoff, sleep)
                + _fetch_window(right_start, end, season, game_types, fetch, retries, backoff, sleep))
    return [(start, end, text, df)]


def download(
    start_year: int = 2015,
    end_year: int | None = None,
    game_types: str = "R",
    pause: float = 1.0,
    retries: int = 4,
    backoff: float = 5.0,
    refresh: bool = False,
    fetch: Callable[[dict], str] = http_fetch,
    sleep: Callable[[float], None] = time.sleep,
    today: date | None = None,
) -> pd.DataFrame:
    """Download HR rows month-by-month, archive raw chunks, and merge into RAW_FILE."""
    today = today or date.today()
    end_year = end_year or today.year
    if start_year < 2015:
        raise ValueError("Statcast WSR coverage starts in 2015.")
    if end_year < start_year:
        raise ValueError("end_year must be >= start_year.")

    CHUNK_DIR.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() and not refresh else {"windows": {}}
    failed: list[str] = []

    for year in range(start_year, end_year + 1):
        for first, last in month_windows(year, today):
            key = f"{game_types.replace(',', '')}_{first}_{last}"
            entry = manifest["windows"].get(key)
            # Re-fetch the still-open current month so late corrections and new games are picked up.
            still_open = last >= today
            if entry and entry.get("status") == "ok" and not still_open:
                continue
            print(f"Savant request: {key}", flush=True)
            try:
                parts = _fetch_window(first, last, year, game_types, fetch, retries, backoff, sleep)
            except Exception as exc:
                failed.append(key)
                manifest["windows"][key] = {"status": "failed", "error": str(exc)[:300]}
                print(f"FAILED {key}: {exc}. It will retry on the next run.", flush=True)
                MANIFEST.write_text(json.dumps(manifest, indent=2))
                continue
            rows = 0
            for a, b, text, df in parts:
                (CHUNK_DIR / f"statcast_hr_{game_types.replace(',', '')}_{a}_{b}.csv").write_text(text)
                rows += int(df["events"].astype("string").str.lower().eq("home_run").sum()) if not df.empty else 0
            manifest["windows"][key] = {
                "status": "ok",
                "rows": rows,
                "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                "split_parts": len(parts),
            }
            MANIFEST.write_text(json.dumps(manifest, indent=2))
            sleep(pause)

    out = merge_chunks()
    if failed:
        print(f"WARNING: {len(failed)} window(s) failed and are NOT in the archive: {failed}")
    return out


def merge_chunks() -> pd.DataFrame:
    """Merge every archived chunk into one de-duplicated raw file."""
    frames = []
    for path in sorted(CHUNK_DIR.glob("statcast_hr_*.csv")):
        text = path.read_text()
        df = _parse(text)
        if df.empty:
            continue
        df = df.loc[df["events"].astype("string").str.lower().eq("home_run")].copy()
        df["wsr_source_chunk"] = path.name
        # File mtime is the retrieval time of that raw response.
        df["wsr_retrieved_at_utc"] = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        frames.append(df)
    if not frames:
        raise RuntimeError("No Statcast home-run rows retrieved. Check network access and source availability.")
    out = pd.concat(frames, ignore_index=True, sort=False)
    keys = [c for c in DEDUPE_KEYS if c in out.columns]
    before = len(out)
    out = out.drop_duplicates(keys, keep="last")
    print(f"Merged {before:,} rows -> {len(out):,} unique home runs ({before - len(out):,} duplicates dropped).")
    out.to_csv(RAW_FILE, index=False)
    return out
