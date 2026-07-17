"""PURE technique-tendency engine over persisted diagnosis rows.

The coupling test is the contract: the adapter must classify a stored
row EXACTLY as the live coach classifies the equivalent RegionDiagnosis —
thresholds are imported from nudges, never re-implemented.
"""

from core.coaching.debrief import RegionDiagnosis
from core.live.nudges import (
    BRAKING_THRESHOLD_M,
    MIN_SPEED_THRESHOLD_MS,
    RELEASE_THRESHOLD_M,
    FaultKind,
    fault_kinds_from_diagnosis,
)
from core.profile.models import TECHNIQUE_MIN_SESSIONS, TechniqueTendencies
from core.profile.technique import _diagnosis_from_row, build_technique
from core.telemetry.loss_regions import LossRegion
from core.track.track_db import DiagnosisRow


def _row(session_id="s1", session_date="2026-07-01 10-00-00", track_id="523",
         car="M2", label="Eau Rouge", time_lost=0.5, braking=None,
         min_speed=0.0, throttle=None, release=None, exit_speed=0.0):
    return DiagnosisRow(
        session_id=session_id, track_id=track_id, track_name="Spa", car=car,
        session_type="practice", session_date=session_date,
        region_rank=1, label=label, distance_start_m=100.0,
        distance_end_m=250.0, time_lost_s=time_lost,
        braking_delta_m=braking, min_speed_delta_ms=min_speed,
        throttle_delta_m=throttle, brake_release_delta_m=release,
        exit_speed_delta_ms=exit_speed, driver_min_speed_ms=30.0,
        reference_min_speed_ms=32.0, driver_lap_number=3,
        driver_lap_time=150.0, reference_source="personal_best",
        reference_lap_time=148.0, total_time_delta_s=2.0,
    )


def test_adapter_matches_live_fault_ladder():
    """Same values through the adapter and through a hand-built
    RegionDiagnosis must classify identically."""
    row = _row(braking=BRAKING_THRESHOLD_M,
               min_speed=-MIN_SPEED_THRESHOLD_MS,
               release=-RELEASE_THRESHOLD_M)
    direct = RegionDiagnosis(
        region=LossRegion(100.0, 250.0, 0.5),
        label="Eau Rouge",
        braking_delta_m=BRAKING_THRESHOLD_M,
        min_speed_delta_ms=-MIN_SPEED_THRESHOLD_MS,
        throttle_delta_m=None,
        driver_min_speed_ms=30.0,
        reference_min_speed_ms=32.0,
        brake_release_delta_m=-RELEASE_THRESHOLD_M,
        exit_speed_delta_ms=0.0,
    )
    assert (fault_kinds_from_diagnosis(_diagnosis_from_row(row))
            == fault_kinds_from_diagnosis(direct))
    assert FaultKind.LIFT in fault_kinds_from_diagnosis(_diagnosis_from_row(row))


def test_empty_rows_gives_empty_tendencies():
    t = build_technique([])
    assert t == TechniqueTendencies()
    assert not t.enough_data


def test_dominant_fault_and_aggregates():
    rows = [
        _row(session_id=f"s{i}", session_date=f"2026-07-{i:02d} 10-00-00",
             car="M2" if i % 2 else "992", release=-RELEASE_THRESHOLD_M,
             time_lost=0.4)
        for i in range(1, 7)
    ]
    t = build_technique(rows)
    assert t.sessions_diagnosed == 6
    assert t.enough_data  # >= TECHNIQUE_MIN_SESSIONS (5)
    assert t.dominant == "release"
    f = t.faults[0]
    assert f.occurrences == 6
    assert f.combos == 2
    assert abs(f.mean_time_lost_s - 0.4) < 1e-9


def test_trend_requires_both_pools():
    # 5 sessions = all inside the recent window -> earlier pool empty -> None
    rows = [
        _row(session_id=f"s{i}", session_date=f"2026-07-{i:02d} 10-00-00",
             release=-RELEASE_THRESHOLD_M)
        for i in range(1, 6)
    ]
    assert build_technique(rows).faults[0].trend_time_lost_s is None
    # 7 sessions with shrinking losses -> negative trend
    rows = [
        _row(session_id=f"s{i}", session_date=f"2026-07-{i:02d} 10-00-00",
             release=-RELEASE_THRESHOLD_M,
             time_lost=1.0 if i <= 2 else 0.3)
        for i in range(1, 8)
    ]
    trend = build_technique(rows).faults[0].trend_time_lost_s
    assert trend is not None and trend < 0


def test_recurring_corners_exclude_position_fallback():
    rows = [
        _row(session_id="s1", label="Bruxelles", release=-RELEASE_THRESHOLD_M),
        _row(session_id="s2", label="Bruxelles", release=-RELEASE_THRESHOLD_M),
        _row(session_id="s3", label="~4.4 km from start/finish",
             release=-RELEASE_THRESHOLD_M),
        _row(session_id="s4", label="~4.4 km from start/finish",
             release=-RELEASE_THRESHOLD_M),
    ]
    t = build_technique(rows)
    assert ("Bruxelles", 2) in t.recurring_corners
    assert all(not label.startswith("~") for label, _ in t.recurring_corners)


def test_below_session_threshold_not_enough_data():
    rows = [
        _row(session_id=f"s{i}", session_date=f"2026-07-{i:02d} 10-00-00",
             release=-RELEASE_THRESHOLD_M)
        for i in range(1, TECHNIQUE_MIN_SESSIONS)
    ]
    t = build_technique(rows)
    assert not t.enough_data
    assert t.sessions_diagnosed == TECHNIQUE_MIN_SESSIONS - 1
