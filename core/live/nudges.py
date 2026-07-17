"""Turn a deterministic RegionDiagnosis into one terse coaching nudge.

No AI, no API key on the critical path. Each loss region yields at most
one imperative line plus the number that justifies it, chosen by salience:
a big apex-speed deficit (a lift) outranks a braking-point error, which
outranks a brake-release error, which outranks an exit-speed deficit,
which outranks a late throttle pickup. Thresholds are tuned during the
spike so only meaningful deltas speak.
"""

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from core.coaching.debrief import RegionDiagnosis
from core.live.session_reader import DiscardReason
from core.race.narrative import corner_name_at
from core.telemetry.cleanliness import IncidentMark

if TYPE_CHECKING:
    from core.benchmark.reference_store import ReferenceLapMeta

# Salience thresholds — below these, a delta is not worth a nudge.
BRAKING_THRESHOLD_M = 8.0
MIN_SPEED_THRESHOLD_MS = 2.0
THROTTLE_THRESHOLD_M = 20.0
RELEASE_THRESHOLD_M = 10.0
EXIT_SPEED_THRESHOLD_MS = 2.0
# Reference apex speed above this (m/s) = a fast/flat corner where the
# right coaching is "carry it flat" rather than "carry more apex speed".
# 50 m/s ≈ 180 km/h.
FLAT_CORNER_MIN_SPEED_MS = 50.0
# Spoken distances use car lengths — drivers translate "a car length later"
# onto their own visual markers far better than raw meters at speed.
CAR_LENGTH_M = 4.5

# Approach-cue magnitude buckets (car lengths) — coarse on purpose; a driver
# can't act on fake-exact meters at speed. Tunable from data/live_sessions logs.
APPROACH_CUE_MAX_FAULTS = 2
COARSE_A_BIT_MAX_LENGTHS = 2.5
COARSE_COUPLE_MAX_LENGTHS = 5.0


class FaultKind(Enum):
    """One coached fault dimension — the shared vocabulary of the
    approach cue and the exit verdict (they derive from the same
    ranking so they can never disagree)."""

    LIFT = "lift"
    BRAKING = "braking"
    RELEASE = "release"
    EXIT_SPEED = "exit_speed"
    THROTTLE = "throttle"


def fault_kinds_from_diagnosis(diag: "RegionDiagnosis") -> "list[FaultKind]":
    """Faults crossing threshold, ordered by the salience ladder:
    lift > braking > release > exit speed > throttle."""
    kinds: list[FaultKind] = []
    if diag.min_speed_delta_ms <= -MIN_SPEED_THRESHOLD_MS:
        kinds.append(FaultKind.LIFT)
    if (diag.braking_delta_m is not None
            and abs(diag.braking_delta_m) >= BRAKING_THRESHOLD_M):
        kinds.append(FaultKind.BRAKING)
    if (diag.brake_release_delta_m is not None
            and diag.brake_release_delta_m <= -RELEASE_THRESHOLD_M):
        kinds.append(FaultKind.RELEASE)
    if diag.exit_speed_delta_ms <= -EXIT_SPEED_THRESHOLD_MS:
        kinds.append(FaultKind.EXIT_SPEED)
    if (diag.throttle_delta_m is not None
            and diag.throttle_delta_m >= THROTTLE_THRESHOLD_M):
        kinds.append(FaultKind.THROTTLE)
    return kinds


@dataclass
class Nudge:
    """One imperative coaching line for a single corner."""

    corner: str
    message: str
    detail: str  # the justifying number, e.g. "-14 km/h" or "15m"
    speech: str  # full between-lap spoken sentence (includes corner name)


def _kmh(ms: float) -> float:
    return ms * 3.6


def _car_lengths_phrase(meters: float) -> str:
    """'15m' -> '3 and a half car lengths' (Python round() to nearest half;
    callers pass whole-meter deltas from the 1m grid)."""
    lengths = max(0.5, round(abs(meters) / CAR_LENGTH_M * 2) / 2)
    if lengths == 0.5:
        return "half a car length"
    if lengths == 1.0:
        return "a car length"
    if lengths == 1.5:
        return "a car length and a half"
    whole = int(lengths)
    if lengths == whole:
        return f"{whole} car lengths"
    return f"{whole} and a half car lengths"


