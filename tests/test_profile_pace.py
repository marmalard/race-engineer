"""Tests for the pure per-combo readiness engine (synthetic history)."""

from core.profile.pace import build_readiness
from core.track.track_db import LapRow, SessionRow


def _sess(sid, date, best=100.0, track="525", name="Spa", car="M2",
          stype="practice"):
    return SessionRow(session_id=sid, track_id=track, track_name=name,
                      car=car, session_type=stype, session_date=date,
                      best_lap_time=best, lap_count=0)


def _laps(times, valid=True):
    return [LapRow(lap_number=i + 1, lap_time=t, is_valid=valid)
            for i, t in enumerate(times)]


def test_grouping_and_thresholds():
    sessions = [
        _sess("a", "2026-07-01", best=101.0),
        _sess("b", "2026-07-02", best=100.0),
        _sess("c", "2026-07-03", best=99.5, track="219", name="Bathurst"),
    ]
    laps = {
        "a": _laps([101.0, 101.5, 102.0, 101.2, 101.1]),
        "b": _laps([100.0, 100.4, 100.2, 100.6, 100.3]),
        "c": _laps([99.5, 99.9]),
    }
    combos = build_readiness(sessions, laps)
    assert len(combos) == 2
    spa = next(c for c in combos if c.track_id == "525")
    assert spa.sessions == 2 and spa.valid_laps == 10
    assert spa.enough_data                      # exactly at both thresholds
    assert spa.best_lap == 100.0
    assert spa.pb_trend_s == 1.0                # 101.0 -> 100.0
    assert spa.last_driven == "2026-07-02"
    assert spa.track_name == "Spa" and spa.car == "M2"
    bathurst = next(c for c in combos if c.track_id == "219")
    assert not bathurst.enough_data             # 1 session, 2 laps


def test_race_sessions_excluded():
    sessions = [
        _sess("a", "2026-07-01"),
        _sess("r", "2026-07-02", stype="Race"),
    ]
    laps = {"a": _laps([100.0] * 10), "r": _laps([99.0] * 10)}
    combos = build_readiness(sessions, laps)
    assert combos[0].sessions == 1
    assert combos[0].valid_laps == 10
    assert combos[0].best_lap == 100.0          # race best ignored
    assert combos[0].last_driven == "2026-07-01"


def test_invalid_laps_dont_count():
    sessions = [_sess("a", "2026-07-01"), _sess("b", "2026-07-02")]
    laps = {
        "a": _laps([100.0] * 5) + _laps([130.0] * 5, valid=False),
        "b": _laps([100.0] * 4),
    }
    combos = build_readiness(sessions, laps)
    assert combos[0].valid_laps == 9
    assert not combos[0].enough_data            # 9 < 10


def test_sessions_without_best_count_laps_but_not_sessions():
    sessions = [
        _sess("a", "2026-07-01"),
        _sess("stub", "2026-07-02", best=None),
        _sess("b", "2026-07-03"),
    ]
    laps = {"a": _laps([100.0] * 5), "stub": [], "b": _laps([100.0] * 5)}
    combos = build_readiness(sessions, laps)
    assert combos[0].sessions == 2              # stub excluded from session count
    assert combos[0].valid_laps == 10


def test_pb_trend_none_with_single_best_session():
    sessions = [_sess("a", "2026-07-01"), _sess("stub", "2026-07-02", best=None)]
    laps = {"a": _laps([100.0] * 5), "stub": _laps([100.0] * 5)}
    combos = build_readiness(sessions, laps)
    assert combos[0].pb_trend_s is None


def test_consistency_uses_recent_window():
    # 4 sessions; first wild, last 3 tight -> consistency from last 3 only
    sessions = [_sess(s, f"2026-07-0{i+1}")
                for i, s in enumerate(["a", "b", "c", "d"])]
    laps = {
        "a": _laps([100.0, 108.0, 95.0, 103.0, 99.0]),
        "b": _laps([100.0, 100.2]),
        "c": _laps([100.1, 100.3]),
        "d": _laps([100.0, 100.2]),
    }
    combos = build_readiness(sessions, laps)
    c = combos[0]
    assert c.consistency_s is not None
    assert c.consistency_s < 0.5                # wild session excluded


def test_consistency_none_below_min_laps():
    sessions = [_sess("a", "2026-07-01"), _sess("b", "2026-07-02")]
    laps = {"a": _laps([100.0, 100.1]), "b": _laps([100.2, 100.0])}
    combos = build_readiness(sessions, laps)
    assert combos[0].consistency_s is None      # 4 < CONSISTENCY_MIN_LAPS


def test_outlier_laps_excluded_from_count_and_consistency():
    """Out-laps/crawl laps (telemetry-valid but > 110% of best) don't count."""
    sessions = [_sess("a", "2026-07-01"), _sess("b", "2026-07-02")]
    laps = {
        "a": _laps([100.0, 101.0, 250.0, 240.0, 100.5]),   # 2 crawl laps
        "b": _laps([100.2, 100.4, 300.0, 100.1, 100.3]),   # 1 crawl lap
    }
    combos = build_readiness(sessions, laps)
    c = combos[0]
    assert c.valid_laps == 7                    # 10 valid - 3 outliers
    assert c.consistency_s is not None
    assert c.consistency_s < 1.0                # crawl laps out of the stdev


def test_sorted_by_valid_laps_desc():
    sessions = [
        _sess("a", "2026-07-01"),
        _sess("b", "2026-07-02", track="219", name="Bathurst"),
    ]
    laps = {"a": _laps([100.0] * 3), "b": _laps([99.0] * 8)}
    combos = build_readiness(sessions, laps)
    assert [c.track_id for c in combos] == ["219", "525"]
