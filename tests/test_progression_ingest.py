# tests/test_progression_ingest.py
"""Progression ingest — rating history caching + weekly implied-iR compute."""

from datetime import date

import pytest

import core.progression.ingest as ingest
from core.benchmark.iracing_api import (
    IRatingPoint, RaceWeek, SeasonSchedule,
)
from core.briefing.curve import build_curve
from core.progression.ingest import (
    compute_week_implied_ir, fetch_rating_history, normalize_sr,
)
from core.track.track_db import LapRow, SessionRow


class _FakeChartAPI:
    def __init__(self, points_by_type, fail=False):
        self.points_by_type = points_by_type
        self.fail = fail
        self.calls = []

    def get_member_chart_data(self, cust_id, category_id=5, chart_type=1):
        if self.fail:
            raise RuntimeError("network down")
        self.calls.append(chart_type)
        return self.points_by_type.get(chart_type, [])


class TestFetchRatingHistory:
    def test_fetches_both_series_and_caches(self, tmp_path):
        api = _FakeChartAPI({
            1: [IRatingPoint("2026-07-01", 1350)],
            3: [IRatingPoint("2026-07-01", 351)],
        })
        ir, sr = fetch_rating_history(api, 123, cache_dir=tmp_path,
                                      today=date(2026, 7, 17))
        assert ir == [IRatingPoint("2026-07-01", 1350)]
        assert sr == [IRatingPoint("2026-07-01", 351)]
        # second call same day: served from cache, API not touched
        dead = _FakeChartAPI({}, fail=True)
        ir2, sr2 = fetch_rating_history(dead, 123, cache_dir=tmp_path,
                                        today=date(2026, 7, 17))
        assert ir2 == ir and sr2 == sr

    def test_api_failure_degrades_to_empty(self, tmp_path):
        dead = _FakeChartAPI({}, fail=True)
        ir, sr = fetch_rating_history(dead, 123, cache_dir=tmp_path,
                                      today=date(2026, 7, 17))
        assert ir == [] and sr == []


class TestNormalizeSr:
    def test_scaled_values_divided(self):
        pts = [IRatingPoint("2026-07-01", 351)]
        assert normalize_sr(pts) == [("2026-07-01", 3.51)]

    def test_small_values_untouched(self):
        pts = [IRatingPoint("2026-07-01", 3)]
        assert normalize_sr(pts) == [("2026-07-01", 3.0)]

    def test_empty(self):
        assert normalize_sr([]) == []


def _season(season_id, track_id, week=5):
    return SeasonSchedule(
        series_id=season_id, series_name=f"Series {season_id}",
        season_id=season_id, season_name="S3", race_week=week, max_weeks=12,
        season_year=2026, season_quarter=3,
        weeks=[RaceWeek(
            race_week_num=week, track_id=track_id, track_name=f"Track {track_id}",
            config_name="", start_date="2026-07-14", race_time_limit=None,
            race_lap_limit=None, start_type="Standing", standing_start=True,
            max_pct_fuel_fill=None,
        )],
    )


def _practice(sid, track_id, car, best=160.0):
    return SessionRow(
        session_id=sid, track_id=track_id, track_name=f"Track {track_id}",
        car=car, session_type="Practice",
        session_date=f"2026-07-0{sid[-1]} 10-00-00",
        best_lap_time=best, lap_count=12,
    )


def _laps(n=12, base=160.0):
    return [LapRow(lap_number=i + 1, lap_time=base + 0.1 * i, is_valid=True)
            for i in range(n)]


def _dense_curve():
    pts = [(1000 + 50 * i, 165.0 - 0.5 * i) for i in range(20)]
    return build_curve(pts, subsessions_used=10, capped=False)


class TestComputeWeekImpliedIr:
    def _fixtures(self):
        seasons = [_season(100, 525)]
        sessions = [_practice("s1", "525", "M2"), _practice("s2", "525", "M2")]
        laps = {s.session_id: _laps() for s in sessions}
        return seasons, sessions, laps

    def test_places_combo_on_harvested_curve(self, monkeypatch, tmp_path):
        seasons, sessions, laps = self._fixtures()
        monkeypatch.setattr(ingest, "harvest_field",
                            lambda *a, **k: (_dense_curve(), None))
        rows, warnings = compute_week_implied_ir(
            None, seasons, sessions, laps, cache_dir=tmp_path)
        assert len(rows) == 1
        r = rows[0]
        assert (r.track_id, r.car) == ("525", "M2")
        assert r.series_name == "Series 100"
        assert r.implied_lo is not None and r.implied_hi > r.implied_lo
        assert r.weight > 0

    def test_thin_curve_skipped_with_warning(self, monkeypatch, tmp_path):
        seasons, sessions, laps = self._fixtures()
        thin = build_curve([(1500, 160.0)], subsessions_used=1, capped=False)
        monkeypatch.setattr(ingest, "harvest_field", lambda *a, **k: (thin, None))
        rows, warnings = compute_week_implied_ir(
            None, seasons, sessions, laps, cache_dir=tmp_path)
        assert rows == []
        assert warnings

    def test_harvest_failure_is_a_warning_not_a_raise(self, monkeypatch, tmp_path):
        seasons, sessions, laps = self._fixtures()

        def boom(*a, **k):
            raise RuntimeError("API down")

        monkeypatch.setattr(ingest, "harvest_field", boom)
        rows, warnings = compute_week_implied_ir(
            None, seasons, sessions, laps, cache_dir=tmp_path)
        assert rows == [] and warnings

    def test_combo_deduped_across_series(self, monkeypatch, tmp_path):
        seasons = [_season(100, 525), _season(200, 525)]
        sessions = [_practice("s1", "525", "M2"), _practice("s2", "525", "M2")]
        laps = {s.session_id: _laps() for s in sessions}
        monkeypatch.setattr(ingest, "harvest_field",
                            lambda *a, **k: (_dense_curve(), None))
        rows, _ = compute_week_implied_ir(
            None, seasons, sessions, laps, cache_dir=tmp_path)
        assert len(rows) == 1  # same (track, car) placed once

    def test_no_practice_at_week_tracks_yields_nothing(self, monkeypatch, tmp_path):
        seasons = [_season(100, 219)]  # Bathurst — user practiced Spa only
        sessions = [_practice("s1", "525", "M2")]
        laps = {"s1": _laps()}
        monkeypatch.setattr(ingest, "harvest_field",
                            lambda *a, **k: (_dense_curve(), None))
        rows, _ = compute_week_implied_ir(
            None, seasons, sessions, laps, cache_dir=tmp_path)
        assert rows == []
