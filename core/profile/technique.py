"""PURE cross-session technique tendencies from persisted region diagnoses.

The vocabulary is the live coach's FaultKind ladder: the adapter rebuilds
RegionDiagnosis objects from stored rows and classifies them with the SAME
fault_kinds_from_diagnosis used by cues and exit verdicts — the profile
can never disagree with the radio.
"""

from collections import Counter, defaultdict

from core.coaching.debrief import RegionDiagnosis
from core.live.nudges import fault_kinds_from_diagnosis
from core.profile.models import (
    RECURRING_CORNER_MIN,
    TECHNIQUE_MIN_SESSIONS,
    TECHNIQUE_TREND_WINDOW,
    FaultAggregate,
    TechniqueTendencies,
)
from core.telemetry.loss_regions import LossRegion
from core.track.track_db import DiagnosisRow


def _diagnosis_from_row(row: DiagnosisRow) -> RegionDiagnosis:
    """Rebuild the analysis dataclass from a stored row (deltas mapped 1:1;
    the live-prompt reference absolutes stay None — tendencies don't use
    them, and they were never persisted)."""
    return RegionDiagnosis(
        region=LossRegion(
            distance_start=row.distance_start_m,
            distance_end=row.distance_end_m,
            time_lost=row.time_lost_s,
        ),
        label=row.label,
        braking_delta_m=row.braking_delta_m,
        min_speed_delta_ms=row.min_speed_delta_ms,
        throttle_delta_m=row.throttle_delta_m,
        driver_min_speed_ms=row.driver_min_speed_ms,
        reference_min_speed_ms=row.reference_min_speed_ms,
        brake_release_delta_m=row.brake_release_delta_m,
        exit_speed_delta_ms=row.exit_speed_delta_ms,
    )


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def build_technique(rows: list[DiagnosisRow]) -> TechniqueTendencies:
    """Aggregate stored diagnosis rows into technique tendencies."""
    if not rows:
        return TechniqueTendencies()

    session_dates: dict[str, str] = {}
    for r in rows:
        session_dates.setdefault(r.session_id, r.session_date)
    ordered = sorted(session_dates, key=lambda s: session_dates[s])
    recent_ids = set(ordered[-TECHNIQUE_TREND_WINDOW:])
    earlier_ids = set(ordered[:-TECHNIQUE_TREND_WINDOW])

    occurrences: Counter = Counter()
    combos: dict[str, set] = defaultdict(set)
    losses: dict[str, list[float]] = defaultdict(list)
    recent_losses: dict[str, list[float]] = defaultdict(list)
    earlier_losses: dict[str, list[float]] = defaultdict(list)
    labels: Counter = Counter()

    for r in rows:
        # Position-fallback labels ("~4.4 km from start/finish") are not
        # a corner identity — never a "recurring corner".
        if not r.label.startswith("~"):
            labels[r.label] += 1
        for kind in fault_kinds_from_diagnosis(_diagnosis_from_row(r)):
            k = kind.value
            occurrences[k] += 1
            combos[k].add((r.track_id, r.car))
            losses[k].append(r.time_lost_s)
            if r.session_id in recent_ids:
                recent_losses[k].append(r.time_lost_s)
            elif r.session_id in earlier_ids:
                earlier_losses[k].append(r.time_lost_s)

    faults = [
        FaultAggregate(
            kind=k,
            occurrences=n,
            combos=len(combos[k]),
            mean_time_lost_s=_mean(losses[k]),
            trend_time_lost_s=(
                _mean(recent_losses[k]) - _mean(earlier_losses[k])
                if recent_losses[k] and earlier_losses[k] else None
            ),
        )
        for k, n in occurrences.items()
    ]
    faults.sort(key=lambda f: (-f.occurrences, -f.mean_time_lost_s))
    recurring = [(label, c) for label, c in labels.most_common()
                 if c >= RECURRING_CORNER_MIN]
    n_sessions = len(ordered)
    return TechniqueTendencies(
        dominant=faults[0].kind if faults else None,
        faults=faults,
        recurring_corners=recurring,
        sessions_diagnosed=n_sessions,
        enough_data=n_sessions >= TECHNIQUE_MIN_SESSIONS,
    )
