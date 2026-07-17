"""Exact-string pins for the week-plan markdown — the verdict wording
IS the product contract (and the no-gating guarantee)."""

from core.weekplan.models import (
    PlanSlot, PracticeHalf, RaceHalf, SRCheck, WeekPlan,
)
from core.weekplan.render import headline, render_week_plan


def _race(**kw):
    base = dict(
        series_name="PCup", season_id=100, race_week=5, track_id="525",
        track_name="Spa", config_name="Grand Prix", car="Porsche 992 Cup",
        slots=[], race_time_limit=25, race_lap_limit=None,
        standing_start=True, prep_sessions=4, prep_best_lap_s=139.2,
    )
    base.update(kw)
    return RaceHalf(**base)


def _plan(**kw):
    base = dict(week_start="2026-07-21", created_at="x", updated_at="x")
    base.update(kw)
    return WeekPlan(**base)


class TestHeadline:
    def test_with_race(self):
        p = _plan(race=_race())
        assert headline(p) == (
            "Your week plan is ready — PCup at Spa."
        )

    def test_without_race(self):
        p = _plan()
        assert headline(p) == (
            "Your week plan is ready — no race pick this week, but the "
            "practice half has a job for you."
        )


class TestRaceSection:
    def test_filled_curve_verdict_line(self):
        p = _plan(race=_race(implied_ir_lo=1400, implied_ir_hi=1650),
                  curve_filled=True)
        out = render_week_plan(p)
        assert (
            "Your practice best (2:19.200) is running like a "
            "1,400–1,650 iR driver in this field." in out
        )

    def test_unfilled_curve_pending_line(self):
        p = _plan(race=_race(), curve_filled=False)
        assert (
            "The field curve builds after Tuesday night — I'll fill "
            "this in." in render_week_plan(p)
        )

    def test_filled_but_no_prep_best(self):
        p = _plan(race=_race(prep_best_lap_s=None), curve_filled=True)
        assert (
            "No practice best at this combo yet — run a few laps and "
            "the verdict fills in." in render_week_plan(p)
        )

    def test_time_limited_format_line(self):
        p = _plan(race=_race())
        assert "The race costs about 25 minutes." in render_week_plan(p)


class TestSrSection:
    def test_comfortable(self):
        p = _plan(sr=SRCheck("Class C", 3.10, comfortable=True))
        assert (
            "SR check: Class C 3.10 — even a bad night keeps you above "
            "the line." in render_week_plan(p)
        )

    def test_near_the_line_still_races(self):
        p = _plan(sr=SRCheck("Class C", 2.10, comfortable=False))
        assert (
            "SR check: Class C 2.10 — this is the low-stakes week to "
            "bank SR. Race anyway, pick the calm slot."
            in render_week_plan(p)
        )


class TestPracticeSection:
    def test_prescription(self):
        p = _plan(practice=PracticeHalf(
            kind="prescription", combo="Porsche 992 Cup at Spa",
            fault="release", skill_line="teaches trail-brake bite",
            transfer_line="it transfers everywhere",
        ))
        assert (
            "Spend 20 minutes in the Porsche 992 Cup at Spa — it "
            "teaches trail-brake bite. It transfers everywhere."
            in render_week_plan(p)
        )

    def test_race_combo_with_goal(self):
        p = _plan(practice=PracticeHalf(
            kind="race_combo", combo="Spa in the M2",
            goal_label="Eau Rouge", goal_fault="Brake point",
            goal_time_lost_s=0.8,
        ))
        assert (
            "Spend 20 minutes at Spa in the M2 — the last debrief puts "
            "the time at Eau Rouge (Brake point, 0.8s)."
            in render_week_plan(p)
        )

    def test_race_combo_no_goal(self):
        p = _plan(practice=PracticeHalf(kind="race_combo",
                                        combo="Spa in the M2"))
        assert (
            "Spend 20 minutes at Spa in the M2 — bank laps, the "
            "diagnoses will follow." in render_week_plan(p)
        )

    def test_ttp_line_rendered(self):
        p = _plan(practice=PracticeHalf(
            kind="race_combo", combo="Spa in the M2",
            ttp_line="You need ~6 laps to reach pace — races give you "
                     "zero. Arrive early."))
        assert "You need ~6 laps to reach pace" in render_week_plan(p)


class TestNeverGates:
    def test_no_gating_sentences_anywhere(self):
        p = _plan(race=_race(), sr=SRCheck("Class C", 1.5, False),
                  practice=PracticeHalf(kind="race_combo", combo="x"))
        out = render_week_plan(p).lower()
        assert "not ready" not in out
        assert "don't race" not in out
        assert "do not race" not in out
