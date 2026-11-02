"""Batted-ball flight model (vertical-plane drag + Magnus lift), vectorized.

Policy (documented, see docs/METHODOLOGY.md section 9):
  * Each HR is flown in the vertical plane through its spray direction.
  * Launch speed and angle come from Statcast; contact height is fixed.
  * Backspin is NOT observed in the public HR feed, so it is the one fitted
    unknown: for every HR we solve for the constant backspin (rpm) that makes
    the model's landing distance equal Statcast's tracked ``hit_distance_sc``.
    Wind, temperature, humidity and altitude actually experienced by the ball are
    therefore absorbed into that fitted spin. The re-flight in every park then
    happens under a declared, *neutral* atmosphere (default 70F, sea level).
  * Global drag coefficient is calibrated so the median fitted HR backspin
    matches a stated target (``TARGET_MEDIAN_RPM``, an assumption, not data).
  * HRs whose tracked distance cannot be reproduced for any physical spin
    (0..MAX_RPM) are flagged and left UNMODELED, never forced.
"""
from __future__ import annotations

import numpy as np

FT = 0.3048
MPH = 0.44704
MASS = 0.1417                    # kg (5.0 oz)
RADIUS = 0.03665                 # m
AREA = np.pi * RADIUS**2
RHO_NEUTRAL = 1.194              # kg/m3, ~70F, sea level, 50% RH
G = 9.80665
CONTACT_HEIGHT_FT = 3.0
MAX_RPM = 6000.0
TARGET_MEDIAN_RPM = 2200.0       # assumption used only to pin the global drag scale
DEFAULT_CD = 0.35
DT = 0.02


def air_density_at_altitude(alt_ft: float, rho_sea_level: float = RHO_NEUTRAL) -> float:
    """Isothermal-ish density scaling; used only if a park environment file is supplied."""
    return rho_sea_level * float(np.exp(-(alt_ft * FT) / 8500.0))


def _accel(vx, vy, omega, rho, cd):
    v = np.hypot(vx, vy)
    v = np.maximum(v, 1e-6)
    s = RADIUS * omega / v                       # spin parameter
    cl = 1.0 / (2.32 + 0.4 / np.maximum(s, 1e-9))
    k = rho * AREA / (2.0 * MASS)
    ax = -k * cd * v * vx - k * cl * v * vy
    ay = -G - k * cd * v * vy + k * cl * v * vx
    return ax, ay


def _rk4(x, y, vx, vy, omega, rho, cd, dt):
    a1x, a1y = _accel(vx, vy, omega, rho, cd)
    k1 = (vx, vy, a1x, a1y)
    a2x, a2y = _accel(vx + 0.5*dt*k1[2], vy + 0.5*dt*k1[3], omega, rho, cd)
    k2 = (vx + 0.5*dt*k1[2], vy + 0.5*dt*k1[3], a2x, a2y)
    a3x, a3y = _accel(vx + 0.5*dt*k2[2], vy + 0.5*dt*k2[3], omega, rho, cd)
    k3 = (vx + 0.5*dt*k2[2], vy + 0.5*dt*k2[3], a3x, a3y)
    a4x, a4y = _accel(vx + dt*k3[2], vy + dt*k3[3], omega, rho, cd)
    k4 = (vx + dt*k3[2], vy + dt*k3[3], a4x, a4y)
    nx = x + dt/6*(k1[0] + 2*k2[0] + 2*k3[0] + k4[0])
    ny = y + dt/6*(k1[1] + 2*k2[1] + 2*k3[1] + k4[1])
    nvx = vx + dt/6*(k1[2] + 2*k2[2] + 2*k3[2] + k4[2])
    nvy = vy + dt/6*(k1[3] + 2*k2[3] + 2*k3[3] + k4[3])
    return nx, ny, nvx, nvy


def _init(ev_mph, la_deg, rpm):
    ev = np.asarray(ev_mph, float) * MPH
    la = np.radians(np.asarray(la_deg, float))
    omega = np.asarray(rpm, float) * 2*np.pi/60.0
    n = np.broadcast(ev, la, omega).shape
    ev, la, omega = (np.broadcast_to(a, n).copy() for a in (ev, la, omega))
    return ev*np.cos(la), ev*np.sin(la), omega


def landing_distance_ft(ev_mph, la_deg, rpm, rho=RHO_NEUTRAL, cd=DEFAULT_CD, dt=DT, max_t=14.0):
    """Horizontal distance (ft) from home plate where the ball returns to ground level."""
    vx, vy, omega = _init(ev_mph, la_deg, rpm)
    x = np.zeros_like(vx); y = np.full_like(vx, CONTACT_HEIGHT_FT*FT)
    done = np.zeros(vx.shape, bool); out = np.full(vx.shape, np.nan)
    for _ in range(int(max_t/dt)):
        nx, ny, nvx, nvy = _rk4(x, y, vx, vy, omega, rho, cd, dt)
        cross = (~done) & (ny <= 0) & (vy < 0)
        if cross.any():
            f = y[cross] / np.maximum(y[cross] - ny[cross], 1e-9)
            out[cross] = (x[cross] + f*(nx[cross] - x[cross])) / FT
            done |= cross
        x, y, vx, vy = nx, ny, nvx, nvy
        if done.all():
            break
    return out


