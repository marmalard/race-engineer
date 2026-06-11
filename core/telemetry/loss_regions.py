"""Loss-region extraction from cumulative time-delta traces.

The analysis primitive of the coaching debrief. Given the cumulative
time delta between a driver lap and a reference lap (positive = driver
slower), a loss region is a contiguous span of track where the delta
grows. Time lost per region is arithmetic on the trace — no corner
detection involved, so it cannot be wrong about *where* time was lost.
"""

from dataclasses import dataclass

import numpy as np
from scipy.signal import savgol_filter


@dataclass
class LossRegion:
    """A contiguous span of track where the driver loses time to the reference."""

    distance_start: float  # meters from start/finish
    distance_end: float
    time_lost: float  # seconds (always positive)


def find_loss_regions(
    cum_delta: np.ndarray,
    distance: np.ndarray,
    min_loss_s: float = 0.05,
    merge_gap_m: float = 30.0,
    smooth_window: int = 21,
    grow_threshold_s_per_m: float = 0.0005,
) -> list[LossRegion]:
    """Extract loss regions from a cumulative time-delta trace.

    Args:
        cum_delta: driver_elapsed - reference_elapsed at each distance point.
        distance: matching distance grid (uniform spacing assumed).
        min_loss_s: regions losing less than this are noise, dropped.
        merge_gap_m: adjacent regions closer than this merge (chicanes).
        smooth_window: Savitzky-Golay window for the gradient (odd).
        grow_threshold_s_per_m: minimum delta slope to count as "losing time".

    Returns:
        LossRegions sorted by time_lost descending.
    """
    n = min(len(cum_delta), len(distance))
    if n < smooth_window:
        return []
    delta = cum_delta[:n]
    dist = distance[:n]
    interval = float(dist[1] - dist[0]) if n > 1 else 1.0

    smoothed = savgol_filter(delta, smooth_window, 3)
    slope = np.gradient(smoothed, dist)
    losing = slope > grow_threshold_s_per_m

    # Contiguous True spans -> candidate regions
    edges = np.flatnonzero(np.diff(losing.astype(int)))
    starts = list(edges[losing[edges + 1]] + 1)
    ends = list(edges[~losing[edges + 1]] + 1)
    if losing[0]:
        starts.insert(0, 0)
    if losing[-1]:
        ends.append(n)

    spans = list(zip(starts, ends))

    # Merge spans separated by less than merge_gap_m
    merged: list[tuple[int, int]] = []
    gap_samples = int(merge_gap_m / interval)
    for start, end in spans:
        if merged and start - merged[-1][1] <= gap_samples:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))

    regions = []
    for start, end in merged:
        time_lost = float(delta[min(end, n - 1)] - delta[start])
        if time_lost >= min_loss_s:
            regions.append(
                LossRegion(
                    distance_start=float(dist[start]),
                    distance_end=float(dist[min(end, n - 1)]),
                    time_lost=time_lost,
                )
            )

    regions.sort(key=lambda r: r.time_lost, reverse=True)
    return regions
