"""Annotate loss regions with corner names from the track database.

Corners are labels on the analysis, never its foundation: if no named
corner overlaps a loss region, the label degrades gracefully to a
position description rather than inventing a turn number.
"""

from core.telemetry.loss_regions import LossRegion
from core.track.models import Corner


def annotate_region(
    region: LossRegion,
    corners: list[Corner],
    track_length: float,
    tolerance_m: float = 50.0,
) -> str:
    """Human label for a loss region: corner name(s) or position fallback.

    Args:
        region: The loss region to annotate.
        corners: Named corners from the track database.
        track_length: Full track length in meters (reserved for future
            wrap-around handling at the start/finish line).
        tolerance_m: Used only when no corner strictly overlaps the region:
            a corner whose entry lies up to this many meters AHEAD of the
            region's end is matched (braking zone attribution). Strict
            overlaps always win, so a region inside one corner is never
            also attributed to the next corner just because it is close.

    Returns:
        Corner name, slash-joined names for multi-corner spans, or a
        position string like "~4.4 km from start/finish" when no named
        corner overlaps.
    """
    def _strictly_overlaps(c: Corner) -> bool:
        return (
            c.distance_start_meters <= region.distance_end
            and c.distance_end_meters >= region.distance_start
        )

    def _approaching(c: Corner) -> bool:
        """Braking zone that ends just before the corner entry."""
        return (
            region.distance_end < c.distance_start_meters
            and c.distance_start_meters - region.distance_end <= tolerance_m
        )

    strict_matches = [c for c in corners if c.name and _strictly_overlaps(c)]
    if strict_matches:
        overlapping = strict_matches
    else:
        overlapping = [c for c in corners if c.name and _approaching(c)]
    if overlapping:
        overlapping.sort(key=lambda c: c.distance_start_meters)
        return " / ".join(dict.fromkeys(c.name for c in overlapping))

    km = region.distance_start / 1000.0
    return f"~{km:.1f} km from start/finish"
