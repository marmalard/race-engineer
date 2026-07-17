# core/weekplan/build.py
"""Week-plan assembly: target-week math, tick decisions, and (Task 3)
the build itself. PURE except build_week_plan's api calls; never raises
to the caller -- every failed sub-build degrades to a warning."""

from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from core.briefing.curve import MIN_BIN_N, place_on_curve
from core.briefing.ingest import harvest_field, rank_series_candidates
from core.briefing.slots import infer_window, slot_fits_window, upcoming_slots
from core.live.nudges import fault_kinds_from_diagnosis
from core.profile.models import TechniqueTendencies, TimeToPace
from core.profile.pace import build_readiness
from core.profile.prescriptions import PRESCRIPTIONS
from core.profile.render import FAULT_LABELS
from core.profile.technique import diagnosis_from_row
from core.progression.streak import iracing_week_start
from core.track.track_db import DiagnosisRow, LapRow, SessionRow
from core.weekplan.models import (
    REFRESH_MAX_AGE_S,
    REFRESH_MIN_INTERVAL_S,
    SR_COMFORT,
    PlanSlot,
    PracticeHalf,
    RaceHalf,
    SRCheck,
    WeekPlan,
)

DEFAULT_CACHE_DIR = Path("data/briefing_cache")


def week_delta(today: date) -> int:
    """0 = plan for the running week (Tue-Sat); 1 = the upcoming week
    (Sun/Mon — the plan lands before the Tuesday flip)."""
    return 1 if today.weekday() in (6, 0) else 0


def target_week_start(today: date) -> date:
    """The Tuesday of the week the plan is FOR."""
    return iracing_week_start(today) + timedelta(days=7 * week_delta(today))


def should_generate(today: date, latest_plan_week: str | None) -> bool:
    """Generate whenever no stored plan exists for the target week."""
    return latest_plan_week != target_week_start(today).isoformat()


def should_refresh(plan: WeekPlan, now_utc: datetime, today: date) -> bool:
    """Refresh the target week's plan at most hourly, and only while the
    curve is unfilled or the plan has gone a day without an update."""
    if plan.week_start != target_week_start(today).isoformat():
        return False
    updated = datetime.fromisoformat(plan.updated_at)
    age_s = (now_utc - updated).total_seconds()
    if age_s < REFRESH_MIN_INTERVAL_S:
        return False
    return (not plan.curve_filled) or age_s >= REFRESH_MAX_AGE_S


def sports_car_license(member_info: dict) -> tuple[str, float] | None:
    """(group_name, safety_rating) for the sports-car license, tolerant
    of dict- or list-shaped licenses payloads. None when absent."""
    licenses = member_info.get("licenses")
    if isinstance(licenses, dict):
        entries = list(licenses.values())
    elif isinstance(licenses, list):
        entries = licenses
    else:
        return None
    for e in entries:
        if not isinstance(e, dict):
            continue
        if e.get("category") == "sports_car" or e.get("category_id") == 5:
            sr = e.get("safety_rating")
            if isinstance(sr, (int, float)):
                return (str(e.get("group_name") or ""), float(sr))
    return None


def _most_practiced_car(
    sessions: list[SessionRow], track_id: str | None
) -> str | None:
    """Most-practiced (non-Race) car at a track, or overall when
    track_id is None."""
    counts: Counter = Counter(
        s.car for s in sessions
        if s.session_type != "Race"
        and (track_id is None or s.track_id == track_id)
    )
    return counts.most_common(1)[0][0] if counts else None


def _latest_top_region(
    diagnoses: list[DiagnosisRow],
) -> DiagnosisRow | None:
    """The rank-1 region of the most recent diagnosed session."""
    ranked = [d for d in diagnoses if d.region_rank == 1]
    if not ranked:
        return None
    return max(ranked, key=lambda d: d.session_date)


