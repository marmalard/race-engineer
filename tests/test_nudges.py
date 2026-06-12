"""Tests for turning a RegionDiagnosis into a terse coaching nudge."""

from core.coaching.debrief import RegionDiagnosis
from core.live.nudges import Nudge, format_lap_block, nudge_from_diagnosis
from core.telemetry.loss_regions import LossRegion


def _diag(label="Eau Rouge", time_lost=0.4, braking=None, min_speed=0.0,
          throttle=None, drv_min=60.0, ref_min=60.0) -> RegionDiagnosis:
    return RegionDiagnosis(
        region=LossRegion(distance_start=1000.0, distance_end=1100.0,
                          time_lost=time_lost),
        label=label,
        braking_delta_m=braking,
        min_speed_delta_ms=min_speed,
        throttle_delta_m=throttle,
        driver_min_speed_ms=drv_min,
        reference_min_speed_ms=ref_min,
    )


def test_lifted_at_high_speed_corner_says_carry_it_flat():
    # Over-slowing (min_speed_delta strongly negative) at a fast corner
    n = nudge_from_diagnosis(_diag(min_speed=-4.0, drv_min=55.0, ref_min=59.0))
    assert n is not None
    assert "carry it flat" in n.message.lower()
    assert n.corner == "Eau Rouge"


def test_overslow_at_slow_corner_says_carry_more_apex_speed():
    n = nudge_from_diagnosis(
        _diag(label="La Source", min_speed=-4.0, drv_min=16.0, ref_min=20.0)
    )
    assert n is not None
    assert "apex speed" in n.message.lower()


def test_braking_early_says_brake_later():
    # Negative braking delta = driver brakes earlier than reference
    n = nudge_from_diagnosis(_diag(braking=-15.0, min_speed=-0.2))
    assert n is not None
    assert "brake later" in n.message.lower()
    assert "15" in n.detail


def test_braking_late_says_brake_earlier():
    n = nudge_from_diagnosis(_diag(braking=14.0, min_speed=-0.2))
    assert n is not None
    assert "brake earlier" in n.message.lower()


def test_late_throttle_says_back_to_power_earlier():
    n = nudge_from_diagnosis(_diag(throttle=30.0, min_speed=-0.2, braking=2.0))
    assert n is not None
    assert "power earlier" in n.message.lower()


def test_below_threshold_returns_none():
    # Everything tiny → nothing worth saying
    n = nudge_from_diagnosis(_diag(braking=2.0, min_speed=-0.5, throttle=3.0))
    assert n is None


def test_min_speed_dominates_braking_when_both_present():
    # A big lift outranks a modest braking error → headline is the lift
    n = nudge_from_diagnosis(_diag(braking=-9.0, min_speed=-5.0,
                                   drv_min=54.0, ref_min=59.0))
    assert "carry it flat" in n.message.lower()


def test_format_lap_block_lists_top_n():
    diags = [
        _diag(label="Eau Rouge", time_lost=2.0, min_speed=-4.0,
              drv_min=55.0, ref_min=59.0),
        _diag(label="Les Combes", time_lost=0.2, braking=-14.0),
        _diag(label="Pouhon", time_lost=0.1, throttle=30.0),
    ]
    block = format_lap_block(lap_number=6, lap_time=143.4,
                             total_delta=1.2, diagnoses=diags, top_n=2)
    assert "Lap 6" in block
    assert "Eau Rouge" in block
    assert "Les Combes" in block
    assert "Pouhon" not in block  # capped at top_n=2


def test_format_lap_block_baseline_when_no_diagnoses():
    block = format_lap_block(lap_number=1, lap_time=142.0,
                             total_delta=0.0, diagnoses=[], top_n=2,
                             is_baseline=True)
    assert "baseline" in block.lower()
    assert "Lap 1" in block
