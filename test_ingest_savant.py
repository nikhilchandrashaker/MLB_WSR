import json
from datetime import date
import pandas as pd
import pytest
from wsr import savant, config

HEADER = "game_date,game_pk,at_bat_number,batter,player_name,events,launch_speed,launch_angle,hc_x,hc_y,hit_distance_sc,home_team,away_team,inning_topbot\n"

def row(d, pk, ab, batter, ev="home_run", ls="100.1"):
    return f"{d},{pk},{ab},{batter},Name {batter},{ev},{ls},28,120.5,40.2,410,NYY,BOS,Bot\n"

@pytest.fixture
def tmp_raw(tmp_path, monkeypatch):
    monkeypatch.setattr(savant, "RAW", tmp_path)
    monkeypatch.setattr(savant, "CHUNK_DIR", tmp_path / "chunks")
    monkeypatch.setattr(savant, "MANIFEST", tmp_path / "manifest.json")
    monkeypatch.setattr(savant, "RAW_FILE", tmp_path / "raw.csv")
    return tmp_path

def test_params_filter_home_runs_only():
    p = savant.build_params(date(2024, 4, 1), date(2024, 4, 30), 2024, "R,F")
    assert p["hfAB"] == r"home\.\.run|" and p["hfGT"] == "R|F|" and p["hfSea"] == "2024|"

def test_download_dedupes_and_resumes(tmp_raw):
    calls = []
    def fake(params):
        calls.append(params["game_date_gt"])
        if params["game_date_gt"].startswith("2024-04"):
            return HEADER + row("2024-04-02", 1, 5, 11) + row("2024-04-02", 1, 5, 11) + row("2024-04-03", 2, 9, 12) + row("2024-04-03", 2, 10, 13, ev="single")
        return HEADER
    out = savant.download(2024, 2024, fetch=fake, sleep=lambda s: None, pause=0, today=date(2024, 6, 15))
    assert len(out) == 2                      # duplicate + non-HR removed
    n_first = len(calls)
    savant.download(2024, 2024, fetch=fake, sleep=lambda s: None, pause=0, today=date(2024, 6, 15))
    # only the still-open current month (June) is re-requested on resume
    assert len(calls) - n_first == 1

def test_failed_window_is_reported_and_retried(tmp_raw):
    state = {"fail": True}
    def flaky(params):
        if params["game_date_gt"].startswith("2024-05") and state["fail"]:
            raise ConnectionError("boom")
        return HEADER + row(params["game_date_gt"], hash(params["game_date_gt"]) % 1000, 1, 7)
    savant.download(2024, 2024, retries=2, backoff=0, fetch=flaky, sleep=lambda s: None, pause=0, today=date(2024, 6, 30))
    m = json.loads((tmp_raw / "manifest.json").read_text())["windows"]
    assert m["R_2024-05-01_2024-05-31"]["status"] == "failed"
    state["fail"] = False
    savant.download(2024, 2024, retries=2, backoff=0, fetch=flaky, sleep=lambda s: None, pause=0, today=date(2024, 6, 30))
    m = json.loads((tmp_raw / "manifest.json").read_text())["windows"]
    assert m["R_2024-05-01_2024-05-31"]["status"] == "ok"

def test_row_cap_triggers_split(tmp_raw, monkeypatch):
    monkeypatch.setattr(savant, "ROW_CAP", 3)
    def capped(params):
        a, b = date.fromisoformat(params["game_date_gt"]), date.fromisoformat(params["game_date_lt"])
        n = (b - a).days + 1
        k = 3 if n > 2 else n   # a window longer than 2 days returns exactly ROW_CAP rows
        return HEADER + "".join(row(date.fromordinal(a.toordinal()+i).isoformat(), a.toordinal()+i, 1, 5) for i in range(k))
    out = savant.download(2024, 2024, fetch=capped, sleep=lambda s: None, pause=0, today=date(2024, 4, 30))
    m = json.loads((tmp_raw / "manifest.json").read_text())["windows"]
    assert m["R_2024-04-01_2024-04-30"]["split_parts"] > 1

def test_error_page_rejected(tmp_raw):
    with pytest.raises(Exception):
        savant.download(2024, 2024, retries=1, backoff=0, fetch=lambda p: "a,b\n1,2\n", sleep=lambda s: None, pause=0, today=date(2024, 4, 30))

def test_team_codes():
    from wsr.normalize import normalize
    raw = pd.DataFrame({"game_date": ["2024-05-01"], "batter": [1], "game_pk": [1], "at_bat_number": [1],
                        "inning_topbot": ["Top"], "home_team": ["CWS"], "away_team": ["AZ"], "events": ["home_run"]})
    df = normalize(raw)
    assert df.loc[0, "home_team_franchise"] == "CHW" and df.loc[0, "batting_team_franchise"] == "ARI"
