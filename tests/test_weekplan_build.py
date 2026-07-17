# tests/test_weekplan_build.py
"""Week-plan target-week math and generate/refresh decisions."""

from datetime import date, datetime, timedelta, timezone

from core.weekplan.build import (
    should_generate, should_refresh, target_week_start, week_delta,
)
from core.weekplan.models import WeekPlan


def _plan(week_start="2026-07-14", updated_at=None, curve_filled=False):
    now = updated_at or datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    return WeekPlan(
        week_start=week_start,
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
        curve_filled=curve_filled,
    )


class TestTargetWeek:
    # 2026-07-14 is a Tuesday; 07-19 Sunday; 07-20 Monday; 07-21 Tuesday.
    def test_tue_through_sat_target_current_week(self):
        assert target_week_start(date(2026, 7, 14)) == date(2026, 7, 14)
        assert target_week_start(date(2026, 7, 18)) == date(2026, 7, 14)

    def test_sunday_and_monday_target_next_week(self):
        assert target_week_start(date(2026, 7, 19)) == date(2026, 7, 21)
        assert target_week_start(date(2026, 7, 20)) == date(2026, 7, 21)

    def test_week_delta_matches(self):
        assert week_delta(date(2026, 7, 18)) == 0   # Saturday
        assert week_delta(date(2026, 7, 19)) == 1   # Sunday


class TestShouldGenerate:
    def test_no_plan_yet_generates(self):
        assert should_generate(date(2026, 7, 19), None) is True

    def test_plan_for_target_week_exists_no_generate(self):
        assert should_generate(date(2026, 7, 19), "2026-07-21") is False

    def test_stale_last_week_plan_generates(self):
        assert should_generate(date(2026, 7, 19), "2026-07-14") is True

    def test_midweek_first_run_generates_for_current_week(self):
        assert should_generate(date(2026, 7, 15), None) is True


class TestShouldRefresh:
    NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    TODAY = date(2026, 7, 15)  # Wednesday -> target week 2026-07-14

    def test_wrong_week_never_refreshes(self):
        plan = _plan(week_start="2026-07-07")
        assert should_refresh(plan, self.NOW, self.TODAY) is False

    def test_hourly_throttle(self):
        plan = _plan(updated_at=self.NOW - timedelta(minutes=30))
        assert should_refresh(plan, self.NOW, self.TODAY) is False

    def test_unfilled_curve_refreshes_after_an_hour(self):
        plan = _plan(updated_at=self.NOW - timedelta(hours=2))
        assert should_refresh(plan, self.NOW, self.TODAY) is True

    def test_filled_and_fresh_is_noop(self):
        plan = _plan(updated_at=self.NOW - timedelta(hours=2),
                     curve_filled=True)
        assert should_refresh(plan, self.NOW, self.TODAY) is False

    def test_filled_but_daily_stale_refreshes(self):
        plan = _plan(updated_at=self.NOW - timedelta(hours=25),
                     curve_filled=True)
        assert should_refresh(plan, self.NOW, self.TODAY) is True
