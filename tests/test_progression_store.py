"""implied_ir_history persistence -- weekly snapshots survive cache expiry."""

import pytest

from core.progression.models import ComboImplied
from core.progression.store import ImpliedIRStore


def _combo(car="M2", lo=1400, hi=1650, weight=30.0):
    return ComboImplied(
        track_id="525", track_name="Spa", car=car, series_name="PCup",
        lap_s=160.5, implied_lo=lo, implied_hi=hi, weight=weight,
    )


@pytest.fixture
def store(tmp_path):
    return ImpliedIRStore(tmp_path / "progression.db")


class TestImpliedIRStore:
    def test_round_trip(self, store):
        store.save_week("2026-07-14", [_combo(), _combo(car="F4", lo=1200, hi=1450)])
        rows = store.get_week("2026-07-14")
        assert len(rows) == 2
        assert rows[0].track_name == "Spa"
        assert rows[0].lap_s == 160.5

    def test_missing_week_empty(self, store):
        assert store.get_week("2026-01-06") == []

    def test_save_week_is_idempotent_overwrite(self, store):
        store.save_week("2026-07-14", [_combo(), _combo(car="F4")])
        store.save_week("2026-07-14", [_combo()])
        assert len(store.get_week("2026-07-14")) == 1

    def test_empty_list_clears_week(self, store):
        store.save_week("2026-07-14", [_combo()])
        store.save_week("2026-07-14", [])
        assert store.get_week("2026-07-14") == []

    def test_history_ascending_by_week(self, store):
        store.save_week("2026-07-14", [_combo()])
        store.save_week("2026-07-07", [_combo(lo=1300, hi=1550)])
        weeks = [w for w, _ in store.history()]
        assert weeks == ["2026-07-07", "2026-07-14"]

    def test_latest_week(self, store):
        assert store.latest_week() is None
        store.save_week("2026-07-07", [_combo()])
        store.save_week("2026-07-14", [_combo(car="F4")])
        week, rows = store.latest_week()
        assert week == "2026-07-14"
        assert rows[0].car == "F4"
