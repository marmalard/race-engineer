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
    'still a touch late' with the wrong direction word.

    Both deltas follow debrief sign conventions (negative braking =
    earlier, positive throttle = later). `last_delta` is the coached
    fault's delta from the approach cue — always >= threshold in
    magnitude by construction, so it is never 0. Note "better" is
    structurally inert when abs(last_delta) < 2x threshold (the fixed
    band swallows it) — that is by design, not a tuning bug."""
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
    (like nudges); tune wording there, nowhere else.
    `live_delta` disambiguates late/early for BRAKING only."""
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


@dataclass
class ArmedVerdict:
    """One prompted corner awaiting its exit verdict this lap."""

    diagnosis: RegionDiagnosis
    faults: "list[FaultKind]"


@dataclass
class VerdictResult:
    """One spoken verdict plus the numbers behind it (session log)."""

    text: str
    label: str
    kind: FaultKind
    bucket: str
    live_delta: float
    observed_brake_onset_m: "float | None"
    observed_min_speed_ms: "float | None"
    observed_throttle_on_m: "float | None"


@dataclass
class _Observation:
    """Passively accumulated execution facts for one armed corner."""

    fired: bool = False
    brake_onset_m: "float | None" = None
    min_speed_ms: "float | None" = None
    min_speed_m: "float | None" = None
    last_brake_on_m: "float | None" = None
    release_m: "float | None" = None       # last brake-on at/before the
    throttle_on_m: "float | None" = None   # (final) min-speed point
    exit_speed_ms: "float | None" = None


class VerdictWatcher:
    """Observes prompted corners from live ticks; emits one verdict per
    corner per lap when the car crosses span_end + VERDICT_POINT_M."""

    def __init__(self) -> None:
        self._armed: list[ArmedVerdict] = []
        self._obs: list[_Observation] = []
        self._track_length_m: float = 0.0
        self._prev_dist: "float | None" = None

    def set_plan(
        self, verdicts: "list[ArmedVerdict]", track_length_m: float
    ) -> None:
        self._armed = verdicts
        self._track_length_m = track_length_m
        self.rearm()

    def rearm(self) -> None:
        """Fresh observations at a lap boundary (same plan, new lap)."""
        self._obs = [_Observation() for _ in self._armed]
        self._prev_dist = None

    def reset_position(self) -> None:
        """Forget the last distance sample while feeds are being skipped
        (pits/tow) — same rationale as PromptScheduler.reset_position."""
        self._prev_dist = None

    def feed(
        self, lap_dist_m: float, speed_ms: float, brake: float,
        throttle: float,
    ) -> "VerdictResult | None":
        prev, self._prev_dist = self._prev_dist, lap_dist_m
        result: "VerdictResult | None" = None
        for armed, obs in zip(self._armed, self._obs):
            if obs.fired:
                continue
            self._observe(armed, obs, lap_dist_m, speed_ms, brake, throttle)
            if prev is None or self._track_length_m <= 0:
                continue
            verdict_point = (
                armed.diagnosis.region.distance_end + VERDICT_POINT_M
            ) % self._track_length_m
            if crossed(prev, lap_dist_m, verdict_point):
                obs.fired = True
                if result is None:  # one verdict per tick, like prompts
                    result = self._judge(armed, obs)
        return result

    def _observe(
        self, armed: ArmedVerdict, obs: _Observation, dist: float,
        speed: float, brake: float, throttle: float,
    ) -> None:
        span_start = armed.diagnosis.region.distance_start
        span_end = armed.diagnosis.region.distance_end
        window_start = max(0.0, span_start - BRAKE_SEARCH_BACK_M)
        in_window = window_start <= dist <= span_end
        if in_window:
            if brake > BRAKE_THRESHOLD:
                if obs.brake_onset_m is None:
                    obs.brake_onset_m = dist
                obs.last_brake_on_m = dist
            if obs.min_speed_ms is None or speed < obs.min_speed_ms:
                obs.min_speed_ms = speed
                obs.min_speed_m = dist
                # A new (final-so-far) apex: the trailing brake release is
                # the last brake-on seen up to here, and any throttle-on
                # recorded before it was pre-apex — rearm it.
                obs.release_m = obs.last_brake_on_m
                obs.throttle_on_m = None
        if (obs.throttle_on_m is None and obs.min_speed_m is not None
                and dist > obs.min_speed_m
                and dist <= span_end + VERDICT_POINT_M
                and throttle > THROTTLE_THRESHOLD):
            obs.throttle_on_m = dist
        if obs.exit_speed_ms is None and dist >= span_end:
            obs.exit_speed_ms = speed

    def _judge(
        self, armed: ArmedVerdict, obs: _Observation
    ) -> "VerdictResult | None":
        if not armed.faults:
            return None
        kind = armed.faults[0]
        live = self._live_delta(kind, armed.diagnosis, obs)
        last = self._last_delta(kind, armed.diagnosis)
        if live is None or last is None or last == 0.0:
            return None  # insufficient observation: silence, never guess
        bucket = bucket_for(kind, live, last)
        return VerdictResult(
            text=verdict_text(kind, bucket, live),
            label=armed.diagnosis.label,
            kind=kind,
            bucket=bucket,
            live_delta=live,
            observed_brake_onset_m=obs.brake_onset_m,
            observed_min_speed_ms=obs.min_speed_ms,
            observed_throttle_on_m=obs.throttle_on_m,
        )

    @staticmethod
    def _live_delta(
        kind: FaultKind, diag: RegionDiagnosis, obs: _Observation
    ) -> "float | None":
        if kind is FaultKind.BRAKING:
            if obs.brake_onset_m is None or diag.reference_brake_onset_m is None:
                return None
            return obs.brake_onset_m - diag.reference_brake_onset_m
        if kind is FaultKind.LIFT:
            if obs.min_speed_ms is None:
                return None
            return obs.min_speed_ms - diag.reference_min_speed_ms
        if kind is FaultKind.RELEASE:
            if obs.release_m is None or diag.reference_release_m is None:
                return None
            return obs.release_m - diag.reference_release_m
        if kind is FaultKind.EXIT_SPEED:
            if obs.exit_speed_ms is None or diag.reference_exit_speed_ms is None:
                return None
            return obs.exit_speed_ms - diag.reference_exit_speed_ms
        if obs.throttle_on_m is None or diag.reference_throttle_on_m is None:
            return None
        return obs.throttle_on_m - diag.reference_throttle_on_m

    @staticmethod
    def _last_delta(kind: FaultKind, diag: RegionDiagnosis) -> "float | None":
        return {
            FaultKind.BRAKING: diag.braking_delta_m,
            FaultKind.LIFT: diag.min_speed_delta_ms,
            FaultKind.RELEASE: diag.brake_release_delta_m,
            FaultKind.EXIT_SPEED: diag.exit_speed_delta_ms,
            FaultKind.THROTTLE: diag.throttle_delta_m,
        }[kind]