def nudge_from_diagnosis(diag: RegionDiagnosis) -> "Nudge | None":
    """The single most salient nudge for this region, or None if nothing
    crosses threshold.

    Salience: lift > braking point > brake release (trail) > exit speed >
    throttle pickup.
    """
    corner = diag.label

    # 1) Apex-speed deficit (a lift / over-slow) is the headline when big.
    if diag.min_speed_delta_ms <= -MIN_SPEED_THRESHOLD_MS:
        deficit_kmh = abs(_kmh(diag.min_speed_delta_ms))
        detail = f"-{deficit_kmh:.0f} km/h"
        if diag.reference_min_speed_ms >= FLAT_CORNER_MIN_SPEED_MS:
            return Nudge(
                corner=corner,
                message="carry it flat, you lifted",
                detail=detail,
                speech=f"{corner}. Carry it flat, you lifted.",
            )
        return Nudge(
            corner=corner,
            message="carry more apex speed",
            detail=detail,
            speech=(
                f"{corner}. Carry more apex speed, you had "
                f"{deficit_kmh:.0f} k more on the reference."
            ),
        )

    # 2) Braking-point error.
    if diag.braking_delta_m is not None and abs(diag.braking_delta_m) >= BRAKING_THRESHOLD_M:
        meters = abs(diag.braking_delta_m)
        lengths = _car_lengths_phrase(meters)
        if diag.braking_delta_m < 0:
            return Nudge(
                corner=corner,
                message="brake later",
                detail=f"{meters:.0f}m",
                speech=f"{corner}. Brake {lengths} later.",
            )
        return Nudge(
            corner=corner,
            message="brake earlier",
            detail=f"{meters:.0f}m",
            speech=f"{corner}. Brake {lengths} earlier.",
        )

    # 3) Brake release (trail braking) — fires only when the reference
    #    trail-brakes (brake_release_delta_m is not None) and the driver
    #    releases significantly earlier.
    if (
        diag.brake_release_delta_m is not None
        and diag.brake_release_delta_m <= -RELEASE_THRESHOLD_M
    ):
        meters = abs(diag.brake_release_delta_m)
        lengths = _car_lengths_phrase(meters)
        return Nudge(
            corner=corner,
            message="carry the brakes deeper",
            detail=f"{meters:.0f}m",
            speech=f"{corner}. Release the brakes more slowly, carry them {lengths} deeper.",
        )

    # 4) Exit-speed deficit — slow onto the following straight.
    # exit_speed_delta_ms is always a float (defaults 0.0 in RegionDiagnosis,
    # never None) — no guard needed, unlike the Optional fields above.
    if diag.exit_speed_delta_ms <= -EXIT_SPEED_THRESHOLD_MS:
        deficit_kmh = abs(_kmh(diag.exit_speed_delta_ms))
        return Nudge(
            corner=corner,
            message="prioritize the exit",
            detail=f"-{deficit_kmh:.0f} km/h",
            speech=(
                f"{corner}. Prioritize the exit, you're "
                f"{deficit_kmh:.0f} k slow onto the straight."
            ),
        )

    # 5) Late throttle pickup.
    if diag.throttle_delta_m is not None and diag.throttle_delta_m >= THROTTLE_THRESHOLD_M:
        return Nudge(
            corner=corner,
            message="back to power earlier",
            detail=f"{diag.throttle_delta_m:.0f}m",
            speech=f"{corner}. Back to power earlier.",
        )

    return None


def _coarse_length_phrase(meters: float) -> str:
    """Coarse braking magnitude in car lengths: 'a bit' / 'a couple car
    lengths' / 'a lot'. No fake precision — the driver adjusts a marker."""
    lengths = abs(meters) / CAR_LENGTH_M
    if lengths < COARSE_A_BIT_MAX_LENGTHS:
        return "a bit"
    if lengths < COARSE_COUPLE_MAX_LENGTHS:
        return "a couple car lengths"
    return "a lot"


