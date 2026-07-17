"""PURE per-combo readiness engine: watcher session history -> readiness.

Race-type sessions are EXCLUDED — race pace (traffic, fuel) would pollute
practice consistency; race tendencies live in racecraft.py instead.
Verdicts are benchmark-free: own progression + consistency only.

Representative-lap filter: only laps within REPRESENTATIVE_FACTOR (110%) of
the combo best count toward valid_laps, enough_data, and consistency_s. This
excludes out-laps, crawl laps, and installation laps that inflate counts and
corrupt stdev — the same 10% pace-threshold precedent as the coaching
analyzer's disrupted-lap filter.
"""

from statistics import median, stdev

from core.profile.models import (
    CONSISTENCY_MIN_LAPS,
    CONSISTENCY_WINDOW_SESSIONS,
    READINESS_MIN_LAPS,
    READINESS_MIN_SESSIONS,
    REPRESENTATIVE_FACTOR,
    TECHNIQUE_TREND_WINDOW,
    TTP_FACTOR,
    TTP_MIN_LAPS,
    ComboReadiness,
    TimeToPace,
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
        # Gather ALL is_valid lap times first; then filter to representative laps
        # (within 110% of the combo best). Out-laps, crawl laps, and
        # installation laps are telemetry-valid but pace-unrepresentative —
        # excluding them keeps valid_laps count and stdev meaningful.
        raw_valid: list[float] = []
        for s in rows:
            raw_valid.extend(
                l.lap_time for l in laps.get(s.session_id, []) if l.is_valid
            )
        combo_best_lap = min(raw_valid) if raw_valid else None
        cutoff = combo_best_lap * REPRESENTATIVE_FACTOR if combo_best_lap else None
        representative = (
            [t for t in raw_valid if t <= cutoff] if cutoff is not None else []
        )
        recent = rows[-CONSISTENCY_WINDOW_SESSIONS:]
        recent_valid = [
            l.lap_time
            for s in recent
            for l in laps.get(s.session_id, [])
            if l.is_valid
        ]
        recent_repr = (
            [t for t in recent_valid if t <= cutoff] if cutoff is not None else []
        )
        combos.append(ComboReadiness(
            track_id=track_id,
            track_name=rows[-1].track_name,
            car=car,
            sessions=len(with_best),
            valid_laps=len(representative),
            last_driven=rows[-1].session_date,
            best_lap=(
                min(s.best_lap_time for s in with_best) if with_best else None
            ),
            pb_trend_s=(
                with_best[0].best_lap_time - with_best[-1].best_lap_time
                if len(with_best) >= 2 else None
            ),
            consistency_s=(
                stdev(recent_repr)
                if len(recent_repr) >= CONSISTENCY_MIN_LAPS else None
            ),
            enough_data=(
                len(with_best) >= READINESS_MIN_SESSIONS
                and len(representative) >= READINESS_MIN_LAPS
            ),
        ))
    combos.sort(key=lambda c: -c.valid_laps)
    return combos


def build_time_to_pace(
    sessions: list[SessionRow],
    laps: dict[str, list[LapRow]],
) -> TimeToPace:
    """Median laps until the driver first laps within TTP_FACTOR of the
    session best. Practice sessions only; sessions shorter than
    TTP_MIN_LAPS valid laps don't count.

    Known caveat (accepted): ordinals count telemetry-valid laps only —
    true out-laps are usually normalizer-invalid and drop out, so
    "lap 3" means the third recorded flying-ish lap.
    """
    practice = [s for s in sessions if s.session_type != "Race"]
    ordinals: list[int] = []   # in session_date order
    for s in sorted(practice, key=lambda s: s.session_date):
        valid = sorted(
            (l for l in laps.get(s.session_id, []) if l.is_valid),
            key=lambda l: l.lap_number,
        )
        if len(valid) < TTP_MIN_LAPS:
            continue
        cutoff = min(l.lap_time for l in valid) * TTP_FACTOR
        for i, lap in enumerate(valid, start=1):
            if lap.lap_time <= cutoff:
                ordinals.append(i)
                break
    if not ordinals:
        return TimeToPace()
    recent = ordinals[-TECHNIQUE_TREND_WINDOW:]
    earlier = ordinals[:-TECHNIQUE_TREND_WINDOW]
    return TimeToPace(
        median_laps=float(median(ordinals)),
        sample_sessions=len(ordinals),
        trend_laps=(
            float(median(recent)) - float(median(earlier))
            if earlier else None
        ),
        enough_data=len(ordinals) >= READINESS_MIN_SESSIONS,
    )
