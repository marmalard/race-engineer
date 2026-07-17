"""Race-week streak math — iRacing weeks flip on Tuesday."""

from datetime import date

from core.progression.models import StreakSummary
from core.progression.streak import build_streak, iracing_week_start, parse_race_date


class TestWeekStart:
    def test_tuesday_maps_to_itself(self):
        assert iracing_week_start(date(2026, 7, 14)) == date(2026, 7, 14)  # a Tuesday

    def test_monday_maps_to_previous_tuesday(self):
        assert iracing_week_start(date(2026, 7, 13)) == date(2026, 7, 7)

    def test_wednesday_maps_back_one_day(self):
        assert iracing_week_start(date(2026, 7, 15)) == date(2026, 7, 14)


class TestParseRaceDate:
    def test_iso_with_z(self):
        assert parse_race_date("2026-07-12T18:04:00Z", "") == date(2026, 7, 12)

    def test_empty_falls_back_to_created_at(self):
        assert parse_race_date("", "2026-07-13T09:00:00+00:00") == date(2026, 7, 13)

    def test_both_unparseable_returns_none(self):
        assert parse_race_date("", "garbage") is None

    def test_garbage_session_date_falls_back_to_created_at(self):
        assert parse_race_date("garbage", "2026-07-13T09:00:00+00:00") == date(2026, 7, 13)


class TestBuildStreak:
    # today = Fri 2026-07-17; current week starts Tue 2026-07-14
    TODAY = date(2026, 7, 17)

    def test_empty_is_zeroes(self):
        s = build_streak([], self.TODAY)
        assert s == StreakSummary(races_this_week=0, streak_weeks=0, total_races=0)

    def test_current_and_previous_week_streak_of_two(self):
        races = [
            ("2026-07-16T01:00:00Z", ""),   # this week
            ("2026-07-08T01:00:00Z", ""),   # last week (Tue 7/7 window)
        ]
        s = build_streak(races, self.TODAY)
        assert s.races_this_week == 1
        assert s.streak_weeks == 2
        assert s.total_races == 2

    def test_empty_current_week_does_not_break_streak(self):
        races = [("2026-07-08T01:00:00Z", ""), ("2026-07-01T01:00:00Z", "")]
        s = build_streak(races, self.TODAY)
        assert s.races_this_week == 0
        assert s.streak_weeks == 2  # counted from last week backward

    def test_gap_week_breaks_streak(self):
        races = [("2026-07-16T01:00:00Z", ""), ("2026-07-01T01:00:00Z", "")]
        s = build_streak(races, self.TODAY)
        assert s.streak_weeks == 1  # 7/7 week empty -> streak is current week only

    def test_unparseable_dates_count_in_total_only(self):
        races = [("", ""), ("2026-07-16T01:00:00Z", "")]
        s = build_streak(races, self.TODAY)
        assert s.total_races == 2
        assert s.races_this_week == 1
