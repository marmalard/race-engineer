"""Pure discovery and promotion logic for the telemetry watcher.

No filesystem access here — the CLI gathers (path, mtime) tuples and the
sessions-table dedupe set; this module only decides. That keeps the whole
risk surface (stability windows, ordering, promotion policy) unit-testable.
"""

from dataclasses import dataclass
from pathlib import Path

# A file modified in the last MIN_AGE_S seconds is assumed still being
# written by iRacing (it appends to the .ibt for the whole session).
MIN_AGE_S = 90.0


@dataclass
class IbtCandidate:
    """One .ibt file as seen by the CLI's folder listing."""

    path: Path
    mtime: float


def find_new_ibts(
    candidates: list[IbtCandidate],
    processed: set[str],
    now: float,
    min_age_s: float = MIN_AGE_S,
) -> list[IbtCandidate]:
    """Unprocessed, write-stable candidates, oldest first."""
    fresh = [
        c for c in candidates
        if str(c.path) not in processed and (now - c.mtime) >= min_age_s
    ]
    return sorted(fresh, key=lambda c: c.mtime)


def is_plausible_lap(
    lap_time_s: float,
    track_length_m: float,
    max_avg_speed_mps: float = 85.0,
) -> bool:
    """True if a lap time is physically achievable for the track length.

    A lap whose implied average speed exceeds ``max_avg_speed_mps``
    (85 m/s ~= 306 km/h) cannot be real — no iRacing car averages that
    over a full lap. Such "laps" come from towed / reset / aborted laps
    whose recorded time covers only a fraction of the track distance yet
    still clears the normalizer's 90% coverage check (a stationary tow
    teleport inflates LapDist coverage; a car that stops at ~92% around
    barely clears the bar). Left ungated, one becomes an unbeatable
    "personal best" and permanently blocks real laps from promotion.

    This is the promotion path's defense in depth — the ReferenceStore is
    the live coach's ground truth, so it must never ingest an impossible
    lap regardless of upstream validity.

    Fails closed on non-positive lap times; passes when the track length
    is unknown (<= 0), since plausibility cannot be judged without it.
    """
    if lap_time_s <= 0:
        return False
    if track_length_m <= 0:
        return True
    return (track_length_m / lap_time_s) <= max_avg_speed_mps


def should_promote(
    best_lap_time: float, existing_pb_time: float | None
) -> bool:
    """Promote when there is no personal_best yet, or this lap is strictly
    faster. (g61 rows are untouchable by construction — the watcher only
    ever writes source='personal_best'.)"""
    return existing_pb_time is None or best_lap_time < existing_pb_time
