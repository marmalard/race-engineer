"""Race ingestion: IBT + session YAML + Data API -> RaceData.

Raw API responses are cached to data/race_cache/{subsession_id}/ so a
race is fetched once; cached files double as recorded test fixtures.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

from core.race.models import (
    DriverLap,
    LapChartRow,
    RaceData,
    ResultRow,
    RosterEntry,
)
from core.race.narrative import select_key_rivals
from core.telemetry.ibt_parser import IBTParser

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path("data/race_cache")

# On grids this size or smaller, fetch lap data for every classified driver so
# pace_ranking covers the full field rather than just the player's immediate rivals.
# Above this limit, cap at player + select_key_rivals to bound API calls.
FULL_FIELD_MAX = 16

RACE_CHANNELS = IBTParser.CORE_CHANNELS + [
    "PlayerCarPosition",
    "PlayerCarClassPosition",
    "SessionFlags",
    "FuelLevel",
    "SessionState",
]


class RaceIngestError(Exception):
    """Raised when a source cannot be ingested as an official race."""


def select_race_simsession(session_results: list[dict]) -> dict:
    """Pick the race simsession from a results payload.

    Prefers simsession_number == 0 (the race in official events);
    falls back to a type-name match for odd formats.
    """
    for entry in session_results:
        if entry.get("simsession_number") == 0:
            return entry
    for entry in session_results:
        name = (entry.get("simsession_type_name") or "").lower()
        if "race" in name:
            return entry
    raise RaceIngestError(
        "No race simsession in results payload "
        f"(found: {[e.get('simsession_type_name') for e in session_results]})"
    )


def _parse_api_lap_time(value) -> float:
    """API lap times are 1/10000s; <= 0 means no valid time.

    Results/lap_data endpoint times are ALWAYS 1/10000s — unlike the
    recent-races endpoint used in iracing_api._parse_lap_time() which
    returns a mixed format (seconds for low values, 1/10000s for high).
    """
    if not isinstance(value, (int, float)) or value <= 0:
        return -1.0
    return value / 10000.0


def parse_results(raw: dict) -> list[ResultRow]:
    """Official race results -> ResultRow list (positions -> 1-based)."""
    race = select_race_simsession(raw.get("session_results", []))
    rows: list[ResultRow] = []
    for r in race.get("results", []):
        rows.append(
            ResultRow(
                cust_id=r.get("cust_id", 0),
                display_name=r.get("display_name", ""),
                finish_position=r.get("finish_position", -1) + 1,
                starting_position=r.get("starting_position", -1) + 1,
                laps_complete=r.get("laps_complete", 0),
                incidents=r.get("incidents", 0),
                oldi_rating=r.get("oldi_rating", 0),
                newi_rating=r.get("newi_rating", 0),
                best_lap_time=_parse_api_lap_time(r.get("best_lap_time")),
            )
        )
    return rows


def parse_lap_chart_rows(raw: list[dict]) -> list[LapChartRow]:
    """Lap chart rows -> LapChartRow list. Lap 0 (grid) is dropped."""
    rows: list[LapChartRow] = []
    for r in raw:
        cust_id = r.get("cust_id") or r.get("group_id") or 0
        lap = r.get("lap_number", 0)
        if lap < 1:
            continue
        rows.append(
            LapChartRow(
                cust_id=cust_id,
                lap_number=lap,
                position=r.get("lap_position", 0),
            )
        )
    return rows


def parse_lap_data_rows(raw: list[dict], cust_id: int) -> list[DriverLap]:
    """Per-driver lap data rows -> DriverLap list."""
    return [
        DriverLap(
            cust_id=cust_id,
            lap_number=r.get("lap_number", 0),
            lap_time=_parse_api_lap_time(r.get("lap_time")),
            lap_events=list(r.get("lap_events", []) or []),
            incident=bool(r.get("incident", False)),
        )
        for r in raw
        if r.get("lap_number", 0) >= 1
    ]


def _cached_fetch(cache_path: Path, fetch: Callable[[], dict | list]):
    """Serve from disk cache, else fetch and cache.

    The cache file is written atomically (write to .tmp sibling, then
    replace) so a crash mid-write never leaves a truncated file that
    poisons the cache permanently.  Corrupt existing files
    (JSONDecodeError) are treated as a cache miss: re-fetch and overwrite.
    """
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning(
                "Corrupt cache file %s — treating as cache miss and re-fetching",
                cache_path,
            )
    data = fetch()
    # A falsy result means the API had nothing yet (e.g. official results not
    # posted). Do NOT cache it — a persisted empty would poison every later
    # retry, stranding the race as partial forever. Return it uncached so the
    # next attempt re-fetches. A legitimately-empty payload simply re-fetches
    # next time — negligible cost, never incorrect.
    if not data:
        return data
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data), encoding="utf-8")
    tmp_path.replace(cache_path)
    return data


def load_race_ibt(source: Path | bytes) -> tuple:
    """Parse a race IBT with extended channels; validate it IS a race.

    Returns (IBTFile, meta dict). Raises RaceIngestError for non-race
    sessions or missing SubSessionID.
    """
    parser = IBTParser()
    ibt = parser.parse(source, channels=RACE_CHANNELS)

    raw = ibt.session.raw or {}
    weekend = raw.get("WeekendInfo", {}) or {}
    subsession_id = weekend.get("SubSessionID", 0)
    if weekend.get("EventType") != "Race" or not subsession_id:
        raise RaceIngestError(
            "This IBT is not an official race session "
            f"(EventType={weekend.get('EventType')!r}, "
            f"SubSessionID={subsession_id!r})."
        )

    driver_info = raw.get("DriverInfo", {}) or {}
    player_car_idx = driver_info.get("DriverCarIdx", -1)
    player_cust_id = driver_info.get("DriverUserID", 0)

    roster = []
    for d in driver_info.get("Drivers", []) or []:
        if d.get("IsSpectator") or d.get("CarIsPaceCar"):
            continue
        roster.append(
            RosterEntry(
                car_idx=d.get("CarIdx", -1),
                cust_id=d.get("UserID", 0),
                display_name=d.get("UserName", ""),
                car_number=str(d.get("CarNumber", "")),
                irating=d.get("IRating", 0),
                license_string=d.get("LicString", ""),
                car_name=d.get("CarScreenName", ""),
            )
        )

    iratings = [r.irating for r in roster if r.irating > 0]

    meta = {
        "subsession_id": int(subsession_id),
        "player_cust_id": int(player_cust_id),
        "player_car_idx": int(player_car_idx),
        "driver_name": ibt.session.driver_name,
        "track_id": ibt.session.track_id,
        "track_name": ibt.session.track_name,
        "track_config": weekend.get("TrackConfigName", "") or "",
        "track_directory": ibt.session.track_directory,
        "track_length_m": ibt.session.track_length_km * 1000.0,
        "car_name": ibt.session.car_name,
        "series_name": "",  # filled from results when available
        "session_date": "",  # filled from results when available
        "sof": int(sum(iratings) / len(iratings)) if iratings else 0,
        "roster": roster,
    }
    return ibt, meta


def ingest_race(
    source: Path | bytes,
    api,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    ibt_path_for_record: str = "",
) -> RaceData:
    """Full ingestion: IBT + YAML + API (cached) -> RaceData.

    api is a LiveIRacingAPI/StubIRacingAPI or None. API failures degrade
    to a partial RaceData (results/lap_chart/driver_laps empty) with a
    warning — the page renders what the telemetry alone supports.
    """
    ibt, meta = load_race_ibt(source)
    subsession_id = meta["subsession_id"]
    sub_cache = cache_dir / str(subsession_id)

    results: list[ResultRow] = []
    lap_chart: list[LapChartRow] = []
    driver_laps: dict[int, list[DriverLap]] = {}

    if api is not None:
        try:
            raw_results = _cached_fetch(
                sub_cache / "results.json",
                lambda: api.get_subsession_results(subsession_id),
            )
            if raw_results:
                results = parse_results(raw_results)
                meta["series_name"] = raw_results.get("series_name", "")
                meta["session_date"] = raw_results.get("start_time", "")

                race_sim = select_race_simsession(
                    raw_results.get("session_results", [])
                )
                simsession = race_sim.get("simsession_number", 0)

                raw_chart = _cached_fetch(
                    sub_cache / "lap_chart.json",
                    lambda: api.get_lap_chart_data(subsession_id, simsession),
                )
                lap_chart = parse_lap_chart_rows(raw_chart)

                # Lap data: full field on small grids (accurate pace ranking);
                # player + key rivals only on large fields (bounds API calls).
                # Rival selection needs results + chart, both now loaded.
                if len(results) <= FULL_FIELD_MAX:
                    targets = [r.cust_id for r in results]
                else:
                    targets = [meta["player_cust_id"]] + select_key_rivals(
                        results, lap_chart, meta["player_cust_id"]
                    )
                for cust_id in targets:
                    try:
                        raw_laps = _cached_fetch(
                            sub_cache / f"lap_data_{cust_id}.json",
                            lambda cid=cust_id: api.get_lap_data(
                                subsession_id, simsession, cid
                            ),
                        )
                        laps = parse_lap_data_rows(raw_laps, cust_id)
                        if laps:
                            driver_laps[cust_id] = laps
                    except Exception as exc:  # noqa: BLE001 — one driver must never nuke the rest
                        logger.warning(
                            "Lap data fetch failed for cust_id %s in subsession %s: %s"
                            " — skipping",
                            cust_id,
                            subsession_id,
                            exc,
                        )
        except RaceIngestError:
            raise
        except Exception as exc:  # noqa: BLE001 — degrade, never crash
            logger.warning(
                "Data API fetch failed for subsession %s: %s — "
                "building partial narrative from telemetry only",
                subsession_id,
                exc,
            )
            results, lap_chart, driver_laps = [], [], {}

    return RaceData(
        subsession_id=subsession_id,
        player_cust_id=meta["player_cust_id"],
        player_car_idx=meta["player_car_idx"],
        driver_name=meta["driver_name"],
        track_id=meta["track_id"],
        track_name=meta["track_name"],
        track_config=meta["track_config"],
        track_directory=meta["track_directory"],
        track_length_m=meta["track_length_m"],
        car_name=meta["car_name"],
        series_name=meta["series_name"],
        session_date=meta["session_date"],
        sof=meta["sof"],
        player_telemetry=ibt.telemetry,
        roster=meta["roster"],
        results=results,
        lap_chart=lap_chart,
        driver_laps=driver_laps,
    )
