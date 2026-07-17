"""Exit verdicts: bucketing precedence, phrasing, and the watcher."""

from core.live.exit_verdict import (
    IMPROVED_FRACTION,
    bucket_for,
    crossed,
    verdict_text,
)
from core.live.nudges import FaultKind


class TestBucketPrecedence:
    # BRAKING threshold is 8.0 m (imported from nudges).

    def test_under_threshold_is_fixed(self):
        assert bucket_for(FaultKind.BRAKING, -5.0, -15.0) == "fixed"

    def test_sign_flip_past_threshold_overcorrects_braking(self):
        # Coached "later" (was early, -15); driver now brakes 10m LATE.
        assert bucket_for(FaultKind.BRAKING, 10.0, -15.0) == "overcorrected"

    def test_overcorrect_beats_better_precedence(self):
        # Sign flipped AND numerically under half of last lap: must be
        # overcorrected, never "better still late" with the wrong word
        # (the spec's precedence bug).
        assert bucket_for(FaultKind.BRAKING, 9.0, -30.0) == "overcorrected"

    def test_shrunk_but_not_fixed_is_better(self):
        assert bucket_for(FaultKind.BRAKING, -10.0, -25.0) == "better"

    def test_unchanged(self):
        assert bucket_for(FaultKind.BRAKING, -14.0, -15.0) == "unchanged"

    def test_speed_faults_never_overcorrect(self):
        # Carrying MORE speed than the reference is not a fault to scold.
        assert bucket_for(FaultKind.LIFT, 3.0, -4.0) == "fixed"
        assert bucket_for(FaultKind.EXIT_SPEED, 3.0, -4.0) == "fixed"

    def test_early_throttle_is_fixed_not_overcorrected(self):
        assert bucket_for(FaultKind.THROTTLE, -25.0, 30.0) == "fixed"

    def test_release_overcorrects(self):
        # Coached "carry them deeper" (was -12); now 11m PAST the ref.
        assert bucket_for(FaultKind.RELEASE, 11.0, -12.0) == "overcorrected"


class TestVerdictText:
    def test_fixed(self):
        assert verdict_text(FaultKind.BRAKING, "fixed", -3.0) == "That's it."

    def test_braking_directions(self):
        assert (verdict_text(FaultKind.BRAKING, "better", -10.0)
                == "Better — still a touch early.")
        assert (verdict_text(FaultKind.BRAKING, "unchanged", 12.0)
                == "Still late on the brakes.")

    def test_overcorrect_lines(self):
        assert (verdict_text(FaultKind.BRAKING, "overcorrected", 10.0)
                == "Too far — back it off.")
        assert (verdict_text(FaultKind.RELEASE, "overcorrected", 11.0)
                == "Too deep — release sooner.")

    def test_speed_and_throttle_lines(self):
        assert (verdict_text(FaultKind.LIFT, "unchanged", -4.0)
                == "Still slow through there.")
        assert (verdict_text(FaultKind.EXIT_SPEED, "better", -2.5)
                == "Better — still a touch slow off the corner.")
        assert (verdict_text(FaultKind.THROTTLE, "unchanged", 30.0)
                == "Still late to throttle.")


class TestCrossed:
    def test_forward_and_wrap(self):
        assert crossed(480.0, 510.0, 500.0)
        assert not crossed(510.0, 520.0, 500.0)
        assert crossed(6900.0, 20.0, 6950.0)  # start/finish wrap


from core.coaching.debrief import RegionDiagnosis
from core.live.exit_verdict import ArmedVerdict, VerdictResult, VerdictWatcher
from core.telemetry.loss_regions import LossRegion

TRACK_LEN = 7000.0


def _armed(span=(1000.0, 1100.0), braking_delta=-15.0, ref_onset=980.0,
           faults=(FaultKind.BRAKING,)) -> ArmedVerdict:
    diag = RegionDiagnosis(
        region=LossRegion(distance_start=span[0], distance_end=span[1],
                          time_lost=0.5),
        label="La Source",
        braking_delta_m=braking_delta,
        min_speed_delta_ms=0.0,
        throttle_delta_m=None,
        driver_min_speed_ms=20.0,
        reference_min_speed_ms=20.0,
        reference_brake_onset_m=ref_onset,
    )
    return ArmedVerdict(diagnosis=diag, faults=list(faults))


