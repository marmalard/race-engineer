"""Progression I/O: member rating history + weekly implied-iR compute.

The package's only networked module (the briefing-ingest precedent).
Everything degrades: API failures return empty series or warnings, never
raise to the page.
"""

from dataclasses import asdict
from datetime import date
import logging
from pathlib import Path

from core.benchmark.iracing_api import IRatingPoint, SeasonSchedule
from core.briefing.curve import MIN_BIN_N, place_on_curve
from core.briefing.ingest import harvest_field, rank_series_candidates
from core.profile.pace import build_readiness
from core.progression.models import IMPLIED_IR_MAX_SERIES, ComboImplied
from core.race.ingest import _cached_fetch
from core.track.track_db import LapRow, SessionRow

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path("data/briefing_cache")

_CHART_IRATING = 1
_CHART_SR = 3
_CATEGORY_SPORTS_CAR = 5


def fetch_rating_history(
    api,
    cust_id: int,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    today: date | None = None,
) -> tuple[list[IRatingPoint], list[IRatingPoint]]:
    """(iRating series, SR series) for the member, cached per day.

    The day stamp in the filename IS the cache policy: today's file is
    reused all day, tomorrow misses and re-fetches. Empty API responses
    are never cached (_cached_fetch rule), so a hiccup retries same-day.
    """
    stamp = (today or date.today()).isoformat()

    def _series(chart_type: int) -> list[IRatingPoint]:
        path = cache_dir / "chart_data" / f"{cust_id}_{chart_type}_{stamp}.json"
        try:
            raw = _cached_fetch(
                path,
                lambda: [
                    asdict(p)
                    for p in api.get_member_chart_data(
                        cust_id,
                        category_id=_CATEGORY_SPORTS_CAR,
                        chart_type=chart_type,
                    )
                ],
            )
        except Exception:
            logger.exception("chart_data fetch failed (type %s)", chart_type)
            return []
        return [IRatingPoint(when=p["when"], value=p["value"]) for p in raw or []]

    return _series(_CHART_IRATING), _series(_CHART_SR)


def normalize_sr(points: list[IRatingPoint]) -> list[tuple[str, float]]:
    """SR chart values arrive x100 (351 = 3.51) — scale for display."""
    if not points:
        return []
    # iRacing SR values are >= 100 for any licensed driver; all <= 10 means already decimal
    scale = 100.0 if max(p.value for p in points) > 10 else 1.0
    return [(p.when, p.value / scale) for p in points]


def compute_week_implied_ir(
    api,
    seasons: list[SeasonSchedule],
    sessions: list[SessionRow],
    laps: dict[str, list[LapRow]],
    cache_dir: Path = DEFAULT_CACHE_DIR,
    max_series: int = IMPLIED_IR_MAX_SERIES,
) -> tuple[list[ComboImplied], list[str]]:
    """Place every qualifying practice combo on this week's field curves.

    A combo qualifies when its track is run by a current-week series the
    user has practiced at (rank_series_candidates order = practice depth)
    and it has a practice best. Placement math stays raw (locked rule).
    Curve honesty: no bins or < MIN_BIN_N total points -> skip + warning.
    The curve is series-scoped, not car-filtered — the same approximation
    the briefing page ships; series_name on the row is the honesty label.
    """
    warnings: list[str] = []
    candidates = [
        c for c in rank_series_candidates(seasons, sessions)
        if c.practice_sessions > 0
    ][:max_series]
    if not candidates:
        return [], ["No current-week series at a track you've practiced."]

    seasons_by_id = {s.season_id: s for s in seasons}
    readiness = build_readiness(sessions, laps)
    rows: list[ComboImplied] = []
    placed: set[tuple[str, str]] = set()

    for cand in candidates:
        combos = [
            r for r in readiness
            if r.track_id == str(cand.track_id)
            and r.best_lap is not None
            and (r.track_id, r.car) not in placed
        ]
        if not combos:
            continue
        season = seasons_by_id.get(cand.season_id)
        try:
            curve, _stats = harvest_field(
                api, cand.season_id, cand.race_week, cache_dir,
                season_year=season.season_year if season else None,
                season_quarter=season.season_quarter if season else None,
            )
        except Exception as exc:
            warnings.append(f"{cand.series_name}: field harvest failed ({exc})")
            continue
        if not curve.bins or len(curve.points) < MIN_BIN_N:
            warnings.append(
                f"{cand.series_name} at {cand.track_name}: field sample too "
                f"thin to place you honestly."
            )
            continue
        for r in combos:
            placement = place_on_curve(curve, r.best_lap, None)
            if placement.implied_ir_lo is None or placement.implied_ir_hi is None:
                continue
            rows.append(ComboImplied(
                track_id=r.track_id, track_name=r.track_name, car=r.car,
                series_name=cand.series_name, lap_s=r.best_lap,
                implied_lo=placement.implied_ir_lo,
                implied_hi=placement.implied_ir_hi,
                weight=float(r.valid_laps),
            ))
            placed.add((r.track_id, r.car))
    return rows, warnings
