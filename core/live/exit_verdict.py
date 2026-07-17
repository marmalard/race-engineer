"""At-exit corner verdicts — closing the approach-cue feedback loop.

Pure state machine, no pyirsdk, no I/O (PromptScheduler's shape). After
an approach cue speaks for a corner, VerdictWatcher observes the
driver's execution of THAT corner from live ticks and speaks a
one-clause bucket verdict ~100 m past the exit: "That's it." /
"Too far — back it off." / "Better — still a touch late." /
"Still late on the brakes." Quantity-free by design — the driver is at
speed and cannot act on numbers.

Anti-drift locks: thresholds and search windows are IMPORTED from their
homes (nudges / debrief), never copied; a coupling test replays a real
lap and asserts the live brake-onset observation matches the offline
diagnosis. Live LapDist vs the aligned reference carries the same small
alignment tolerance the approach-cue triggers already accept.

Spec: docs/superpowers/specs/2026-07-16-exit-verdict-cues-design.md
"""

from dataclasses import dataclass

from core.coaching.debrief import (
    BRAKE_SEARCH_BACK_M,
    BRAKE_THRESHOLD,
    THROTTLE_THRESHOLD,
    RegionDiagnosis,
)
from core.live.nudges import (
    BRAKING_THRESHOLD_M,
    EXIT_SPEED_THRESHOLD_MS,
    MIN_SPEED_THRESHOLD_MS,
    RELEASE_THRESHOLD_M,
    THROTTLE_THRESHOLD_M,
    FaultKind,
)

# Verdict fires this far past the region end — the end of the offline
# throttle search window, ~1-2s past the exit at speed. Tunable from
# data/live_sessions logs like every live threshold before it.
VERDICT_POINT_M = 100.0
# "Better" = live magnitude under this fraction of last lap's.
IMPROVED_FRACTION = 0.5
# Only distance faults where going PAST the reference is genuinely risky
# get the overcorrect call-out; more speed / earlier throttle than the
# reference is not a fault to scold ("fixed").
OVERCORRECT_KINDS = frozenset({FaultKind.BRAKING, FaultKind.RELEASE})

_THRESHOLDS = {
    FaultKind.LIFT: MIN_SPEED_THRESHOLD_MS,
    FaultKind.BRAKING: BRAKING_THRESHOLD_M,
    FaultKind.RELEASE: RELEASE_THRESHOLD_M,
    FaultKind.EXIT_SPEED: EXIT_SPEED_THRESHOLD_MS,
    FaultKind.THROTTLE: THROTTLE_THRESHOLD_M,
}


def crossed(prev: float, curr: float, trigger: float) -> bool:
    """True iff the car crossed `trigger` between two distance samples.
    curr < prev is treated as a start/finish wrap (LapDist is spline-
    monotonic within a lap; genuine reversals are covered by fired
    flags). Shared with PromptScheduler."""
    if curr >= prev:
        return prev < trigger <= curr
    return trigger > prev or trigger <= curr


def bucket_for(kind: FaultKind, live_delta: float, last_delta: float) -> str:
    """Bucket the live delta for the coached fault. Precedence (spec):
    fixed -> overcorrected -> better -> unchanged. Overcorrection is
    checked BEFORE better so a sign-flipped delta can never produce
    'still a touch late' with the wrong direction word."""
    threshold = _THRESHOLDS[kind]
    if abs(live_delta) < threshold:
        return "fixed"
    same_side = (live_delta > 0) == (last_delta > 0)
    if not same_side:
        return "overcorrected" if kind in OVERCORRECT_KINDS else "fixed"
    if abs(live_delta) < IMPROVED_FRACTION * abs(last_delta):
        return "better"
    return "unchanged"


def verdict_text(kind: FaultKind, bucket: str, live_delta: float) -> str:
    """The spoken one-clause verdict. Exact strings are pinned by tests
    (like nudges); tune wording there, nowhere else."""
    if bucket == "fixed":
        return "That's it."
    if bucket == "overcorrected":
        if kind is FaultKind.RELEASE:
            return "Too deep — release sooner."
        return "Too far — back it off."
    better = bucket == "better"
    if kind is FaultKind.BRAKING:
        word = "late" if live_delta > 0 else "early"
        return (f"Better — still a touch {word}." if better
                else f"Still {word} on the brakes.")
    if kind is FaultKind.LIFT:
        return ("Better — still a bit slow." if better
                else "Still slow through there.")
    if kind is FaultKind.RELEASE:
        return ("Better — carry them a touch deeper." if better
                else "Still off the brakes early.")
    if kind is FaultKind.EXIT_SPEED:
        return ("Better — still a touch slow off the corner." if better
                else "Still slow off the corner.")
    return ("Better — still a touch late to throttle." if better
            else "Still late to throttle.")
