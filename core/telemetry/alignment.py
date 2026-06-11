"""Distance-offset alignment between laps from different sources.

Garage 61 CSVs and iRacing IBT files can disagree on where distance
zero is by several meters. Cross-correlating the speed traces finds
the best-fit offset; shifting the lap circularly (a lap is a loop)
corrects it. Without this, braking-point deltas are systematically wrong.
"""

from dataclasses import replace

import numpy as np

from core.telemetry.normalizer import NormalizedLap


def find_distance_offset(
    reference_speed: np.ndarray,
    comparison_speed: np.ndarray,
    max_offset_m: float = 150.0,
    interval_m: float = 1.0,
) -> int:
    """Find the distance offset (in samples) that best aligns comparison to reference.

    Returns the lag such that np.roll(comparison, -lag) best matches reference.
    Positive lag means the comparison trace is shifted forward relative
    to the reference.

    Args:
        reference_speed: Speed trace of the reference lap (m/s), one sample per meter.
        comparison_speed: Speed trace of the comparison lap (m/s), one sample per meter.
        max_offset_m: Maximum offset to search in either direction (meters).
        interval_m: Distance between samples (meters). Default 1.0 for 1m grids.

    Returns:
        Integer offset in samples. Apply np.roll(comparison, -offset) to align.
    """
    n = min(len(reference_speed), len(comparison_speed))
    ref = reference_speed[:n] - reference_speed[:n].mean()
    comp = comparison_speed[:n] - comparison_speed[:n].mean()

    max_lag = int(max_offset_m / interval_m)
    lags = np.arange(-max_lag, max_lag + 1)
    # Circular cross-correlation at each candidate lag (a lap is a loop)
    scores = np.array([np.dot(ref, np.roll(comp, -lag)) for lag in lags])
    return int(lags[int(np.argmax(scores))])


def shift_lap(lap: NormalizedLap, offset_samples: int) -> NormalizedLap:
    """Return a copy of the lap circularly shifted by offset_samples.

    Shifts all telemetry channels by offset_samples positions on the distance
    grid, wrapping around (since a lap is a closed loop). elapsed_time is
    rebuilt from rolled per-sample time deltas so it stays monotonic —
    rolling a cumulative array directly would not preserve monotonicity.

    Args:
        lap: The NormalizedLap to shift.
        offset_samples: Number of samples (meters) to shift. Positive shifts
            forward (toward higher distance indices), negative shifts back.

    Returns:
        A new NormalizedLap with all channels shifted and elapsed_time rebuilt.
    """
    if offset_samples == 0:
        return lap

    def roll(arr: np.ndarray) -> np.ndarray:
        return np.roll(arr, offset_samples)

    dt = np.diff(lap.elapsed_time, prepend=lap.elapsed_time[0])
    dt[0] = lap.elapsed_time[0]
    rolled_dt = np.roll(dt, offset_samples)
    new_elapsed = np.cumsum(rolled_dt)

    return replace(
        lap,
        speed=roll(lap.speed),
        throttle=roll(lap.throttle),
        brake=roll(lap.brake),
        steering=roll(lap.steering),
        gear=roll(lap.gear),
        rpm=roll(lap.rpm),
        lat=roll(lap.lat),
        lon=roll(lap.lon),
        elapsed_time=new_elapsed,
    )
