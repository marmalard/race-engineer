"""Coaching analysis orchestrator.

Takes raw IBT telemetry and runs the full pipeline:
parse → normalize → detect corners → compare laps → consistency analysis
→ prioritized coaching output.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from core.telemetry.ibt_parser import IBTParser
from core.telemetry.normalizer import Normalizer, NormalizedLap
from core.telemetry.corner_detector import CornerDetector, LapSegmentation
from core.telemetry.lap_comparator import (
    LapComparator,
    LapComparison,
    TheoreticalBest,
    ConsistencyAnalysis,
)


@dataclass
class PriorityCorner:
    """A corner ranked by coaching priority (most time available)."""

    corner_number: int
    corner_name: str | None  # From TrackDB via CornerRegistry (None if unmatched)
    time_lost: float  # seconds lost vs best lap (positive = slower)
    issue_type: str  # "consistency", "technique", or "both"
    braking_delta: float  # meters (positive = brakes later)
    apex_speed_delta: float  # m/s (positive = faster at apex)
    exit_speed_delta: float  # m/s
    throttle_delta: float  # meters (positive = gets on throttle later)


@dataclass
class CoachingAnalysis:
    """Complete coaching analysis for a session."""

    track_name: str
    car_name: str
    lap_count: int
    valid_lap_count: int
    best_lap_time: float
    theoretical_best_time: float
    gap_to_theoretical: float
    best_lap: NormalizedLap
    comparison_lap: NormalizedLap
    lap_comparison: LapComparison
    segmentation: LapSegmentation
    theoretical_best: TheoreticalBest
    consistency: list[ConsistencyAnalysis]
    priority_corners: list[PriorityCorner]
    corner_names: dict[int, str]  # corner_number -> name (for UI/plots)
    all_laps: list[NormalizedLap]
    lap_times: list[tuple[int, float]]  # (lap_number, lap_time) for all valid laps


def analyze_session(
    ibt_data: bytes | Path,
    track_type: str = "road",
    db_path: Path | None = None,
) -> CoachingAnalysis:
    """Run the full coaching analysis pipeline on an IBT file.

    Args:
        ibt_data: Raw IBT file bytes (from upload) or Path to file.
        track_type: Track type for corner detection tuning ('road', 'street', 'oval').
        db_path: Path to tracks.db for corner name lookup. If None, names are omitted.

    Returns:
        CoachingAnalysis with all structured data needed for coaching.

    Raises:
        ValueError: If fewer than 2 valid laps are found.
    """
    parser = IBTParser()
    normalizer = Normalizer(distance_interval=1.0)

    # 1. Parse
    ibt = parser.parse(ibt_data)
    track_name = ibt.session.track_name
    car_name = ibt.session.car_name
    track_length_m = ibt.session.track_length_km * 1000

    # 2. Split into laps, normalize, then filter disrupted laps by pace
    raw_laps = parser.get_laps(ibt)
    lap_numbers = [int(df["Lap"].iloc[0]) for df in raw_laps]
    all_laps = normalizer.normalize_session(raw_laps, lap_numbers, track_length_m)
    all_laps = _filter_disrupted_laps(all_laps)

    if len(all_laps) < 2:
        raise ValueError(
            f"Need at least 2 valid laps for coaching analysis, "
            f"got {len(all_laps)} from {len(raw_laps)} raw laps."
        )

    # 3. Find best lap and median-pace comparison lap
    sorted_laps = sorted(all_laps, key=lambda l: l.lap_time)
    best_lap = sorted_laps[0]

    # Use median-pace lap for comparison (more representative than worst)
    median_idx = len(sorted_laps) // 2
    comparison_lap = sorted_laps[median_idx]

    # If median is the best lap (only 2 laps), use the other one
    if comparison_lap.lap_number == best_lap.lap_number:
        comparison_lap = sorted_laps[-1]

    # 4. Detect corners on the best lap
    detector = CornerDetector.for_track_type(track_type)
    segmentation = detector.detect(best_lap)

    # 4b. Match detected corners to named corners from database
    corner_names: dict[int, str] = {}
    if db_path is not None:
        corner_names = _match_corner_names(
            db_path, str(ibt.session.track_id), segmentation.corners
        )

    # 5. Compare best vs comparison
    comparator = LapComparator()
    lap_comparison = comparator.compare_laps(best_lap, comparison_lap, segmentation)

    # 6. Theoretical best and consistency
    theoretical = comparator.theoretical_best(all_laps, segmentation)
    consistency = comparator.consistency_analysis(all_laps, segmentation)

    # 6b. Populate corner names on consistency entries
    for ca in consistency:
        ca.corner_name = corner_names.get(ca.corner_number)

    # 7. Build priority corners — rank by time lost
    consistency_map = {c.corner_number: c for c in consistency}
    priority_corners = _rank_priority_corners(lap_comparison, consistency_map, corner_names)

    # 8. Lap times for display
    lap_times = [(l.lap_number, l.lap_time) for l in sorted_laps]

    return CoachingAnalysis(
        track_name=track_name,
        car_name=car_name,
        lap_count=len(raw_laps),
        valid_lap_count=len(all_laps),
        best_lap_time=best_lap.lap_time,
        theoretical_best_time=theoretical.theoretical_time,
        gap_to_theoretical=theoretical.gap_to_theoretical,
        best_lap=best_lap,
        comparison_lap=comparison_lap,
        lap_comparison=lap_comparison,
        segmentation=segmentation,
        theoretical_best=theoretical,
        consistency=consistency,
        priority_corners=priority_corners,
        corner_names=corner_names,
        all_laps=all_laps,
        lap_times=lap_times,
    )


def _rank_priority_corners(
    comparison: LapComparison,
    consistency_map: dict[int, ConsistencyAnalysis],
    corner_names: dict[int, str] | None = None,
) -> list[PriorityCorner]:
    """Rank corners by how much time is available, taking the top 3."""
    names = corner_names or {}
    corners: list[PriorityCorner] = []

    for cd in comparison.corner_deltas:
        cn = cd.corner.corner_number
        cons = consistency_map.get(cn)

        if cons is not None:
            if cons.is_consistency_issue:
                issue_type = "consistency"
            elif cons.is_technique_issue:
                issue_type = "technique"
            else:
                issue_type = "minor"
        else:
            issue_type = "technique" if abs(cd.time_delta) > 0.3 else "minor"

        corners.append(
            PriorityCorner(
                corner_number=cn,
                corner_name=names.get(cn),
                time_lost=cd.time_delta,
                issue_type=issue_type,
                braking_delta=cd.braking_point_delta,
                apex_speed_delta=cd.apex_speed_delta,
                exit_speed_delta=cd.exit_speed_delta,
                throttle_delta=cd.throttle_application_delta,
            )
        )

    # Sort by absolute time lost (most time first), take top 3
    corners.sort(key=lambda c: abs(c.time_lost), reverse=True)
    return corners[:3]


def _filter_disrupted_laps(laps: list[NormalizedLap]) -> list[NormalizedLap]:
    """Remove laps that were significantly disrupted (spins, stalls, long off-tracks).

    Rather than filtering on incident count (which excludes minor 1x
    off-tracks that don't meaningfully affect pace), we filter on lap
    time. Any lap >10% slower than the fastest is likely disrupted.
    This keeps laps with minor incidents that are still representative.
    """
    if len(laps) < 2:
        return laps

    fastest = min(l.lap_time for l in laps)
    threshold = fastest * 1.10  # 10% slower = likely a spin or stall
    return [l for l in laps if l.lap_time <= threshold]


def _match_corner_names(
    db_path: Path,
    track_id: str,
    detected_corners: list,
) -> dict[int, str]:
    """Match detected corners to named corners in the database.

    Lazy-seeds from Crew Chief data if the track has no named corners yet.
    Returns a dict of corner_number -> corner_name for matched corners.
    """
    import logging

    from core.track.corner_registry import CornerRegistry
    from core.track.crew_chief_seeder import seed_track_by_id
    from core.track.track_db import TrackDB

    logger = logging.getLogger(__name__)

    try:
        db = TrackDB(db_path)

        # Lazy-seed from Crew Chief if no named corners exist
        existing = db.get_corners(track_id)
        if not existing or not any(c.name for c in existing):
            cache_path = db_path.parent / "crew_chief_cache.json"
            seed_track_by_id(db, track_id, cache_path)

        # Match detected corners to DB corners
        registry = CornerRegistry(db)
        matches = registry.match_corners(track_id, detected_corners)

        corner_names: dict[int, str] = {}
        for detected, db_corner in matches:
            if db_corner and db_corner.name:
                corner_names[detected.corner_number] = db_corner.name

        if corner_names:
            logger.info(
                "Matched %d/%d corners to named corners for track %s",
                len(corner_names),
                len(detected_corners),
                track_id,
            )
        return corner_names

    except Exception as exc:
        logger.warning("Corner name matching failed: %s", exc)
        return {}
