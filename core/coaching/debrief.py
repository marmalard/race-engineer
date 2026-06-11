"""Debrief orchestrator: driver lap vs reference lap, loss-region first.

Replaces the corner-detection-driven analysis path. Pipeline:
align -> cumulative delta -> loss regions -> annotate -> diagnose.
Every number in the output is arithmetic on the aligned traces and
can be displayed for audit; the AI synthesis layer narrates these
numbers and nothing else.
"""

from dataclasses import dataclass

import numpy as np

from core.telemetry.alignment import find_distance_offset, shift_lap
from core.telemetry.loss_regions import LossRegion, find_loss_regions
from core.telemetry.normalizer import NormalizedLap
from core.track.models import Corner
from core.track.segment_annotator import annotate_region

BRAKE_THRESHOLD = 0.05
THROTTLE_THRESHOLD = 0.9
BRAKE_SEARCH_BACK_M = 200.0


@dataclass
class RegionDiagnosis:
    """Deterministic metrics for one loss region."""

    region: LossRegion
    label: str
    braking_delta_m: float | None  # negative = driver brakes earlier
    min_speed_delta_ms: float  # negative = driver over-slows
    throttle_delta_m: float | None  # positive = driver back on power later
    driver_min_speed_ms: float
    reference_min_speed_ms: float


@dataclass
class DebriefAnalysis:
    """Full debrief of one driver lap against the reference."""

    driver_lap_time: float
    reference_lap_time: float
    total_time_delta: float
    alignment_offset_m: float
    cumulative_delta: np.ndarray
    distance: np.ndarray
    diagnoses: list[RegionDiagnosis]


def _onset(
    mask: np.ndarray, start_idx: int, end_idx: int
) -> int | None:
    """First index in [start_idx, end_idx) where mask is True."""
    span = mask[start_idx:end_idx]
    hits = np.flatnonzero(span)
    return int(start_idx + hits[0]) if len(hits) else None


def _diagnose_region(
    region: LossRegion,
    driver: NormalizedLap,
    reference: NormalizedLap,
    corners: list[Corner],
    interval_m: float,
) -> RegionDiagnosis:
    n = min(len(driver.distance), len(reference.distance))
    start = max(0, int((region.distance_start - BRAKE_SEARCH_BACK_M) / interval_m))
    end = min(n, int(region.distance_end / interval_m) + 1)

    drv_brake = _onset(driver.brake[:n] > BRAKE_THRESHOLD, start, end)
    ref_brake = _onset(reference.brake[:n] > BRAKE_THRESHOLD, start, end)
    braking_delta = (
        (drv_brake - ref_brake) * interval_m
        if drv_brake is not None and ref_brake is not None
        else None
    )

    drv_min = float(driver.speed[start:end].min())
    ref_min = float(reference.speed[start:end].min())

    # Throttle pickup searched from each lap's min-speed point forward
    drv_apex = start + int(np.argmin(driver.speed[start:end]))
    ref_apex = start + int(np.argmin(reference.speed[start:end]))
    search_end = min(n, end + int(100 / interval_m))
    drv_thr = _onset(driver.throttle[:n] > THROTTLE_THRESHOLD, drv_apex, search_end)
    ref_thr = _onset(reference.throttle[:n] > THROTTLE_THRESHOLD, ref_apex, search_end)
    throttle_delta = (
        (drv_thr - ref_thr) * interval_m
        if drv_thr is not None and ref_thr is not None
        else None
    )

    return RegionDiagnosis(
        region=region,
        label=annotate_region(region, corners, track_length=driver.track_length),
        braking_delta_m=braking_delta,
        min_speed_delta_ms=drv_min - ref_min,
        throttle_delta_m=throttle_delta,
        driver_min_speed_ms=drv_min,
        reference_min_speed_ms=ref_min,
    )


def build_debrief(
    driver: NormalizedLap,
    reference: NormalizedLap,
    corners: list[Corner],
    top_n: int = 3,
) -> DebriefAnalysis:
    """Analyze one driver lap against the reference lap."""
    interval_m = float(driver.distance[1] - driver.distance[0])

    offset = find_distance_offset(driver.speed, reference.speed,
                                  interval_m=interval_m)
    aligned_ref = shift_lap(reference, -offset)

    n = min(len(driver.distance), len(aligned_ref.distance))
    cum_delta = (
        (driver.elapsed_time[:n] - driver.elapsed_time[0])
        - (aligned_ref.elapsed_time[:n] - aligned_ref.elapsed_time[0])
    )
    distance = driver.distance[:n]

    regions = find_loss_regions(cum_delta, distance)[:top_n]
    diagnoses = [
        _diagnose_region(r, driver, aligned_ref, corners, interval_m)
        for r in regions
    ]

    return DebriefAnalysis(
        driver_lap_time=driver.lap_time,
        reference_lap_time=reference.lap_time,
        total_time_delta=float(cum_delta[-1]) if n else 0.0,
        alignment_offset_m=offset * interval_m,
        cumulative_delta=cum_delta,
        distance=distance,
        diagnoses=diagnoses,
    )
