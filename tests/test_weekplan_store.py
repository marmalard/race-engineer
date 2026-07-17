# tests/test_weekplan_store.py
"""week_plans persistence — refresh-not-rebirth and tolerant reload."""

import json

import pytest

from core.progression.store import ImpliedIRStore
from core.weekplan.models import PlanSlot, PracticeHalf, RaceHalf, WeekPlan
from core.weekplan.store import WeekPlanStore


def _plan(week="2026-07-21", created="2026-07-19T09:00:00+00:00",
          updated="2026-07-19T09:00:00+00:00"):
    return WeekPlan(
        week_start=week, created_at=created, updated_at=updated,
        race=RaceHalf(
            series_name="PCup", season_id=100, race_week=5,
            track_id="525", track_name="Spa", config_name="GP",
            car="992", slots=[PlanSlot("2026-07-21T20:00:00+00:00", True)],
        ),
        practice=PracticeHalf(kind="race_combo", combo="Spa in the 992"),
    )


@pytest.fixture
def store(tmp_path):
    return WeekPlanStore(tmp_path / "progression.db")


class TestWeekPlanStore:
    def test_round_trip(self, store):
        store.save(_plan())
        out = store.get("2026-07-21")
        assert out is not None
        assert out.race.series_name == "PCup"
        assert out.race.slots[0].fits_window is True
        assert out.practice.kind == "race_combo"

    def test_missing_week_none(self, store):
        assert store.get("2026-01-06") is None

    def test_resave_preserves_created_at(self, store):
        store.save(_plan())
        store.save(_plan(created="2026-07-20T10:00:00+00:00",
                         updated="2026-07-20T10:00:00+00:00"))
        out = store.get("2026-07-21")
        assert out.created_at == "2026-07-19T09:00:00+00:00"
        assert out.updated_at == "2026-07-20T10:00:00+00:00"

    def test_latest_and_history_ordering(self, store):
        store.save(_plan(week="2026-07-14"))
        store.save(_plan(week="2026-07-21"))
        assert store.latest().week_start == "2026-07-21"
        assert [p.week_start for p in store.history()] == [
            "2026-07-21", "2026-07-14"]

    def test_stale_json_with_unknown_and_missing_fields_loads(
            self, store, tmp_path):
        store.save(_plan())
        # simulate an OLD stored plan: unknown key + missing 'sr'
        raw = {
            "week_start": "2026-07-07", "created_at": "x",
            "updated_at": "x", "race": None, "practice": None,
            "curve_filled": False, "warnings": [],
            "some_future_field": 42,
        }
        with store._conn() as conn:
            conn.execute(
                "INSERT INTO week_plans VALUES (?, ?, ?, ?)",
                ("2026-07-07", json.dumps(raw), "x", "x"),
            )
        out = store.get("2026-07-07")
        assert out is not None and out.sr is None

    def test_coexists_with_implied_ir_store_same_file(self, tmp_path):
        db = tmp_path / "progression.db"
        ImpliedIRStore(db)          # creates its table first
        WeekPlanStore(db).save(_plan())
        assert WeekPlanStore(db).get("2026-07-21") is not None
