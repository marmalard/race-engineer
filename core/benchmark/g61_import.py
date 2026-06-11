"""Import a Garage 61 lap CSV export into a NormalizedLap.

G61 exports vary in column naming, units (km/h vs m/s, percent vs 0-1
pedals), and sample spacing. This module maps columns by alias table,
detects units heuristically, and resamples onto the same 1m distance
grid the IBT pipeline uses — after this, comparison code cannot tell
where a lap came from.
"""

from typing import IO

import numpy as np
import pandas as pd

from core.telemetry.normalizer import NormalizedLap


class G61ImportError(Exception):
    """Raised when a CSV cannot be mapped to required channels."""


# Logical channel -> acceptable G61 column names (case-insensitive match).
# VERIFY against a real export before trusting; extend as needed.
CHANNEL_ALIASES: dict[str, list[str]] = {
    "distance": ["distance", "distance (m)", "lapdist", "lap distance", "dist"],
    "speed": ["speed", "speed (km/h)", "speed (m/s)", "speed kmh", "ground speed"],
    "throttle": ["throttle", "throttle (%)", "throttle pos", "rpedal"],
    "brake": ["brake", "brake (%)", "brake pos", "brake pressure"],
    "gear": ["gear"],
    "rpm": ["rpm", "engine rpm"],
    "steering": ["steeringwheelangle", "steering", "steering angle", "steer"],
    "time": ["time", "lap time", "currentlaptime", "elapsed time", "time (s)"],
    "lat": ["lat", "latitude", "gps lat"],
    "lon": ["lon", "long", "longitude", "gps lon"],
}

REQUIRED = ["distance", "speed"]


def _map_columns(df: pd.DataFrame) -> dict[str, str]:
    """Map logical channel names to actual DataFrame column names.

    Args:
        df: DataFrame parsed from the G61 CSV.

    Returns:
        Dict mapping logical channel name -> actual column name.

    Raises:
        G61ImportError: If required channels cannot be found.
    """
    lower_cols = {c.lower().strip(): c for c in df.columns}
    mapping: dict[str, str] = {}
    for logical, aliases in CHANNEL_ALIASES.items():
        for alias in aliases:
            if alias in lower_cols:
                mapping[logical] = lower_cols[alias]
                break
    missing = [ch for ch in REQUIRED if ch not in mapping]
    if missing:
        raise G61ImportError(
            f"Could not find required channels {missing} in CSV. "
            f"Found columns: {list(df.columns)}. "
            f"Add the actual names to CHANNEL_ALIASES in g61_import.py."
        )
    return mapping


def import_g61_csv(
    source: IO | str,
    track_length_m: float,
    distance_interval: float = 1.0,
) -> NormalizedLap:
    """Parse a Garage 61 lap CSV and resample to the standard distance grid.

    Handles:
    - Column name variations via CHANNEL_ALIASES alias table
    - Speed in km/h (detected heuristically, converted to m/s)
    - Pedals as percent 0-100 (detected heuristically, converted to 0-1)
    - Arbitrary sample spacing (resampled to distance_interval meter grid)
    - Missing optional channels (filled with zeros)
    - Elapsed time integration when no time channel is present

    Args:
        source: File-like object or path to the G61 CSV export.
        track_length_m: Expected track length in meters (used to cap the grid).
        distance_interval: Output grid spacing in meters (default 1.0).

    Returns:
        NormalizedLap on a uniform distance grid, all channels in SI units.

    Raises:
        G61ImportError: If required columns (distance, speed) cannot be found.
    """
    try:
        df = pd.read_csv(source)
    except Exception as exc:
        raise G61ImportError(f"Could not parse CSV: {exc}") from exc
    cols = _map_columns(df)

    if len(df) < 2:
        raise G61ImportError(
            "CSV has fewer than 2 data rows; cannot resample a lap from it."
        )

    raw_dist = df[cols["distance"]].to_numpy(dtype=float)
    raw_speed = df[cols["speed"]].to_numpy(dtype=float)

    # Unit detection: no car reaches 130 m/s; km/h values for race cars do exceed it
    if np.nanmax(raw_speed) > 130.0:
        raw_speed = raw_speed / 3.6

    def channel(name: str, default: float = 0.0) -> np.ndarray:
        if name in cols:
            return df[cols[name]].to_numpy(dtype=float)
        return np.full(len(df), default)

    raw_throttle = channel("throttle")
    raw_brake = channel("brake")
    # Pedal unit detection: percent scale -> 0-1
    if np.nanmax(raw_throttle) > 1.5:
        raw_throttle = raw_throttle / 100.0
    if np.nanmax(raw_brake) > 1.5:
        raw_brake = raw_brake / 100.0

    # Drop duplicate / non-increasing distance samples (interp requires monotonic x)
    keep = np.concatenate([[True], np.diff(raw_dist) > 0])
    raw_dist = raw_dist[keep]

    def kept(arr: np.ndarray) -> np.ndarray:
        return arr[keep]

    grid = np.arange(0.0, min(track_length_m, raw_dist[-1]), distance_interval)

    def resample(arr: np.ndarray) -> np.ndarray:
        return np.interp(grid, raw_dist, arr)

    speed = resample(kept(raw_speed))

    if "time" in cols:
        raw_time = kept(df[cols["time"]].to_numpy(dtype=float))
        elapsed = resample(raw_time - raw_time[0])
    else:
        # Integrate dt = ds / v over the grid
        dt = distance_interval / np.maximum(speed, 1.0)
        elapsed = np.cumsum(dt)

    return NormalizedLap(
        lap_number=0,
        lap_time=float(elapsed[-1]),
        track_length=track_length_m,
        distance=grid,
        speed=speed,
        throttle=resample(kept(raw_throttle)),
        brake=resample(kept(raw_brake)),
        steering=resample(kept(channel("steering"))),
        gear=np.round(resample(kept(channel("gear", 0.0)))).astype(int),
        rpm=resample(kept(channel("rpm"))),
        lat=resample(kept(channel("lat"))),
        lon=resample(kept(channel("lon"))),
        elapsed_time=elapsed,
        is_valid=True,
    )
