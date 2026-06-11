"""Scouting report generation orchestrator.

Coordinates between the synthesizer (Claude API), iRacing Data API,
track database, and driver profile to produce a complete scouting report.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from core.coaching.synthesizer import ScoutingReport, Synthesizer

logger = logging.getLogger(__name__)


@dataclass
class PaceContext:
    """Aggregated pace context from the driver's own race history."""

    matching_races: list[dict] = field(default_factory=list)
    driver_best_lap: float | None = None
    driver_best_qual: float | None = None
    avg_finish_position: float | None = None
    avg_sof: float | None = None
    race_count: int = 0


def _try_fetch_pace_context(
    car_name: str,
    track_name: str,
) -> PaceContext | None:
    """Attempt to fetch pace context from iRacing API.

    Returns None on any failure (missing creds, API error, etc.).
    Scouting reports must work without this data.
    """
    client_id = os.environ.get("IRACING_CLIENT_ID", "")
    client_secret = os.environ.get("IRACING_CLIENT_SECRET", "")
    username = os.environ.get("IRACING_USERNAME", "")
    password = os.environ.get("IRACING_PASSWORD", "")

    if not all([client_id, client_secret, username, password]):
        logger.debug("iRacing API credentials not configured, skipping pace context")
        return None

    try:
        from core.benchmark.iracing_api import LiveIRacingAPI, RecentRace

        with LiveIRacingAPI(client_id, client_secret, username, password) as api:
            recent = api.get_member_recent_races()

        matches = _filter_races(recent, car_name, track_name)

        if not matches:
            logger.info("No recent races matching %s at %s", car_name, track_name)
            return PaceContext()

        return _build_pace_context(matches)

    except Exception as e:
        logger.warning("Failed to fetch pace context from iRacing API: %s", e)
        return None


def _filter_races(
    races: list, car_name: str, track_name: str
) -> list:
    """Filter recent races by car and track name using substring matching.

    Tries car+track match first, falls back to track-only.
    """
    car_lower = car_name.lower()
    track_lower = track_name.lower()

    # Try car + track match
    both = [
        r for r in races
        if _name_matches(r.track_name, track_lower)
        and _name_matches(r.car_name, car_lower)
    ]
    if both:
        return both

    # Fall back to track-only match
    track_only = [
        r for r in races
        if _name_matches(r.track_name, track_lower)
    ]
    return track_only


def _name_matches(api_name: str, query: str) -> bool:
    """Case-insensitive bidirectional substring match."""
    api_lower = api_name.lower()
    return query in api_lower or api_lower in query


def _fmt_time(seconds: float) -> str:
    """Format seconds as M:SS.mmm."""
    mins = int(seconds // 60)
    secs = seconds % 60
    return f"{mins}:{secs:06.3f}"


def _build_pace_context(matches: list) -> PaceContext:
    """Build a PaceContext from matching race results."""
    valid_laps = [r.best_lap_time for r in matches if r.best_lap_time > 0]
    valid_quals = [r.best_qual_lap_time for r in matches if r.best_qual_lap_time > 0]
    valid_finishes = [r.finish_position for r in matches if r.finish_position > 0]
    valid_sofs = [r.strength_of_field for r in matches if r.strength_of_field > 0]

    race_dicts = []
    for r in matches:
        race_dicts.append({
            "series": r.series_name,
            "track": r.track_name,
            "car": r.car_name,
            "best_lap": _fmt_time(r.best_lap_time) if r.best_lap_time > 0 else "N/A",
            "best_qual": _fmt_time(r.best_qual_lap_time) if r.best_qual_lap_time > 0 else "N/A",
            "finish": f"P{r.finish_position}" if r.finish_position > 0 else "N/A",
            "sof": r.strength_of_field,
            "date": r.session_start_time,
        })

    return PaceContext(
        matching_races=race_dicts,
        driver_best_lap=min(valid_laps) if valid_laps else None,
        driver_best_qual=min(valid_quals) if valid_quals else None,
        avg_finish_position=(
            sum(valid_finishes) / len(valid_finishes) if valid_finishes else None
        ),
        avg_sof=sum(valid_sofs) / len(valid_sofs) if valid_sofs else None,
        race_count=len(matches),
    )


def generate_scouting_report(
    synthesizer: Synthesizer,
    car_name: str,
    track_name: str,
    track_config: str | None = None,
    irating: int | None = None,
) -> ScoutingReport:
    """Generate a scouting report with optional pace context from iRacing API."""
    pace_context = _try_fetch_pace_context(car_name, track_name)

    return synthesizer.generate_scouting_report(
        car_name=car_name,
        track_name=track_name,
        track_config=track_config,
        irating=irating,
        pace_context=pace_context,
    )
