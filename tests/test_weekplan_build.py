# tests/test_weekplan_build.py
"""Week-plan target-week math and generate/refresh decisions."""

from datetime import date, datetime, timedelta, timezone

import core.weekplan.build as wp_build
from core.benchmark.iracing_api import RaceWeek, SeasonSchedule
from core.briefing.curve import build_curve
from core.profile.models import TechniqueTendencies, TimeToPace
from core.track.track_db import DiagnosisRow, LapRow, SessionRow
from core.weekplan.build import (
    build_week_plan, should_generate, should_refresh, sports_car_license,
    target_week_start, week_delta,
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


# ---------------------------------------------------------------------------
# Task 3: build_week_plan
# ---------------------------------------------------------------------------

def _season(season_id=100, track_id=525, week=5, name="PCup"):
    return SeasonSchedule(
        series_id=season_id, series_name=name, season_id=season_id,
        season_name="S3", race_week=week, max_weeks=12,
        season_year=2026, season_quarter=3,
        weeks=[RaceWeek(
            race_week_num=week, track_id=track_id, track_name="Spa",
            config_name="Grand Prix", start_date="2026-07-14",
            race_time_limit=25, race_lap_limit=None, start_type="Standing",
            standing_start=True, max_pct_fuel_fill=None,
            race_time_descriptors=[],
        )],
    )


def _practice(sid, track_id="525", car="M2", best=160.0):
    return SessionRow(
        session_id=sid, track_id=track_id, track_name="Spa", car=car,
        session_type="Practice", session_date=f"2026-07-0{sid[-1]} 19-00-00",
        best_lap_time=best, lap_count=12,
    )


def _laps(n=12):
    return [LapRow(lap_number=i + 1, lap_time=160.0 + 0.1 * i, is_valid=True)
            for i in range(n)]


def _diag(sid="s1", label="Eau Rouge", braking=-15.0):
    return DiagnosisRow(
        session_id=sid, track_id="525", track_name="Spa", car="M2",
        session_type="Practice", session_date="2026-07-01 19-00-00",
        region_rank=1, label=label, distance_start_m=100.0,
        distance_end_m=300.0, time_lost_s=0.8, braking_delta_m=braking,
        min_speed_delta_ms=0.0, throttle_delta_m=None,
        brake_release_delta_m=None, exit_speed_delta_ms=0.0,
        driver_min_speed_ms=40.0, reference_min_speed_ms=40.0,
        driver_lap_number=3, driver_lap_time=160.0,
        reference_source="personal_best", reference_lap_time=158.0,
        total_time_delta_s=2.0,
    )


NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)  # Wednesday
TODAY = date(2026, 7, 15)


def _dense_curve():
    pts = [(1000 + 50 * i, 165.0 - 0.5 * i) for i in range(20)]
    return build_curve(pts, subsessions_used=10, capped=False)


class TestSportsCarLicense:
    def test_list_shape(self):
        info = {"licenses": [{"category": "sports_car",
                              "group_name": "Class C",
                              "safety_rating": 3.1}]}
        assert sports_car_license(info) == ("Class C", 3.1)

    def test_dict_shape(self):
        info = {"licenses": {"sports_car": {
            "category_id": 5, "group_name": "Class B",
            "safety_rating": 2.2}}}
        assert sports_car_license(info) == ("Class B", 2.2)

    def test_missing_returns_none(self):
        assert sports_car_license({}) is None


