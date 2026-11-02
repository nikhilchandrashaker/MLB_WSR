import pandas as pd
from wsr.normalize import normalize
from wsr.aggregate import _summarize

def test_batting_team_top_bottom():
    raw = pd.DataFrame({
        "game_date":["2025-04-01","2025-04-01"],"batter":[1,2],"pitcher":[3,4],
        "events":["home_run","home_run"],"inning_topbot":["Top","Bot"],
        "home_team":["NYY","NYY"],"away_team":["BOS","BOS"],
        "launch_speed":[100,95],"launch_angle":[25,30],"hc_x":[1,2],"hc_y":[3,4],
        "game_pk":[10,10],"at_bat_number":[1,2],"player_name":["Batter A","Batter B"]
    })
    df = normalize(raw)
    assert list(df["batting_team"]) == ["BOS","NYY"]
    assert list(df["season"]) == [2025,2025]
