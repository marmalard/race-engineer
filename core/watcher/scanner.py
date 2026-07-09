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


def should_promote(
    best_lap_time: float, existing_pb_time: float | None
) -> bool:
    """Promote when there is no personal_best yet, or this lap is strictly
    faster. (g61 rows are untouchable by construction — the watcher only
    ever writes source='personal_best'.)"""
    return existing_pb_time is None or best_lap_time < existing_pb_time