class TestBuildWeekPlan:
    def _inputs(self):
        sessions = [_practice("s1"), _practice("s2")]
        laps = {s.session_id: _laps() for s in sessions}
        return [_season()], sessions, laps

    def test_full_plan_midweek_with_field_data(self, monkeypatch, tmp_path):
        seasons, sessions, laps = self._inputs()
        monkeypatch.setattr(wp_build, "harvest_field",
                            lambda *a, **k: (_dense_curve(), None))

        class _Api:
            def get_member_info(self):
                return {"licenses": [{"category": "sports_car",
                                      "group_name": "Class C",
                                      "safety_rating": 3.1}]}

        plan = build_week_plan(_Api(), seasons, sessions, laps, [],
                               TechniqueTendencies(), TimeToPace(),
                               NOW, TODAY, cache_dir=tmp_path)
        assert plan.week_start == "2026-07-14"
        assert plan.race is not None
        assert plan.race.car == "M2"
        assert plan.curve_filled is True
        assert plan.race.implied_ir_lo is not None
        assert plan.sr is not None and plan.sr.comfortable is True
        assert plan.practice is not None

    def test_empty_field_pre_flip_is_unfilled_not_warned(self, monkeypatch,
                                                         tmp_path):
        seasons, sessions, laps = self._inputs()
        empty = build_curve([], subsessions_used=0, capped=False)
        monkeypatch.setattr(wp_build, "harvest_field",
                            lambda *a, **k: (empty, None))

        class _Api:
            def get_member_info(self):
                return {}

        plan = build_week_plan(_Api(), seasons, sessions, laps, [],
                               TechniqueTendencies(), TimeToPace(),
                               NOW, TODAY, cache_dir=tmp_path)
        assert plan.race is not None
        assert plan.curve_filled is False
        assert not any("harvest" in w.lower() for w in plan.warnings)

    def test_no_candidates_yields_warning_not_crash(self, tmp_path):
        plan = build_week_plan(None, [], [], {}, [],
                               TechniqueTendencies(), TimeToPace(),
                               NOW, TODAY, cache_dir=tmp_path)
        assert plan.race is None
        assert plan.warnings  # the no-series warning

    def test_practice_prescription_when_dominant_fault_matches(
            self, monkeypatch, tmp_path):
        seasons, sessions, laps = self._inputs()
        monkeypatch.setattr(wp_build, "harvest_field",
                            lambda *a, **k: (_dense_curve(), None))
        tech = TechniqueTendencies(dominant="release", enough_data=True,
                                   sessions_diagnosed=6)

        class _Api:
            def get_member_info(self):
                return {}

        plan = build_week_plan(_Api(), seasons, sessions, laps, [],
                               tech, TimeToPace(), NOW, TODAY,
                               cache_dir=tmp_path)
        assert plan.practice.kind == "prescription"
        assert plan.practice.fault == "release"
        assert plan.practice.skill_line  # from the PRESCRIPTIONS row

    def test_practice_fallback_seeds_goal_from_latest_diagnosis(
            self, monkeypatch, tmp_path):
        seasons, sessions, laps = self._inputs()
        monkeypatch.setattr(wp_build, "harvest_field",
                            lambda *a, **k: (_dense_curve(), None))

        class _Api:
            def get_member_info(self):
                return {}

        plan = build_week_plan(_Api(), seasons, sessions, laps, [_diag()],
                               TechniqueTendencies(), TimeToPace(),
                               NOW, TODAY, cache_dir=tmp_path)
        assert plan.practice.kind == "race_combo"
        assert plan.practice.goal_label == "Eau Rouge"
        assert plan.practice.goal_fault == "Brake point"

    def test_practice_fault_classification_uses_live_ladder(self):
        """COUPLING: goal_fault must come from fault_kinds_from_diagnosis
        via diagnosis_from_row -- assert against a direct call."""
        from core.live.nudges import fault_kinds_from_diagnosis
        from core.profile.render import FAULT_LABELS
        from core.profile.technique import diagnosis_from_row
        row = _diag()
        kinds = fault_kinds_from_diagnosis(diagnosis_from_row(row))
        expected = FAULT_LABELS[kinds[0].value]
        half = wp_build._practice_from_fallback(None, [row], "")
        assert half.goal_fault == expected

    def test_ttp_line_present_when_enough_data(self, monkeypatch, tmp_path):
        seasons, sessions, laps = self._inputs()
        monkeypatch.setattr(wp_build, "harvest_field",
                            lambda *a, **k: (_dense_curve(), None))
        ttp = TimeToPace(median_laps=6.0, sample_sessions=38,
                         enough_data=True)

        class _Api:
            def get_member_info(self):
                return {}

        plan = build_week_plan(_Api(), seasons, sessions, laps, [],
                               TechniqueTendencies(), ttp, NOW, TODAY,
                               cache_dir=tmp_path)
        assert "~6 laps" in plan.practice.ttp_line

    def test_never_raises_even_when_everything_explodes(self, tmp_path):
        class _Bomb:
            def get_member_info(self):
                raise RuntimeError("down")

        plan = build_week_plan(_Bomb(), [], [], {}, [],
                               TechniqueTendencies(), TimeToPace(),
                               NOW, TODAY, cache_dir=tmp_path)
        assert plan.week_start  # a plan object came back regardless


