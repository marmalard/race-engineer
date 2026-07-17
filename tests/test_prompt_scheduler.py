"""Tests for the in-corner prompt scheduler (pure state machine)."""

from core.coaching.debrief import RegionDiagnosis
from core.live.nudges import FaultKind
from core.live.prompt_scheduler import (
    PromptScheduler,
    ScheduledPrompt,
    build_plan,
    build_schedule,
)
from core.telemetry.loss_regions import LossRegion
from core.track.models import Corner

TRACK_LEN = 7000.0


def _diag(label="La Source", start=1000.0, end=1100.0, braking=-15.0,
          onset=None) -> RegionDiagnosis:
    return RegionDiagnosis(
        region=LossRegion(distance_start=start, distance_end=end,
                          time_lost=0.5),
        label=label,
        braking_delta_m=braking,
        min_speed_delta_ms=0.0,
        throttle_delta_m=None,
        driver_min_speed_ms=20.0,
        reference_min_speed_ms=20.0,
        brake_release_delta_m=None,
        exit_speed_delta_ms=0.0,
        reference_brake_onset_m=onset,
    )


def _corner(start, end, name="C"):
    return Corner(corner_id=None, track_id="t", corner_number=1, name=name,
                  distance_start_meters=start, distance_end_meters=end,
                  corner_type=None)


def test_trigger_placed_lead_before_brake_onset():
    schedule = build_schedule([_diag(onset=800.0)], [], TRACK_LEN)
    assert len(schedule) == 1
    assert schedule[0].trigger_m == 500.0
    assert schedule[0].text.startswith("Coming up — brake")
    assert "La Source" not in schedule[0].text  # name dropped in approach cue


def test_trigger_falls_back_to_region_start_without_onset():
    schedule = build_schedule([_diag(start=1000.0, onset=None)], [], TRACK_LEN)
    assert schedule[0].trigger_m == 700.0


def test_trigger_inside_corner_moves_past_corner_end():
    corners = [_corner(450.0, 550.0)]
    schedule = build_schedule([_diag(onset=800.0)], corners, TRACK_LEN)
    # naive 500 is inside the corner -> moved to 550 + 30 margin
    assert schedule[0].trigger_m == 580.0


def test_trigger_dropped_when_gap_too_small():
    corners = [_corner(450.0, 730.0)]  # moved trigger 760, only 40m to anchor
    schedule = build_schedule([_diag(onset=800.0)], corners, TRACK_LEN)
    assert schedule == []


def test_trigger_dropped_when_moved_lands_in_next_corner():
    corners = [_corner(450.0, 550.0), _corner(560.0, 700.0)]
    schedule = build_schedule([_diag(onset=800.0)], corners, TRACK_LEN)
    assert schedule == []


def test_below_threshold_diagnosis_produces_no_prompt():
    schedule = build_schedule([_diag(braking=-2.0)], [], TRACK_LEN)
    assert schedule == []


def test_max_three_prompts():
    diags = [_diag(label=f"T{i}", onset=1000.0 * (i + 1)) for i in range(5)]
    schedule = build_schedule(diags, [], TRACK_LEN)
    assert len(schedule) == 3


def test_feed_fires_once_on_crossing():
    s = PromptScheduler([ScheduledPrompt(trigger_m=500.0, text="go")])
    assert s.feed(480.0) is None  # first sample primes prev_dist
    assert s.feed(510.0) == "go"
    assert s.feed(520.0) is None  # fired flag holds
    assert s.feed(490.0) is None  # driving backward over it doesn't re-fire


def test_rearm_resets_fired_flags():
    s = PromptScheduler([ScheduledPrompt(trigger_m=500.0, text="go")])
    s.feed(480.0)
    assert s.feed(510.0) == "go"
    s.rearm()
    s.feed(480.0)
    assert s.feed(510.0) == "go"


def test_feed_fires_across_start_finish_wrap():
    s = PromptScheduler([ScheduledPrompt(trigger_m=6950.0, text="wrap")])
    assert s.feed(6900.0) is None
    assert s.feed(20.0) == "wrap"  # crossed s/f between ticks


def test_empty_schedule_is_silent():
    s = PromptScheduler([])
    assert s.feed(100.0) is None
    assert s.feed(200.0) is None


def test_reset_position_prevents_false_wrap_fire_after_pits():
    """A backward position jump after a gated stretch (pit/tow) must not be
    mistaken for a start/finish wrap and fire a far-away trigger."""
    s = PromptScheduler([ScheduledPrompt(trigger_m=5500.0, text="far")])
    s.feed(4900.0)
    s.feed(5000.0)          # on track, trigger still ahead
    s.reset_position()      # feeds were skipped (towed to pits)
    assert s.feed(300.0) is None   # resume near pit exit: primes, no fire
    assert s.feed(400.0) is None   # still nowhere near the trigger


def test_build_plan_arms_verdict_per_scheduled_prompt():
    prompts, verdicts = build_plan([_diag(onset=800.0)], [], TRACK_LEN)
    assert len(prompts) == len(verdicts) == 1
    assert verdicts[0].diagnosis.label == "La Source"
    assert verdicts[0].faults[0] is FaultKind.BRAKING


def test_build_plan_dropped_prompt_arms_no_verdict():
    # No safe speaking gap -> prompt dropped -> no verdict either
    corners = [_corner(450.0, 730.0)]
    prompts, verdicts = build_plan([_diag(onset=800.0)], corners, TRACK_LEN)
    assert prompts == [] and verdicts == []


def test_build_schedule_still_returns_prompts_only():
    schedule = build_schedule([_diag(onset=800.0)], [], TRACK_LEN)
    assert len(schedule) == 1 and isinstance(schedule[0], ScheduledPrompt)
