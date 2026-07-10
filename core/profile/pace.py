"""PURE per-combo readiness engine: watcher session history -> readiness.

Race-type sessions are EXCLUDED — race pace (traffic, fuel) would pollute
practice consistency; race tendencies live in racecraft.py instead.
Verdicts are benchmark-free: own progression + consistency only.
"""

from statistics import stdev

from core.profile.models import (
    CONSISTENCY_MIN_LAPS,
    CONSISTENCY_WINDOW_SESSIONS,
    READINESS_MIN_LAPS,
    READINESS_MIN_SESSIONS,
    ComboReadiness,
)
from core.track.track_db import LapRow, SessionRow


def build_readiness(
    sessions: list[SessionRow],
    laps: dict[str, list[LapRow]],
) -> list[ComboReadiness]:
    """Per-combo readiness, most-practiced first. `laps` maps session_id ->
    that session's lap rows (missing keys = no laps recorded)."""
    practice = [s for s in sessions if s.session_type != "Race"]
    by_combo: dict[tuple[str, str], list[SessionRow]] = {}
    # session_date is "YYYY-MM-DD HH-MM-SS" from the watcher — lexical sort
    # is correct for that format. A renamed IBT stores a garbage substring
    # (metadata-only by design) and sorts arbitrarily; acceptable degradation.
    for s in sorted(practice, key=lambda s: s.session_date):
        by_combo.setdefault((s.track_id, s.car), []).append(s)

    combos: list[ComboReadiness] = []
    for (track_id, car), rows in by_combo.items():
        with_best = [s for s in rows if s.best_lap_time is not None]
        valid_lap_times: list[float] = []
        for s in rows:
            valid_lap_times.extend(
                l.lap_time for l in laps.get(s.session_id, []) if l.is_valid
            )
        recent = rows[-CONSISTENCY_WINDOW_SESSIONS:]
        recent_valid = [
            l.lap_time
            for s in recent
            for l in laps.get(s.session_id, [])
            if l.is_valid
        ]
        combos.append(ComboReadiness(
            track_id=track_id,
            track_name=rows[-1].track_name,
            car=car,
            sessions=len(with_best),
            valid_laps=len(valid_lap_times),
            last_driven=rows[-1].session_date,
            best_lap=(
                min(s.best_lap_time for s in with_best) if with_best else None
            ),
            pb_trend_s=(
                with_best[0].best_lap_time - with_best[-1].best_lap_time
                if len(with_best) >= 2 else None
            ),
            consistency_s=(
                stdev(recent_valid)
                if len(recent_valid) >= CONSISTENCY_MIN_LAPS else None
            ),
            enough_data=(
                len(with_best) >= READINESS_MIN_SESSIONS
                and len(valid_lap_times) >= READINESS_MIN_LAPS
            ),
        ))
    combos.sort(key=lambda c: -c.valid_laps)
    return combos