def _drive(watcher, start, end, step=10.0, speed=40.0, brake=0.0,
           throttle=0.0):
    """Feed a straight run of ticks; return the first VerdictResult."""
    d = start
    result = None
    while d <= end:
        r = watcher.feed(d, speed, brake, throttle)
        result = result or r
        d += step
    return result


class TestVerdictWatcher:
    def test_braking_verdict_fires_past_exit(self):
        w = VerdictWatcher()
        w.set_plan([_armed()], TRACK_LEN)
        _drive(w, 700.0, 985.0)                      # no brake yet
        w.feed(990.0, 30.0, 0.5, 0.0)                # brake onset at 990
        _drive(w, 1000.0, 1190.0, speed=25.0)        # through the corner
        r = w.feed(1210.0, 30.0, 0.0, 1.0)           # crosses 1100+100
        assert isinstance(r, VerdictResult)
        assert r.label == "La Source"
        assert r.kind is FaultKind.BRAKING
        # onset 990 vs ref 980 -> +10 late; last lap -15 early -> flip
        assert r.bucket == "overcorrected"
        assert r.text == "Too far — back it off."

    def test_fixed_when_onset_matches_reference(self):
        w = VerdictWatcher()
        w.set_plan([_armed()], TRACK_LEN)
        _drive(w, 700.0, 975.0)
        w.feed(983.0, 30.0, 0.5, 0.0)                # 3m late: under 8m
        _drive(w, 990.0, 1190.0, speed=25.0)
        r = w.feed(1210.0, 30.0, 0.0, 1.0)
        assert r.bucket == "fixed"
        assert r.text == "That's it."

    def test_no_brake_observed_is_silent(self):
        w = VerdictWatcher()
        w.set_plan([_armed()], TRACK_LEN)
        r = _drive(w, 700.0, 1250.0)                 # never brakes
        assert r is None                             # insufficient data

    def test_fires_once_per_lap_and_rearm(self):
        w = VerdictWatcher()
        w.set_plan([_armed()], TRACK_LEN)
        _drive(w, 700.0, 975.0)
        w.feed(983.0, 30.0, 0.5, 0.0)
        _drive(w, 990.0, 1190.0)
        assert w.feed(1210.0, 30.0, 0.0, 1.0) is not None
        assert w.feed(1220.0, 30.0, 0.0, 1.0) is None   # fired flag holds
        w.rearm()
        _drive(w, 700.0, 975.0)
        w.feed(983.0, 30.0, 0.5, 0.0)
        _drive(w, 990.0, 1190.0)
        assert w.feed(1210.0, 30.0, 0.0, 1.0) is not None

    def test_reset_position_prevents_false_wrap_fire(self):
        w = VerdictWatcher()
        w.set_plan([_armed(span=(5400.0, 5500.0), ref_onset=5380.0)],
                   TRACK_LEN)
        w.feed(5300.0, 40.0, 0.5, 0.0)
        w.reset_position()                           # towed to pits
        assert w.feed(300.0, 20.0, 0.0, 0.0) is None  # primes, no fire
        assert w.feed(400.0, 20.0, 0.0, 0.0) is None

    def test_lift_verdict_uses_observed_min_speed(self):
        armed = _armed(faults=(FaultKind.LIFT,))
        armed.diagnosis.min_speed_delta_ms = -4.0    # last lap: 4 m/s slow
        w = VerdictWatcher()
        w.set_plan([armed], TRACK_LEN)
        _drive(w, 700.0, 990.0, speed=40.0)
        _drive(w, 1000.0, 1090.0, speed=19.0)        # min 19 vs ref 20:
        r = _drive(w, 1100.0, 1250.0, speed=30.0)    # 1 m/s slow -> fixed
        assert r is not None and r.bucket == "fixed"

    def test_empty_plan_is_silent(self):
        w = VerdictWatcher()
        w.set_plan([], TRACK_LEN)
        assert _drive(w, 0.0, 500.0) is None
