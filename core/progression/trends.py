"""PURE trend-series builders for the Progression page.

Fault classification goes through the technique adapter and the live
FaultKind ladder — one ranking function, four consumers (cue, verdict,
profile tendencies, progression trends). Never re-implement thresholds.
"""

from collections import defaultdict

from core.benchmark.reference_store import ReferenceLapMeta
from core.live.nudges import fault_kinds_from_diagnosis
from core.profile.technique import diagnosis_from_row
from core.track.track_db import DiagnosisRow, SessionRow


def combo_pace_series(
    sessions: list[SessionRow],
) -> dict[tuple[str, str], list[tuple[str, float]]]:
    """(track_id, car) -> [(session_date, session_best_s)] date-ascending.

    Race sessions are excluded (traffic/fuel pace is not practice pace),
    as are sessions with no recorded best lap.
    """
    series: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
    for s in sessions:
        if s.session_type == "Race" or s.best_lap_time is None:
            continue
        series[(s.track_id, s.car)].append((s.session_date, s.best_lap_time))
    return {k: sorted(v) for k, v in series.items()}


def fault_trend_series(
    rows: list[DiagnosisRow],
) -> dict[str, list[tuple[str, float]]]:
    """FaultKind.value -> [(session_date, summed time_lost_s)] date-ascending.

    Per session, time_lost of every region where the fault crossed its
    live threshold is summed — 'how much did this habit cost per outing'.
    """
    per_kind: dict[str, dict[tuple[str, str], float]] = defaultdict(
        lambda: defaultdict(float)
    )
    for r in rows:
        for kind in fault_kinds_from_diagnosis(diagnosis_from_row(r)):
            per_kind[kind.value][(r.session_date, r.session_id)] += r.time_lost_s
    return {
        k: [(d, round(t, 6)) for (d, _sid), t in sorted(buckets.items())]
        for k, buckets in per_kind.items()
    }


def pb_timeline(metas: list[ReferenceLapMeta]) -> list[ReferenceLapMeta]:
    """personal_best references only, oldest first by imported_at."""
    return sorted(
        (m for m in metas if m.source == "personal_best"),
        key=lambda m: m.imported_at,
    )