def _cue_phrase(kind: FaultKind, diag: RegionDiagnosis) -> str:
    """The spoken phrase fragment for a single fault kind in an approach cue."""
    if kind is FaultKind.LIFT:
        if diag.reference_min_speed_ms >= FLAT_CORNER_MIN_SPEED_MS:
            return "carry it flat, don't lift"
        return "carry more apex speed"
    if kind is FaultKind.BRAKING:
        coarse = _coarse_length_phrase(diag.braking_delta_m)
        return (f"brake {coarse} later" if diag.braking_delta_m < 0
                else f"brake {coarse} earlier")
    if kind is FaultKind.RELEASE:
        return "carry the brakes deeper"
    if kind is FaultKind.EXIT_SPEED:
        return "prioritize the exit"
    return "get to throttle earlier on exit"


def approach_cue_from_diagnosis(diag: RegionDiagnosis) -> "str | None":
    """One combined approach cue for a corner, or None if nothing crosses
    threshold. Spoken ~300m before the corner, so it names no corner ('here')
    and joins the top APPROACH_CUE_MAX_FAULTS faults by the salience ladder:
    lift > braking > release > exit > throttle."""
    kinds = fault_kinds_from_diagnosis(diag)
    if not kinds:
        return None
    phrases = [_cue_phrase(k, diag) for k in kinds[:APPROACH_CUE_MAX_FAULTS]]
    return "Coming up — " + ", ".join(phrases) + "."


