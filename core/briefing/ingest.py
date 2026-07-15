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
from statistics import median as _median

from core.benchmark.iracing_api import SeasonSchedule
from core.briefing.curve import build_curve, place_on_curve
from core.briefing.models import (
    BriefingData,
    ComboPrep,
    FieldStats,
    PaceCurve,
    RaceFormat,
    RaceSlot,
)
from core.briefing.slots import infer_window, upcoming_slots
from core.profile.pace import build_readiness
from core.race.ingest import _cached_fetch, parse_results
from core.track.track_db import LapRow, SessionRow

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
    license_group: int = 0  # 0 = unknown, never filtered out


def max_license_group(member_info: dict) -> int | None:
    """Highest license group (1=Rookie..5=A/Pro) from a /data/member/info
    payload, tolerant of dict- or list-shaped licenses. None when the
    shape is unrecognized - callers must then show ALL series rather
    than guess (a wrong filter hides races; no filter just adds scroll).
    """
    licenses = member_info.get("licenses")
    if isinstance(licenses, dict):
        entries = list(licenses.values())
    elif isinstance(licenses, list):
        entries = licenses
    else:
        return None
    groups: list[int] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        g = e.get("group_id") or e.get("license_group")
        if g is None and isinstance(e.get("license_level"), int):
            g = (e["license_level"] + 3) // 4  # levels 1-4 = group 1, etc.
        if isinstance(g, int) and g > 0:
            groups.append(g)
    return max(groups) if groups else None


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
            license_group=season.license_group,
        ))
    out.sort(key=lambda c: (-c.practice_sessions, c.series_name))
    return out


def harvest_field(
    api,
    season_id: int,
    race_week: int,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    season_year: int | None = None,
    season_quarter: int | None = None,
) -> tuple[PaceCurve, FieldStats | None]:
    """Fetch the week's subsessions -> (iR, best_lap) points + field norms.

    The search call is never disk-cached (the week is still growing);
    per-subsession results are cached forever (results are immutable).

    search_series REQUIRES season_year+season_quarter — season_id alone is
    a 400, and the server ignores season_id as a filter (both verified
    live 2026-07-15: the year+quarter response is the whole week across
    all series), so rows are filtered to this season client-side.
    """
    rows = api.search_series_results(
        season_id=season_id,
        race_week_num=race_week,
        season_year=season_year,
        season_quarter=season_quarter,
    )
    rows = [r for r in rows if r.season_id == season_id]
    rows = sorted(rows, key=lambda r: r.start_time)
    capped = len(rows) > HARVEST_CAP
    if capped:
        logger.info(
            "Harvest capped: %d of %d subsessions used", HARVEST_CAP, len(rows)
        )
    used = rows[-HARVEST_CAP:]

    points: list[tuple[int, float]] = []
    week_dir = cache_dir / str(season_id) / str(race_week)
    for row in used:
        payload = _cached_fetch(
            week_dir / f"{row.subsession_id}.json",
            lambda row=row: api.get_subsession_results(row.subsession_id),
        )
        if not payload:
            continue
        for r in parse_results(payload):
            if r.oldi_rating > 0 and r.best_lap_time > 0:
                points.append((r.oldi_rating, r.best_lap_time))

    curve = build_curve(points, subsessions_used=len(used), capped=capped)
    if not used:
        return curve, None
    sofs = sorted(r.strength_of_field for r in used)
    splits: dict[int, int] = {}
    for r in used:
        splits[r.session_id] = splits.get(r.session_id, 0) + 1
    stats = FieldStats(
        sof_p25=sofs[len(sofs) // 4],
        sof_median=int(_median(sofs)),
        sof_p75=sofs[(3 * len(sofs)) // 4],
        field_size_median=int(_median(sorted(r.num_drivers for r in used))),
        splits_median=int(_median(sorted(splits.values()))),  # int-truncates: 1.5 splits -> 1 by design
    )
    return curve, stats


def build_briefing(
    api,
    season: SeasonSchedule,
    sessions: list[SessionRow],
    laps: dict[str, list[LapRow]],
    car: str,
    user_irating: int | None,
    now_utc: datetime,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> BriefingData:
    """Assemble the full deterministic briefing. Never raises: every
    failure downgrades to a warning + missing section (spec degradation
    ladder)."""
    week = next(
        (w for w in season.weeks if w.race_week_num == season.race_week),
        None,
    )
    if week is None:
        raise ValueError(
            f"season {season.season_id} has no schedule for week "
            f"{season.race_week}"
        )
    data = BriefingData(
        series_name=season.series_name,
        season_id=season.season_id,
        race_week=season.race_week,
        fmt=RaceFormat(
            track_name=week.track_name,
            config_name=week.config_name,
            race_time_limit=week.race_time_limit,
            race_lap_limit=week.race_lap_limit,
            standing_start=week.standing_start,
            max_pct_fuel_fill=week.max_pct_fuel_fill,
        ),
        user_irating=user_irating,
    )

    try:
        data.curve, data.field_stats = harvest_field(
            api,
            season.season_id,
            season.race_week,
            cache_dir,
            season_year=season.season_year or None,
            season_quarter=season.season_quarter or None,
        )
    except Exception:
        logger.warning("Field harvest failed", exc_info=True)
        data.warnings.append(
            "Couldn't fetch this week's field data — briefing is "
            "format-and-history only."
        )

    # Prep ledger + placement from the user's own practice at this combo.
    combo = next(
        (
            c
            for c in build_readiness(sessions, laps)
            if c.track_id == str(week.track_id) and c.car == car
        ),
        None,
    )
    if combo is not None:
        data.prep = ComboPrep(
            car=car,
            sessions=combo.sessions,
            representative_laps=combo.valid_laps,
            best_lap_s=combo.best_lap,
            trend_s=combo.pb_trend_s,
        )
        if data.curve is not None and combo.best_lap is not None:
            data.placement = place_on_curve(
                data.curve, combo.best_lap, user_irating
            )

    window = infer_window([s.session_date for s in sessions])
    for slot in upcoming_slots(
        week.race_time_descriptors, now_utc, count=4
    ):
        local_hour = slot.astimezone().hour
        fits = window is not None and window[0] <= local_hour <= window[1]
        data.slots.append(
            RaceSlot(start_utc=slot.isoformat(), fits_window=fits)
        )
    return data