def fit_backspin(ev_mph, la_deg, dist_ft, rho=RHO_NEUTRAL, cd=DEFAULT_CD, iters=28):
    """Solve backspin (rpm) so modeled landing distance == tracked distance.

    Distance is monotone increasing in spin up to a peak; we bracket on [0, rpm_peak]
    where rpm_peak is found on a coarse grid. Returns (rpm, status) with status in
    {"OK","UNREACHABLE_SHORT","UNREACHABLE_LONG","MISSING_INPUT"}.
    """
    ev = np.asarray(ev_mph, float); la = np.asarray(la_deg, float); d = np.asarray(dist_ft, float)
    n = ev.shape[0]
    status = np.full(n, "OK", dtype=object)
    bad = ~(np.isfinite(ev) & np.isfinite(la) & np.isfinite(d))
    status[bad] = "MISSING_INPUT"
    evf = np.where(bad, 100.0, ev); laf = np.where(bad, 28.0, la)
    grid = np.linspace(0, MAX_RPM, 25)
    dg = np.stack([landing_distance_ft(evf, laf, np.full(n, r), rho, cd) for r in grid], axis=1)
    peak = np.nanmax(dg, axis=1)
    # Distance flattens near its peak (spin is then poorly identified); take the lowest
    # spin that gets within 1 ft of the peak as the upper bracket.
    peak_idx = np.argmax(dg >= (peak[:, None] - 1.0), axis=1)
    hi = grid[peak_idx].astype(float)
    lo = np.zeros(n)
    d_lo = dg[:, 0]
    status[~bad & (d < d_lo - 1.0)] = "UNREACHABLE_SHORT"
    status[~bad & (d > peak + 1.0)] = "UNREACHABLE_LONG"
    for _ in range(iters):
        mid = 0.5*(lo+hi)
        dm = landing_distance_ft(evf, laf, mid, rho, cd)
        up = dm < d
        lo = np.where(up, mid, lo); hi = np.where(up, hi, mid)
    rpm = 0.5*(lo+hi)
    rpm[status != "OK"] = np.nan
    return rpm, status


def calibrate_cd(ev_mph, la_deg, dist_ft, target_rpm=TARGET_MEDIAN_RPM, rho=RHO_NEUTRAL,
                 sample=3000, seed=0):
    """Pick the drag coefficient (0.25-0.45) whose median fitted HR backspin hits the target."""
    rng = np.random.default_rng(seed)
    ev = np.asarray(ev_mph, float); la = np.asarray(la_deg, float); d = np.asarray(dist_ft, float)
    ok = np.isfinite(ev) & np.isfinite(la) & np.isfinite(d)
    idx = np.flatnonzero(ok)
    if len(idx) > sample:
        idx = rng.choice(idx, sample, replace=False)
    def med(cd):
        r, s = fit_backspin(ev[idx], la[idx], d[idx], rho, cd)
        # If most HRs are unreachable the drag is too high for the observed distances.
        if np.mean(s == "OK") < 0.5:
            return np.inf
        return np.nanmedian(r)
    lo, hi = 0.25, 0.45
    # Higher drag needs more lift to reach the same distance -> median rpm increases with cd.
    for _ in range(14):
        mid = 0.5*(lo+hi)
        m = med(mid)
        if m < target_rpm:
            lo = mid
        else:
            hi = mid
    return 0.5*(lo+hi)


def height_grid_ft(ev_mph, la_deg, rpm, grid_ft, rho=RHO_NEUTRAL, cd=DEFAULT_CD, dt=DT, max_t=14.0):
    """Ball height (ft) at each radial distance in ``grid_ft`` for each HR.

    Distances beyond the landing point get -inf (ball already down). Heights are taken
    on the ascending/descending branch by interpolating the monotone-in-x trajectory.
    """
    vx, vy, omega = _init(ev_mph, la_deg, rpm)
    n = vx.shape[0]
    steps = int(max_t/dt)
    xs = np.empty((steps+1, n), np.float32); ys = np.empty((steps+1, n), np.float32)
    x = np.zeros(n); y = np.full(n, CONTACT_HEIGHT_FT*FT)
    xs[0], ys[0] = x/FT, y/FT
    live = np.ones(n, bool); last = 0
    for i in range(1, steps+1):
        x, y, vx, vy = _rk4(x, y, vx, vy, omega, rho, cd, dt)
        xs[i], ys[i] = x/FT, y/FT
        last = i
        live &= ~((y <= 0) & (vy < 0))
        if not live.any():
            break
    xs, ys = xs[:last+1], ys[:last+1]
    out = np.full((n, len(grid_ft)), -np.inf, np.float32)
    for j in range(n):
        xj, yj = xs[:, j], ys[:, j]
        land = np.flatnonzero(yj <= 0)
        end = land[0] if len(land) else len(xj)-1
        xj, yj = xj[:end+1], yj[:end+1]
        # x is non-decreasing for a batted ball in this model
        m = (grid_ft >= xj[0]) & (grid_ft <= xj[-1])
        out[j, m] = np.interp(grid_ft[m], xj, yj)
    return out


def spray_angle_deg(hc_x, hc_y):
    """Spray angle from Statcast hit coordinates; 0 = dead center, negative = left-field line.

    Home plate is at about (125.42, 198.27) in Savant's hc_x/hc_y pixel frame (community-derived,
    the same transform used in Savant's own spray charts); the angle is independent of scale.
    """
    x = np.asarray(hc_x, float) - 125.42
    y = 198.27 - np.asarray(hc_y, float)
    return np.degrees(np.arctan2(x, y))
