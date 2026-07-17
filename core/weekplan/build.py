# core/weekplan/build.py
"""Week-plan assembly: target-week math, tick decisions, and (Task 3)
the build itself. PURE except build_week_plan's api calls; never raises
to the caller — every failed sub-build degrades to a warning."""

from datetime import date, datetime, timedelta

from core.progression.streak import iracing_week_start
from core.weekplan.models import (
    REFRESH_MAX_AGE_S,
    REFRESH_MIN_INTERVAL_S,
    WeekPlan,
)


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
