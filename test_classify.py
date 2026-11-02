import pandas as pd
from wsr.classify import classify_parks_cleared, attach_classifications

def test_thresholds():
    assert classify_parks_cleared(1) == "WALL_SCRAPER"
    assert classify_parks_cleared(5) == "WALL_SCRAPER"
    assert classify_parks_cleared(6) == "STANDARD"
    assert classify_parks_cleared(29) == "STANDARD"
    assert classify_parks_cleared(30) == "NO_DOUBTER"
    assert classify_parks_cleared(None) == "UNMODELED"

def test_attach_requires_30_parks():
    hrs = pd.DataFrame({"hr_record_id":["a"]})
    sims = pd.DataFrame({"hr_record_id":["a"]*30,"park_id":[f"P{i}" for i in range(30)],
                         "would_be_home_run":[True]*4+[False]*26})
    out = attach_classifications(hrs, sims)
    assert out.loc[0,"parks_cleared"] == 4
    assert out.loc[0,"wsr_classification"] == "WALL_SCRAPER"
