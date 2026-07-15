"""Briefing ingestion: Data API harvest + disk cache + tracks.db reads.

The only I/O module in core/briefing (mirrors core/race/ingest.py's role).
Raw subsession results are cached to data/briefing_cache/{season}/{week}/;
cached files double as recorded test fixtures.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from core.benchmark.iracing_api import SeasonSchedule
from core.track.track_db import SessionRow

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path("data/briefing_cache")
HARVEST_CAP = 30  # newest subsessions fetched per series-week


@dataclass
class SeriesCandidate:
    """One pickable series for the current week, ranked by practice depth."""

    season_id: int
    series_name: str
    season_name: str
    race_week: int
    track_id: int
    track_name: str
    practice_sessions: int


def rank_series_candidates(
    seasons: list[SeasonSchedule],
    sessions: list[SessionRow],
) -> list[SeriesCandidate]:
    """Rank this week's series by the user's practice depth at each track.

    tracks.db track_id is TEXT; RaceWeek.track_id is int — compared as str.
    Seasons whose current race_week has no schedule entry are skipped.
    """
    by_track: dict[str, int] = {}
    for s in sessions:
        if s.session_type != "Race":
            by_track[s.track_id] = by_track.get(s.track_id, 0) + 1

    out: list[SeriesCandidate] = []
    for season in seasons:
        week = next(
            (w for w in season.weeks if w.race_week_num == season.race_week),
            None,
        )
        if week is None:
            continue
        out.append(SeriesCandidate(
            season_id=season.season_id,
            series_name=season.series_name,
            season_name=season.season_name,
            race_week=season.race_week,
            track_id=week.track_id,
            track_name=week.track_name,
            practice_sessions=by_track.get(str(week.track_id), 0),
        ))
    out.sort(key=lambda c: (-c.practice_sessions, c.series_name))
    return out
