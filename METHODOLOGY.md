# WSR Technical Methodology

## 1. Event definition
The unit is a completed plate appearance with Statcast `events == home_run`. The downloader stores the source row from the pitch on which the plate appearance ended. A stable key is constructed from game, at-bat number, and batter ID.

## 2. Classification thresholds
For home run *i*, let `K_i` be the number of the 30 MLB parks where the modeled trajectory clears the outfield boundary:
- 1–5: Wall-Scraper
- 6–29: Standard
- 30: No-Doubter
- missing or incomplete 30-park evaluation: Unmodeled
- 0: review required; the source event was an HR, so a zero-park result indicates a model/geometry/coordinate inconsistency.

## 3. WSR denominator
The headline rate is `100 × Wall-Scraper HR / Total HR`. Because missing classifications can bias the result, publish it only when coverage is complete. When coverage is partial, publish `modeled_wsr_pct` as a clearly labeled secondary diagnostic and always show `model_coverage_pct`. Never present modeled-only WSR as the official full-season rate.

## 4. Park-neutral simulation design
A robust simulation must:
1. Reconstruct the ball's 3D trajectory from tracking or a calibrated flight model.
2. Preserve the batted ball's launch vector and evaluate it against each park's wall surface.
3. Represent the foul poles, corners, wall height, and wall distance as a season-specific profile.
4. Use a coordinate transform for each park, with spray direction consistently defined relative to center field.
5. Declare whether conditions are neutralized (air density, temperature, wind, altitude, roof, baseball) or held at actual game conditions.
6. Report uncertainty and sensitivity; classify borderline outcomes conservatively.

The Statcast export includes launch speed, launch angle, hit coordinates, and hit distance fields, but `hc_x/hc_y` are not a universally documented spray-angle variable and the export is not a full 3D ball trajectory. Do not claim an exact replay from those fields alone.

## 5. Park geometry
The supplied park directory is an identity register. The supplied profile file is intentionally blank for physical measurements. Populate it only from verified primary/credible sources and cite each park/season profile. Dimensions change; one current dimension set cannot safely represent 2015–2026.

## 6. Validation plan
- Verify event counts against Baseball Savant season/leaderboard totals.
- Check uniqueness by game_pk + at_bat_number + batter.
- Test known HRs and non-HR batted balls at multiple parks.
- Compare modeled outcomes with available Statcast expected-HR / park-adjusted references.
- Evaluate classification stability under plausible trajectory and geometry errors.
- Report confusion matrix, accuracy, calibration, and unmodeled percentage.

## 7. Implemented software boundary
The `wsr.simulation` module evaluates an already-generated trajectory against verified park wall profiles. It deliberately does not synthesize a flight trajectory from exit velocity and launch angle; that upstream model must be calibrated and validated before official classes can be published.

## 8. Season-specific venue mapping
The `team_park_seasons_template.csv` is a 2015–2026 franchise-to-physical-venue mapping template. A club's team ID is not a stadium ID. Temporary venues, relocations, renovations, and dimension changes must be represented by unique physical park IDs and season-specific geometry.

## 9. Implemented flight model and run policy (src/wsr/flight.py, model.py)
- **Spray angle:** `atan2(hc_x - 125.42, 198.27 - hc_y)` in degrees; 0 = center, negative = left field. The transform is community-derived; the run reports the share of HRs landing inside +/-45 degrees (expect ~100%) and marks any outside that range UNMODELED.
- **Trajectory:** 2-D vertical-plane RK4 integration with quadratic drag (global Cd) and Magnus lift (`CL = 1/(2.32 + 0.4/S)`, S = r*omega/v), contact height 3 ft, constant spin (no spin decay, no sidespin/curvature).
- **Per-HR fit:** backspin is unobserved, so each HR's backspin is solved so modeled landing distance equals Statcast `hit_distance_sc`. Real wind/temperature/altitude are absorbed into that spin. Where distance is flat in spin (near the carry peak) the *lowest* spin reaching the plateau is used.
- **Global drag:** Cd is chosen so the median fitted HR backspin equals `TARGET_MEDIAN_RPM` (2200). **This is an assumption**, not a measurement; replace it with published batted-ball spin data and re-run. Report sensitivity to it.
- **Park re-flight:** each fitted ball is re-flown under neutral air (1.194 kg/m^3 ~ 70F, sea level) and compared with each park's wall distance/height interpolated at the HR's spray angle. `margin_ft = height_at_wall - wall_height`; clears if margin > 0. Optional `data/reference/park_environment.csv` (park_id, altitude_ft) switches those parks to altitude-scaled density.
- **Gating:** official classes require all 30 season-park mappings VERIFIED, all 30 geometry profiles VERIFIED, valid tracking, and an in-range spray angle. Everything else is UNMODELED with a reason in `model_status`. `--allow-provisional` writes to `data/processed/provisional/` only.
- **Known limitations:** 5-anchor interpolated wall outlines miss irregular walls (Green Monster shape, Crawford Boxes, Oracle triples alley); no sidespin, so pull/oppo curvature is ignored; HRs hit off the wall/bouncing cases are not modeled; roofs/domes and weather are neutralized, not replayed; hit-distance tracking error propagates into spin and clearance (see sensitivity).
- **Sensitivity (`python run_pipeline.py sensitivity`):** Monte Carlo draws perturb EV (1 mph), LA (1 deg), spray (2 deg), tracked distance (4 ft), wall distance (2 ft) and height (0.5 ft); outputs per-HR class stability and the spread of the Wall-Scraper share.
- **Validation still required with real data:** (a) fitted-distance residuals (should be ~0 by construction, so also hold out: predict distance from EV/LA with a spin model fit on a subset and score the rest); (b) fraction UNREACHABLE; (c) agreement with Savant's "HR in X of 30 parks" figures for a sample of HRs; (d) season HR totals vs Savant leaderboard.
