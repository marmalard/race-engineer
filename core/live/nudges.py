"""Turn a deterministic RegionDiagnosis into one terse coaching nudge.

No AI, no API key on the critical path. Each loss region yields at most
one imperative line plus the number that justifies it, chosen by salience:
a big apex-speed deficit (a lift) outranks a braking-point error, which
outranks a late throttle pickup. Thresholds are tuned during the spike so
only meaningful deltas speak.
"""

from dataclasses import dataclass

from core.coaching.debrief import RegionDiagnosis

# Salience thresholds — below these, a delta is not worth a nudge.
BRAKING_THRESHOLD_M = 8.0
MIN_SPEED_THRESHOLD_MS = 2.0
THROTTLE_THRESHOLD_M = 20.0
# Reference apex speed above this (m/s) = a fast/flat corner where the
# right coaching is "carry it flat" rather than "carry more apex speed".
# 50 m/s ≈ 180 km/h.
FLAT_CORNER_MIN_SPEED_MS = 50.0


@dataclass
class Nudge:
    """One imperative coaching line for a single corner."""

    corner: str
    message: str
    detail: str  # the justifying number, e.g. "-14 km/h" or "15m"


def _kmh(ms: float) -> float:
    return ms * 3.6


def nudge_from_diagnosis(diag: RegionDiagnosis) -> Nudge | None:
    """The single most salient nudge for this region, or None if nothing
    crosses threshold."""
    corner = diag.label

    # 1) Apex-speed deficit (a lift / over-slow) is the headline when big.
    if diag.min_speed_delta_ms <= -MIN_SPEED_THRESHOLD_MS:
        deficit_kmh = abs(_kmh(diag.min_speed_delta_ms))
        detail = f"-{deficit_kmh:.0f} km/h"
        if diag.reference_min_speed_ms >= FLAT_CORNER_MIN_SPEED_MS:
            return Nudge(corner, "carry it flat, you lifted", detail)
        return Nudge(corner, "carry more apex speed", detail)

    # 2) Braking-point error.
    if diag.braking_delta_m is not None and abs(diag.braking_delta_m) >= BRAKING_THRESHOLD_M:
        meters = abs(diag.braking_delta_m)
        if diag.braking_delta_m < 0:
            return Nudge(corner, "brake later", f"{meters:.0f}m")
        return Nudge(corner, "brake earlier", f"{meters:.0f}m")

    # 3) Late throttle pickup.
    if diag.throttle_delta_m is not None and diag.throttle_delta_m >= THROTTLE_THRESHOLD_M:
        return Nudge(corner, "back to power earlier", f"{diag.throttle_delta_m:.0f}m")

    return None


def _fmt_lap_time(seconds: float) -> str:
    mins = int(seconds // 60)
    secs = seconds % 60
    return f"{mins}:{secs:06.3f}"


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
