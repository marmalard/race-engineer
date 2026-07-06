"""Tests for turning a RegionDiagnosis into a terse coaching nudge."""

from core.coaching.debrief import RegionDiagnosis
from core.live.nudges import Nudge, format_lap_block, format_lap_speech, nudge_from_diagnosis
from core.telemetry.loss_regions import LossRegion


def _diag(label="Eau Rouge", time_lost=0.4, braking=None, min_speed=0.0,
          throttle=None, drv_min=60.0, ref_min=60.0, release=None,
          exit_speed=0.0, onset=None) -> RegionDiagnosis:
    return RegionDiagnosis(
        region=LossRegion(distance_start=1000.0, distance_end=1100.0,
                          time_lost=time_lost),
        label=label,
        braking_delta_m=braking,
        min_speed_delta_ms=min_speed,
        throttle_delta_m=throttle,
        driver_min_speed_ms=drv_min,
        reference_min_speed_ms=ref_min,
        brake_release_delta_m=release,
        exit_speed_delta_ms=exit_speed,
        reference_brake_onset_m=onset,
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


def test_early_release_says_carry_brakes_deeper():
    n = nudge_from_diagnosis(_diag(release=-15.0, min_speed=-0.5))
    assert n is not None
    assert "brakes deeper" in n.message.lower()
    assert "15" in n.detail


def test_release_below_threshold_returns_none():
    n = nudge_from_diagnosis(_diag(release=-6.0, min_speed=-0.5))
    assert n is None


def test_slow_exit_says_prioritize_the_exit():
    n = nudge_from_diagnosis(_diag(exit_speed=-3.0, min_speed=-0.5))
    assert n is not None
    assert "exit" in n.message.lower()


def test_braking_point_outranks_release():
    n = nudge_from_diagnosis(_diag(braking=-12.0, release=-15.0, min_speed=-0.5))
    assert "brake later" in n.message.lower()


def test_release_outranks_exit_speed():
    n = nudge_from_diagnosis(_diag(release=-12.0, exit_speed=-3.0, min_speed=-0.5))
    assert "brakes deeper" in n.message.lower()


def test_exit_speed_outranks_throttle():
    n = nudge_from_diagnosis(_diag(exit_speed=-3.0, throttle=30.0, min_speed=-0.5))
    assert "exit" in n.message.lower()


def test_speech_uses_car_lengths_not_meters():
    n = nudge_from_diagnosis(_diag(braking=-15.0, min_speed=-0.5))
    assert "car length" in n.speech.lower()
    assert "15m" not in n.speech


def test_prompt_is_terse_imperative_with_corner():
    """In-corner prompts are quantity-free — the magnitude was spoken
    between laps; at speed the driver needs only the instruction."""
    n = nudge_from_diagnosis(_diag(label="La Source", braking=-15.0, min_speed=-0.5))
    assert n.prompt == "La Source — brake later."
    assert "car length" not in n.prompt


def test_every_rung_has_speech_and_prompt():
    rungs = [
        _diag(min_speed=-4.0, drv_min=55.0, ref_min=59.0),  # flat lift
        _diag(min_speed=-4.0, drv_min=16.0, ref_min=20.0),  # apex speed
        _diag(braking=-15.0, min_speed=-0.5),               # brake later
        _diag(braking=14.0, min_speed=-0.5),                # brake earlier
        _diag(release=-15.0, min_speed=-0.5),               # trail
        _diag(exit_speed=-3.0, min_speed=-0.5),             # exit
        _diag(throttle=30.0, min_speed=-0.5),               # throttle
    ]
    for d in rungs:
        n = nudge_from_diagnosis(d)
        assert n is not None
        assert n.speech and n.prompt
        assert n.corner in n.speech and n.corner in n.prompt


def test_release_threshold_boundary():
    """Exactly -10.0 fires (<= semantics); just above it does not."""
    assert nudge_from_diagnosis(_diag(release=-10.0, min_speed=-0.5)) is not None
    assert nudge_from_diagnosis(_diag(release=-9.9, min_speed=-0.5)) is None


def test_lift_dominates_all_rungs():
    """Apex-speed deficit outranks every other signal regardless of magnitude."""
    n = nudge_from_diagnosis(_diag(
        min_speed=-3.0, drv_min=30.0, ref_min=33.0,
        braking=-20.0, release=-20.0, exit_speed=-5.0, throttle=40.0,
    ))
    assert "carry" in n.message.lower()


def test_speech_baseline():
    speech, flagged = format_lap_speech(131.4, 0.0, [], is_baseline=True)
    assert speech == "Baseline set. 2 11.4."
    assert flagged == set()


def test_speech_slower_lap_reads_delta_then_top_nudge():
    diags = [_diag(label="Les Combes", braking=-15.0, min_speed=-0.5)]
    speech, flagged = format_lap_speech(132.0, 0.3, diags)
    assert speech.startswith("Up 3 tenths.")
    assert "Les Combes" in speech
    assert "car length" in speech
    assert flagged == {"Les Combes"}


def test_speech_singular_tenth():
    speech, _ = format_lap_speech(132.0, 0.11, [])
    assert speech.startswith("Up a tenth.")


def test_speech_faster_lap():
    speech, _ = format_lap_speech(130.9, -0.4, [])
    assert speech.startswith("4 tenths quicker.")


def test_speech_big_delta_in_seconds():
    speech, _ = format_lap_speech(133.0, 1.4, [])
    assert speech.startswith("Up 1.4 seconds.")


def test_speech_clean_lap():
    speech, _ = format_lap_speech(131.5, 0.05, [])
    assert "clean lap" in speech.lower()


def test_speech_only_top_nudge_is_spoken():
    diags = [
        _diag(label="Eau Rouge", min_speed=-4.0, drv_min=55.0, ref_min=59.0),
        _diag(label="Pouhon", braking=-15.0, min_speed=-0.5),
    ]
    speech, flagged = format_lap_speech(132.0, 0.5, diags)
    assert "Eau Rouge" in speech
    assert "Pouhon" not in speech  # flagged, but not spoken
    assert flagged == {"Eau Rouge", "Pouhon"}


def test_speech_confirmation_when_flagged_corner_heals_on_improving_lap():
    diags = [_diag(label="Eau Rouge", braking=-15.0, min_speed=-0.5)]
    speech, _ = format_lap_speech(
        131.0, 0.2, diags, prev_flagged={"Pouhon", "Eau Rouge"}, improved=True
    )
    assert "Pouhon — that's it, keep that." in speech


def test_speech_no_confirmation_when_lap_did_not_improve():
    speech, _ = format_lap_speech(
        133.0, 1.0, [], prev_flagged={"Pouhon"}, improved=False
    )
    assert "that's it" not in speech


def test_speech_lap_time_minute_rollover_and_padding():
    """1:59.97 must carry to '2 00.0', and sub-10s seconds are zero-padded
    so SAPI says 'oh five' instead of an ambiguous 'five'."""
    from core.live.nudges import _speech_lap_time
    assert _speech_lap_time(119.97) == "2 00.0"
    assert _speech_lap_time(65.03) == "1 05.0"