def _fmt_lap_time(seconds: float) -> str:
    mins = int(seconds // 60)
    secs = seconds % 60
    return f"{mins}:{secs:06.3f}"


def _speech_lap_time(seconds: float) -> str:
    """131.4 -> '2 11.4' — SAPI reads it as 'two eleven point four'.

    Seconds are zero-padded ('1 05.0', not '1 5.0') so SAPI says "oh five"
    rather than an ambiguous "five", and rounding that hits 60.0 carries
    into the minutes (1:59.97 must not become '1 60.0')."""
    mins = int(seconds // 60)
    secs = round(seconds % 60, 1)
    if secs >= 60.0:
        mins += 1
        secs = 0.0
    return f"{mins} {secs:04.1f}"


def _speech_delta(total_delta: float) -> str:
    """Lap delta as a spoken sentence, in tenths (or seconds when >= 1s)."""
    tenths = round(abs(total_delta) * 10)
    if tenths == 0:
        return "Even with the reference."
    if tenths >= 10:
        secs = f"{abs(total_delta):.1f}"
        return f"Up {secs} seconds." if total_delta > 0 else f"{secs} seconds quicker."
    if tenths == 1:
        return "Up a tenth." if total_delta > 0 else "A tenth quicker."
    return f"Up {tenths} tenths." if total_delta > 0 else f"{tenths} tenths quicker."


def format_radio_check(reference: "ReferenceLapMeta | None") -> str:
    """Spoken on sim connect — always, so the audio path is confirmed even
    when no reference exists (that was the silent case). For testing, any
    object with a `.lap_time: float` attribute is accepted (no runtime
    isinstance check is performed)."""
    if reference is None:
        return (
            "Radio check, reading you. No reference for this combo — "
            "I'll set a baseline from your first lap."
        )
    return (
        "Radio check, reading you. Reference lap "
        f"{_speech_lap_time(reference.lap_time)}, loaded. Coaching from lap one."
    )


def format_lap_speech(
    lap_time: float,
    total_delta: float,
    diagnoses: list[RegionDiagnosis],
    *,
    is_baseline: bool = False,
    prev_flagged: set[str] | None = None,
    improved: bool = False,
) -> tuple[str, set[str]]:
    """The spoken lap summary and the set of corner labels flagged this lap.

    Voice gets the headline only: delta sentence + the top region's top
    nudge. A confirmation ("that's it, keep that") is appended when a
    corner flagged on the previous lap produced no nudge this lap AND the
    lap improved — closing the learning loop the way a human coach does.
    Callers thread the returned flagged set into the next call's
    prev_flagged.
    """
    if is_baseline:
        return f"Baseline set. {_speech_lap_time(lap_time)}.", set()

    nudges = [
        n for n in (nudge_from_diagnosis(d) for d in diagnoses) if n is not None
    ]
    flagged = {n.corner for n in nudges}

    parts = [_speech_delta(total_delta)]
    if nudges:
        parts.append(nudges[0].speech)
    else:
        parts.append("Clean lap, nothing to flag.")

    # "Healed" = flagged last lap, no nudge this lap. That fires both when
    # the driver fixed the corner and when its region merely ranked out of
    # the top-3 because a larger loss appeared elsewhere; the `improved`
    # guard makes the false-positive case uncommon. Acceptable for a voice
    # line — a human coach makes the same call.
    if prev_flagged and improved:
        healed = sorted(prev_flagged - flagged)
        if healed:
            parts.append(f"{healed[0]} — that's it, keep that.")

    return " ".join(parts), flagged


def format_lap_block(
    lap_number: int,
    lap_time: float,
    total_delta: float,
    diagnoses: list[RegionDiagnosis],
    top_n: int = 2,
    is_baseline: bool = False,
) -> str:
    """The terminal block printed after one completed lap."""
    header = f"Lap {lap_number}  ({_fmt_lap_time(lap_time)}, {total_delta:+.1f}s)"
    if is_baseline:
        return f"{header}\n  baseline set - drive a faster lap for nudges"

    nudges = []
    for diag in diagnoses[:top_n]:
        n = nudge_from_diagnosis(diag)
        if n is not None:
            nudges.append(n)

    if not nudges:
        return f"{header}\n  clean lap - nothing to flag"

    lines = [header]
    for n in nudges:
        lines.append(f"  {n.corner} - {n.message}  ({n.detail})")
    return "\n".join(lines)


# Spoken phrasing per incident-count delta. Verb form for the asterisk
# clause; noun form for the baseline-refusal line and the watcher's dirty
# note. Unknown deltas (never observed, defensive) fall back to the
# generic noun/verb.
_ASTERISK_VERB = {1: "track limits", 2: "you lost it", 4: "contact"}
_ASTERISK_NOUN = {1: "track limits", 2: "a moment", 4: "contact"}


def incident_noun(delta: int) -> str:
    """Public noun phrase for an incident delta ('track limits', 'contact')
    — shared with the watcher's dirty note so wording stays consistent."""
    return _ASTERISK_NOUN.get(delta, "an incident")


def format_asterisk_speech(
    marks: "list[IncidentMark]", corners: list
) -> str:
    """Appended to the normal lap speech when a valid lap is dirty.

    Phrases the FIRST (earliest) mark; extra marks become '(and N more)'.
    Empty marks -> "" (clean lap, nothing to append)."""
    if not marks:
        return ""
    first = marks[0]
    phrase = _ASTERISK_VERB.get(first.delta, "an incident")
    corner = corner_name_at(corners, first.distance_m)
    extra = f" (and {len(marks) - 1} more)" if len(marks) > 1 else ""
    if corner:
        return f" — but {phrase} at {corner}{extra}, that time won't count."
    return f" — but {phrase} out there{extra}, that time won't count."


def format_dirty_baseline_speech(marks: "list[IncidentMark]") -> str:
    """Spoken instead of 'Baseline set' when the would-be baseline is dirty."""
    phrase = _ASTERISK_NOUN.get(marks[0].delta, "an incident") if marks else "an incident"
    return (
        f"That lap had {phrase} — I won't use it as the baseline. "
        "Give me a clean one."
    )


def format_discard_speech(reason: DiscardReason) -> str:
    """Brief spoken acknowledgment that a lap was thrown away, so silence is
    never ambiguous."""
    if reason is DiscardReason.PIT:
        return "In the pits — that lap won't count."
    return "Reset — scratch that lap."
