"""Nav registration + the page's pure helper."""

from app.navigation import NAV_SPEC
from app.pages.week_plan import _current_week_plan


class TestNavRegistration:
    def test_week_plan_second_in_race_group(self):
        race = dict(NAV_SPEC)["Race"]
        assert race[1].title == "Week Plan"
        assert race[1].url_path == "week-plan"


class TestCurrentWeekPlan:
    def test_store_error_returns_none(self):
        class _Boom:
            def get(self, week):
                raise RuntimeError("locked")

        assert _current_week_plan(_Boom()) is None

    def test_returns_target_week_plan(self):
        from datetime import date
        from core.weekplan.build import target_week_start
        from core.weekplan.models import WeekPlan
        week = target_week_start(date.today()).isoformat()
        plan = WeekPlan(week_start=week, created_at="x", updated_at="x")

        class _Store:
            def get(self, w):
                return plan if w == week else None

        assert _current_week_plan(_Store()) is plan
