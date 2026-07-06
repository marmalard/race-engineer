"""Approach-triggered in-corner prompts from the previous lap's diagnoses.

Pure state machine — no pyirsdk, no I/O. After each debriefed lap,
build_schedule() converts the top loss regions into distance-triggered
prompts for the NEXT lap; feed() is called with LapDist each tick and
returns the prompt text when a trigger is crossed.

Safety rule baked in: a trigger is never placed inside a corner span —
the coach must not speak over a braking zone or mid-corner. A trigger
that would land inside a corner moves to just past that corner's exit;
if the remaining run to the anchor is too short to act on, the prompt
is dropped entirely.
"""

from dataclasses import dataclass

from core.coaching.debrief import RegionDiagnosis
from core.live.nudges import nudge_from_diagnosis
from core.track.models import Corner

# Tunable constants — expected to be adjusted from real driving, like the
# nudge thresholds before them.
LEAD_M = 300.0          # how far before the brake-onset anchor to speak
CLAMP_MARGIN_M = 30.0   # breathing room past a corner exit before speaking
MIN_GAP_M = 100.0       # minimum run from trigger to anchor to be actionable
MAX_PROMPTS = 3


@dataclass
class ScheduledPrompt:
    """One armed prompt: speak `text` when the car crosses `trigger_m`."""

    trigger_m: float
    text: str
    fired: bool = False


def _containing_corner(pos: float, corners: list[Corner]) -> Corner | None:
    # Assumes start <= end for every span; a corner whose span wraps the
    # start/finish line (start > end) would never match. The seeders
    # (lovely / Crew Chief) only produce non-wrapping spans today.
    for c in corners:
        if c.distance_start_meters <= pos <= c.distance_end_meters:
            return c
    return None


def _place_trigger(
    anchor: float,
    corners: list[Corner],
    track_length_m: float,
    lead_m: float,
    margin_m: float,
    min_gap_m: float,
) -> float | None:
    """Trigger distance for an anchor, or None when no safe spot exists."""
    trigger = (anchor - lead_m) % track_length_m
    inside = _containing_corner(trigger, corners)
    if inside is not None:
        trigger = (inside.distance_end_meters + margin_m) % track_length_m
        if _containing_corner(trigger, corners) is not None:
            return None  # chicane-dense stretch; no safe gap to speak in
        gap = (anchor - trigger) % track_length_m
        if gap < min_gap_m or gap > lead_m:
            return None  # too close to act on, or moved past the anchor
    return trigger


def build_schedule(
    diagnoses: list[RegionDiagnosis],
    corners: list[Corner],
    track_length_m: float,
    *,
    lead_m: float = LEAD_M,
    margin_m: float = CLAMP_MARGIN_M,
    min_gap_m: float = MIN_GAP_M,
    max_prompts: int = MAX_PROMPTS,
) -> list[ScheduledPrompt]:
    """Distance-triggered prompts for the next lap, from this lap's
    diagnoses (already sorted by time lost)."""
    if track_length_m <= 0:
        return []
    prompts: list[ScheduledPrompt] = []
    for diag in diagnoses:
        if len(prompts) >= max_prompts:
            break
        nudge = nudge_from_diagnosis(diag)
        if nudge is None:
            continue
        anchor = (
            diag.reference_brake_onset_m
            if diag.reference_brake_onset_m is not None
            else diag.region.distance_start
        )
        trigger = _place_trigger(
            anchor, corners, track_length_m, lead_m, margin_m, min_gap_m
        )
        if trigger is None:
            continue
        prompts.append(ScheduledPrompt(trigger_m=trigger, text=nudge.prompt))
    return prompts


class PromptScheduler:
    """Fires each armed prompt once as the car crosses its trigger."""

    def __init__(self, schedule: list[ScheduledPrompt] | None = None) -> None:
        self._schedule = schedule if schedule is not None else []
        self._prev_dist: float | None = None

    def set_schedule(self, schedule: list[ScheduledPrompt]) -> None:
        self._schedule = schedule
        self._prev_dist = None

    def rearm(self) -> None:
        """Reset fired flags at a lap boundary (same schedule, new lap)."""
        for p in self._schedule:
            p.fired = False

    def feed(self, lap_dist_m: float) -> str | None:
        """One tick. Returns prompt text iff a trigger was crossed.

        At most ONE prompt fires per tick; if two triggers land inside the
        same tick window (~1.4 m at 300 km/h and 60 Hz), the second is
        silently skipped for this lap rather than deferred — two prompts
        back-to-back would talk over each other anyway.
        """
        prev, self._prev_dist = self._prev_dist, lap_dist_m
        if prev is None:
            return None
        for p in self._schedule:
            if not p.fired and _crossed(prev, lap_dist_m, p.trigger_m):
                p.fired = True
                return p.text
        return None


def _crossed(prev: float, curr: float, trigger: float) -> bool:
    if curr >= prev:
        return prev < trigger <= curr
    # curr < prev is treated as a start/finish wrap. Safe because iRacing's
    # LapDist comes from the track spline (monotonic within a lap, no GPS
    # jitter); a genuine reversal (spin) is covered by the fired flag.
    return trigger > prev or trigger <= curr