def _build_race_half(
    api,
    seasons,
    sessions: list[SessionRow],
    laps: dict[str, list[LapRow]],
    delta: int,
    now_utc: datetime,
    cache_dir: Path,
) -> tuple[RaceHalf | None, bool, list[str]]:
    warnings: list[str] = []
    candidates = [
        c for c in rank_series_candidates(seasons, sessions,
                                          week_delta=delta)
        if c.practice_sessions > 0
    ]
    if not candidates:
        return None, False, [
            "No target-week series at a track you've practiced -- the "
            "Race Briefing page lists the full calendar."
        ]
    cand = candidates[0]
    season = next(s for s in seasons if s.season_id == cand.season_id)
    week = next(w for w in season.weeks
                if w.race_week_num == cand.race_week)

    car = _most_practiced_car(sessions, str(cand.track_id))
    if car is None:
        car = _most_practiced_car(sessions, None) or ""
        warnings.append(
            "No practice at this track yet -- recommending your usual car."
        )

    window = infer_window([s.session_date for s in sessions])
    slots = [
        PlanSlot(start_utc=dt.isoformat(),
                 fits_window=slot_fits_window(dt, window))
        for dt in upcoming_slots(week.race_time_descriptors, now_utc,
                                 count=4)
    ]

    readiness = build_readiness(sessions, laps)
    combo = next(
        (r for r in readiness
         if r.track_id == str(cand.track_id) and r.car == car),
        None,
    )
    half = RaceHalf(
        series_name=cand.series_name, season_id=cand.season_id,
        race_week=cand.race_week, track_id=str(cand.track_id),
        track_name=cand.track_name, config_name=week.config_name,
        car=car, slots=slots, race_time_limit=week.race_time_limit,
        race_lap_limit=week.race_lap_limit,
        standing_start=week.standing_start,
        prep_sessions=combo.sessions if combo else 0,
        prep_best_lap_s=combo.best_lap if combo else None,
    )

    curve_filled = False
    try:
        curve, stats = harvest_field(
            api, cand.season_id, cand.race_week, cache_dir,
            season_year=season.season_year,
            season_quarter=season.season_quarter,
        )
        if curve.bins and len(curve.points) >= MIN_BIN_N:
            curve_filled = True
            if half.prep_best_lap_s is not None:
                placement = place_on_curve(curve, half.prep_best_lap_s,
                                           None)
                half.implied_ir_lo = placement.implied_ir_lo
                half.implied_ir_hi = placement.implied_ir_hi
            if stats is not None:
                half.sof_median = stats.sof_median
                half.splits_median = stats.splits_median
        # empty pre-flip curve is EXPECTED: unfilled, not a warning
    except Exception as exc:  # noqa: BLE001 -- degrade, never raise
        warnings.append(f"Field harvest failed ({exc}) -- verdict pending.")
    return half, curve_filled, warnings


def _ttp_line(time_to_pace: TimeToPace) -> str:
    if not time_to_pace.enough_data or time_to_pace.median_laps is None:
        return ""
    return (
        f"You need ~{round(time_to_pace.median_laps)} laps to reach pace "
        f"-- races give you zero. Arrive early."
    )


def _practice_from_fallback(
    race: RaceHalf | None,
    diagnoses: list[DiagnosisRow],
    ttp_line: str,
) -> PracticeHalf:
    combo = (
        f"{race.track_name} in the {race.car}" if race and race.car
        else "your latest combo"
    )
    half = PracticeHalf(kind="race_combo", combo=combo, ttp_line=ttp_line)
    latest = _latest_top_region(diagnoses)
    if latest is not None:
        half.goal_label = latest.label
        kinds = fault_kinds_from_diagnosis(diagnosis_from_row(latest))
        if kinds:
            half.goal_fault = FAULT_LABELS.get(kinds[0].value, "")
        half.goal_time_lost_s = latest.time_lost_s
    return half


def _build_practice_half(
    technique: TechniqueTendencies,
    time_to_pace: TimeToPace,
    diagnoses: list[DiagnosisRow],
    race: RaceHalf | None,
) -> PracticeHalf:
    ttp = _ttp_line(time_to_pace)
    if technique.enough_data and technique.dominant:
        row = next(
            (p for p in PRESCRIPTIONS if p.fault == technique.dominant),
            None,
        )
        if row is not None:
            return PracticeHalf(
                kind="prescription", combo=row.combo, fault=row.fault,
                skill_line=row.skill_line,
                transfer_line=row.transfer_line, ttp_line=ttp,
            )
    return _practice_from_fallback(race, diagnoses, ttp)


def build_week_plan(
    api,
    seasons,
    sessions: list[SessionRow],
    laps: dict[str, list[LapRow]],
    diagnoses: list[DiagnosisRow],
    technique: TechniqueTendencies,
    time_to_pace: TimeToPace,
    now_utc: datetime,
    today: date,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> WeekPlan:
    """Assemble the week plan. Never raises -- every failed sub-build
    degrades to None + a warning (the build_briefing precedent)."""
    now_iso = now_utc.isoformat()
    plan = WeekPlan(
        week_start=target_week_start(today).isoformat(),
        created_at=now_iso, updated_at=now_iso,
    )
    try:
        plan.race, plan.curve_filled, race_warnings = _build_race_half(
            api, seasons, sessions, laps, week_delta(today), now_utc,
            cache_dir,
        )
        plan.warnings.extend(race_warnings)
    except Exception as exc:  # noqa: BLE001
        plan.warnings.append(f"Race half unavailable ({exc}).")
    try:
        plan.practice = _build_practice_half(
            technique, time_to_pace, diagnoses, plan.race,
        )
    except Exception as exc:  # noqa: BLE001
        plan.warnings.append(f"Practice half unavailable ({exc}).")
    try:
        info = api.get_member_info() if api is not None else {}
        lic = sports_car_license(info or {})
        if lic is not None:
            plan.sr = SRCheck(
                license_class=lic[0], safety_rating=lic[1],
                comfortable=lic[1] >= SR_COMFORT,
            )
        else:
            plan.warnings.append("License info unavailable.")
    except Exception:  # noqa: BLE001
        plan.warnings.append("License info unavailable.")
    return plan
