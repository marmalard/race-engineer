"""Pure trend-series builders for the Progression page."""

from core.benchmark.reference_store import ReferenceLapMeta
from core.live.nudges import fault_kinds_from_diagnosis
from core.profile.technique import _diagnosis_from_row
from core.progression.trends import combo_pace_series, fault_trend_series, pb_timeline
from core.track.track_db import DiagnosisRow, SessionRow


def _session(sid, track_id, car, stype, sdate, best):
    return SessionRow(
        session_id=sid, track_id=track_id, track_name=f"Track {track_id}",
        car=car, session_type=stype, session_date=sdate,
        best_lap_time=best, lap_count=10,
    )


def _diag_row(sid, sdate, label="Turn 1", braking=-15.0, time_lost=0.8):
    """A row whose braking delta is far past the live nudge threshold."""
    return DiagnosisRow(
        session_id=sid, track_id="525", track_name="Spa", car="M2",
        session_type="Practice", session_date=sdate, region_rank=1,
        label=label, distance_start_m=100.0, distance_end_m=300.0,
        time_lost_s=time_lost, braking_delta_m=braking,
        min_speed_delta_ms=0.0, throttle_delta_m=None,
        brake_release_delta_m=None, exit_speed_delta_ms=0.0,
        driver_min_speed_ms=40.0, reference_min_speed_ms=40.0,
        driver_lap_number=3, driver_lap_time=160.0,
        reference_source="personal_best", reference_lap_time=158.0,
        total_time_delta_s=2.0,
    )


class TestComboPaceSeries:
    def test_groups_by_combo_sorted_by_date(self):
        sessions = [
            _session("b", "525", "M2", "Practice", "2026-07-02 10-00-00", 160.0),
            _session("a", "525", "M2", "Practice", "2026-07-01 10-00-00", 161.5),
            _session("c", "18", "F4", "Practice", "2026-07-03 10-00-00", 130.0),
        ]
        series = combo_pace_series(sessions)
        assert series[("525", "M2")] == [
            ("2026-07-01 10-00-00", 161.5), ("2026-07-02 10-00-00", 160.0)]
        assert series[("18", "F4")] == [("2026-07-03 10-00-00", 130.0)]

    def test_race_sessions_and_missing_best_excluded(self):
        sessions = [
            _session("r", "525", "M2", "Race", "2026-07-01 10-00-00", 159.0),
            _session("n", "525", "M2", "Practice", "2026-07-02 10-00-00", None),
        ]
        assert combo_pace_series(sessions) == {}


class TestFaultTrendSeries:
    def test_classification_matches_live_ladder(self):
        """COUPLING: the series must contain exactly the kinds the live
        fault ladder produces for the same row — no re-implementation."""
        row = _diag_row("s1", "2026-07-01 10-00-00")
        expected = {k.value for k in fault_kinds_from_diagnosis(_diagnosis_from_row(row))}
        series = fault_trend_series([row])
        assert set(series.keys()) == expected
        assert "braking" in series  # sanity: -15m is far past any brake threshold

    def test_per_session_time_lost_summed_and_date_sorted(self):
        rows = [
            _diag_row("s2", "2026-07-02 10-00-00", time_lost=0.5),
            _diag_row("s1", "2026-07-01 10-00-00", time_lost=0.8),
            _diag_row("s1", "2026-07-01 10-00-00", label="Turn 5", time_lost=0.3),
        ]
        series = fault_trend_series(rows)
        assert series["braking"] == [
            ("2026-07-01 10-00-00", 1.1), ("2026-07-02 10-00-00", 0.5)]

    def test_empty_rows_empty_series(self):
        assert fault_trend_series([]) == {}


class TestPbTimeline:
    def test_personal_best_only_sorted_by_imported_at(self):
        metas = [
            ReferenceLapMeta(1, "525", "M2", "g61", 159.1, "Borsuk", "2026-06-01T00:00:00"),
            ReferenceLapMeta(2, "525", "M2", "personal_best", 161.3, None, "2026-07-02T00:00:00"),
            ReferenceLapMeta(3, "18", "F4", "personal_best", 130.2, None, "2026-07-01T00:00:00"),
        ]
        out = pb_timeline(metas)
        assert [m.ref_id for m in out] == [3, 2]
