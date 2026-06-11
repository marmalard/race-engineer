"""Seed corner names from lovely-track-data (Lovely-Sim-Racing on GitHub).

Covers ~185 iRacing track configs (vs ~30 from Crew Chief) with named
corner ranges as track-position fractions (0-1). License: CC BY-NC-SA 4.0
(non-commercial, attribution) — fine for this personal tool.

Track slugs align with iRacing's track directory naming, which we already
extract from IBT session YAML: "spa 2024 up" -> "spa-2024-up".

Real JSON shape (verified against live repo):
  {
    "name": "...",
    "trackId": "...",
    "country": "XX",
    "length": <meters int>,
    "pitentry": <float>,
    "pitexit": <float>,
    "turn": [{"start": <0-1>, "end": <0-1>, "name": "..."}, ...],
    "straight": [{"start": ..., "marker": ..., "end": ..., "name": "..."}, ...]
  }

The key for corners is "turn" (not "turns"). Straights are in a separate
"straight" list and are intentionally ignored here.
"""

import logging

import requests

from core.track.models import Corner
from core.track.track_db import TrackDB

logger = logging.getLogger(__name__)

RAW_BASE = (
    "https://raw.githubusercontent.com/Lovely-Sim-Racing/"
    "lovely-track-data/main/data/iracing"
)


def lovely_track_slug(ibt_track_name: str) -> str:
    """Convert IBT session YAML track name to a lovely-track-data slug.

    iRacing track names in session YAML use spaces; lovely-track-data uses
    hyphens and the same lowercase tokens.

    Examples:
        "spa 2024 up"          -> "spa-2024-up"
        "roadamerica full"     -> "roadamerica-full"
        "monza combinedchicanes" -> "monza-combinedchicanes"
    """
    return ibt_track_name.strip().lower().replace(" ", "-")


def _fetch_lovely_json(slug: str) -> dict | None:
    """Fetch a track's JSON from lovely-track-data; None if absent or unreachable.

    Returns the raw parsed JSON dict, or None on 404 / network failure.
    Separated from parse logic so tests can patch it cleanly.
    """
    url = f"{RAW_BASE}/{slug}.json"
    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.warning("lovely-track-data fetch failed for %s: %s", slug, exc)
        return None


def parse_lovely_corners(
    data: dict, track_id: str, track_length_m: float
) -> list[Corner]:
    """Convert lovely turn entries (fractions) to Corner models (meters).

    Args:
        data: Parsed JSON from lovely-track-data (must contain "turn" list).
        track_id: iRacing numeric track ID string to stamp on each Corner.
        track_length_m: Track length in meters used to convert fractions.

    Returns:
        List of Corner objects sorted by position, numbered from 1.
        Entries missing a name, start, or end are skipped.
    """
    turns = data.get("turn", [])
    corners: list[Corner] = []
    # Sort by start position so corner_number is always positional, never
    # based on arbitrary source ordering.
    for i, turn in enumerate(
        sorted(turns, key=lambda t: t.get("start", 0.0)), start=1
    ):
        name = turn.get("name")
        if name is None or "start" not in turn or "end" not in turn:
            continue
        corners.append(
            Corner(
                corner_id=None,
                track_id=track_id,
                corner_number=i,  # positional ordering — NOT official turn number
                name=name,
                distance_start_meters=turn["start"] * track_length_m,
                distance_end_meters=turn["end"] * track_length_m,
                corner_type=None,
            )
        )
    return corners


def seed_track_from_lovely(
    db: TrackDB,
    track_id: str,
    ibt_track_name: str,
    track_length_m: float,
) -> int:
    """Fetch and upsert lovely-track-data corners for a track.

    Args:
        db: TrackDB instance to write into.
        track_id: iRacing numeric track ID string.
        ibt_track_name: Raw track name from IBT session YAML (e.g. "spa 2024 up").
        track_length_m: Track length in meters (from IBT header or track DB).

    Returns:
        Number of corners seeded.  0 means no data was available or the fetch
        failed — callers should fall back to Crew Chief seeding or heuristic
        corner detection.
    """
    data = _fetch_lovely_json(lovely_track_slug(ibt_track_name))
    if data is None:
        return 0
    corners = parse_lovely_corners(data, track_id, track_length_m)
    if not corners:
        return 0
    db.upsert_corners(track_id, corners)
    return len(corners)