class TestBuildRaceHalf:
    def test_build_race_half_slot_anchor(self, monkeypatch, tmp_path):
        """upcoming_slots receives the LATER of now_utc and midnight-UTC
        of the target week start, so Sunday builds don't list stale slots."""
        captured = {}

        def _fake_upcoming(descriptors, now_utc, count=4):
            captured["now_utc"] = now_utc
            return []

        monkeypatch.setattr(wp_build, "upcoming_slots", _fake_upcoming)

        # Sunday 2026-07-19: target = 2026-07-21 (next Tuesday).
        # Anchor must be 2026-07-21 00:00 UTC (later than now_utc).
        # week_delta=1 on Sunday: rank_series_candidates looks for
        # season.race_week + 1, so season.race_week=5 + delta=1 = week 6.
        sunday_now = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
        sunday_today = date(2026, 7, 19)
        sunday_season = SeasonSchedule(
            series_id=300, series_name="S", season_id=300,
            season_name="S3", race_week=5, max_weeks=12,
            season_year=2026, season_quarter=3,
            weeks=[RaceWeek(
                race_week_num=6, track_id=525, track_name="Spa",
                config_name="", start_date="2026-07-21",
                race_time_limit=25, race_lap_limit=None,
                start_type="Standing", standing_start=True,
                max_pct_fuel_fill=None, race_time_descriptors=[],
            )],
        )
        sessions = [_practice("s1"), _practice("s2")]
        laps = {s.session_id: _laps() for s in sessions}
        build_week_plan(None, [sunday_season], sessions, laps, [],
                        TechniqueTendencies(), TimeToPace(),
                        sunday_now, sunday_today, cache_dir=tmp_path)
        assert captured.get("now_utc") == datetime(2026, 7, 21, 0, 0,
                                                   tzinfo=timezone.utc)

        # Wednesday 2026-07-16: target = 2026-07-14 (already past).
        # Anchor must equal now_utc itself (max selects now_utc as later).
        # week_delta=0 on Wednesday: season.race_week=5 + delta=0 = week 5.
        wed_now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
        wed_today = date(2026, 7, 16)
        wed_season = SeasonSchedule(
            series_id=301, series_name="S", season_id=301,
            season_name="S3", race_week=5, max_weeks=12,
            season_year=2026, season_quarter=3,
            weeks=[RaceWeek(
                race_week_num=5, track_id=525, track_name="Spa",
                config_name="", start_date="2026-07-14",
                race_time_limit=25, race_lap_limit=None,
                start_type="Standing", standing_start=True,
                max_pct_fuel_fill=None, race_time_descriptors=[],
            )],
        )
        build_week_plan(None, [wed_season], sessions, laps, [],
                        TechniqueTendencies(), TimeToPace(),
                        wed_now, wed_today, cache_dir=tmp_path)
        assert captured.get("now_utc") == wed_now

    def test_build_race_half_skips_wrong_week(self, tmp_path):
        """A season whose week starts on the PREVIOUS week is skipped,
        leaving plan.race=None (today=2026-07-15, target=2026-07-14,
        week start_date=2026-07-07 is outside [target, target+7d))."""
        wrong_week_season = SeasonSchedule(
            series_id=200, series_name="WrongWeek", season_id=200,
            season_name="S3", race_week=5, max_weeks=12,
            season_year=2026, season_quarter=3,
            weeks=[RaceWeek(
                race_week_num=5, track_id=525, track_name="Spa",
                config_name="Grand Prix", start_date="2026-07-07",
                race_time_limit=25, race_lap_limit=None,
                start_type="Standing", standing_start=True,
                max_pct_fuel_fill=None, race_time_descriptors=[],
            )],
        )
        sessions = [_practice("s1"), _practice("s2")]
        laps = {s.session_id: _laps() for s in sessions}
        plan = build_week_plan(None, [wrong_week_season], sessions, laps, [],
                               TechniqueTendencies(), TimeToPace(),
                               NOW, TODAY, cache_dir=tmp_path)
        assert plan.race is None
        assert any(
            "Race Briefing" in w or "practiced" in w
            for w in plan.warnings
        )


class TestNoAiOnScheduledPath:
    def test_build_module_imports_no_ai(self):
        import sys
        import core.weekplan.build  # noqa: F401 -- ensure imported
        import inspect
        src = inspect.getsource(wp_build)
        assert "anthropic" not in src
        assert "Synthesizer" not in src
