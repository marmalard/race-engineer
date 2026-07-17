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
