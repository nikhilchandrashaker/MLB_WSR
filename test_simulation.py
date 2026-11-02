
import pandas as pd
from wsr.simulation import evaluate_trajectory_in_park

def test_park_wall_crossing():
    trajectory = pd.DataFrame({"distance_ft":[0,100,200,300,350,400],
                               "height_ft":[3,35,55,50,30,0]})
    profile = pd.DataFrame({
        "park_id":["X","X"],"season_start":[2025,2025],"season_end":[2025,2025],
        "spray_angle_deg":[-10,10],"wall_distance_ft":[330,330],
        "wall_height_ft":[8,8],"geometry_status":["VERIFIED","VERIFIED"]
    })
    assert evaluate_trajectory_in_park(trajectory, profile, "X", 2025, 0) is True

def test_incomplete_geometry_is_unmodeled():
    trajectory = pd.DataFrame({"distance_ft":[0,200,400],"height_ft":[3,30,0]})
    profile = pd.DataFrame({
        "park_id":["X","X"],"season_start":[2025,2025],"season_end":[2025,2025],
        "spray_angle_deg":[-10,10],"wall_distance_ft":[330,330],
        "wall_height_ft":[8,8],"geometry_status":["MISSING","MISSING"]
    })
    assert evaluate_trajectory_in_park(trajectory, profile, "X", 2025, 0) is None
