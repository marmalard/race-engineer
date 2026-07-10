"""Per-file race capture for the telemetry watcher.

Detects race IBTs and captures a (full or partial) RaceNarrative into
races.db while the source IBT still exists. Durability-first: wait a few
minutes for official results to settle, then persist a partial narrative
(the ephemeral IBT-only signals) rather than risk losing the IBT.

Like core.watcher.processor, process_race_ibt never raises — any error is
captured into the returned report so one bad file never aborts a scan.
"""

from dataclasses import dataclass
from pathlib import Path

from core.race.ingest import DEFAULT_CACHE_DIR, ingest_race
from core.race.narrative import build_narrative
from core.race.race_store import RaceStore
from core.track.lovely_seeder import seed_track_from_lovely
from core.track.models import Track, TrackType
from core.track.track_db import TrackDB

GRACE_MINUTES = 5.0  # how long to wait for official results before saving partial
RACE_RESULTS_GRACE_S = GRACE_MINUTES * 60.0


@dataclass
class RaceReport:
    """What one race IBT produced this scan; the CLI prints it, tests assert it."""

    path: Path
    subsession_id: int = 0
    track: str = ""
    car: str = ""
    start_position: int = 0
    finish_position: int = 0
    incidents: int = 0
    captured: bool = False   # narrative saved to races.db this scan
    partial: bool = False    # saved without Data API results
    deferred: bool = False   # results not ready + file young -> retry next scan
    error: str | None = None


def classify_ibt(weekend_info: dict) -> str:
    """'race' when this IBT is an official race, else 'lap'. Pure — reads the
    already-parsed WeekendInfo dict."""
    if weekend_info.get("EventType") == "Race" and weekend_info.get("SubSessionID"):
        return "race"
    return "lap"


def decide_capture(
    results_ready: bool,
    have_creds: bool,
    file_age_s: float,
    grace_s: float = RACE_RESULTS_GRACE_S,
) -> str:
    """'full' | 'partial' | 'defer'. Durability-first: wait for results only
    while the file is young and we actually have creds to fetch them."""
    if results_ready:
        return "full"
    if not have_creds:
        return "partial"
    if file_age_s >= grace_s:
        return "partial"
    return "defer"


def _load_corners(track_db: TrackDB, data) -> list:
    """Named corners for incident/place-change labeling, lazy-seeding from
    lovely-track-data. Creates the track row when missing (a race may be the
    first time this track is seen). Corner names are enhancement only — any
    failure returns an empty list and the narrative uses position fallbacks."""
    track_id = data.track_id
    if not track_id:
        return []
    try:
        if track_db.get_track(str(track_id)) is None:
            track_db.upsert_track(Track(
                track_id=str(track_id),
                name=data.track_name,
                config=None,
                length_meters=data.track_length_m,
                track_type=TrackType.ROAD,
                character=None,
            ))
        corners = track_db.get_corners(str(track_id))
        if not corners:
            seed_track_from_lovely(
                track_db, str(track_id), data.track_directory, data.track_length_m
            )
            corners = track_db.get_corners(str(track_id))
        return corners
    except Exception:  # noqa: BLE001 — corner names are enhancement only
        return []


def _record_race_history(track_db: TrackDB, path: Path, data) -> None:
    """Record a 'Race' session row (marks the IBT processed via the path-based
    dedupe set) and the player's race laps for the pace layer. NO PB promotion
    — race laps (traffic, fuel) must never become reference laps."""
    player_laps = data.driver_laps.get(data.player_cust_id, [])
    valid_times = [
        l.lap_time for l in player_laps if l.lap_time > 0 and not l.incident
    ]
    best = min(valid_times) if valid_times else None
    track_db.record_session(
        session_id=path.stem,
        track_id=str(data.track_id),
        car=data.car_name,
        session_type="Race",
        session_date=path.stem[-19:],
        best_lap_time=best,
        lap_count=len(player_laps),
        ibt_file_path=str(path),
    )
    if player_laps:
        track_db.record_laps(
            path.stem,
            [
                (l.lap_number, l.lap_time, l.lap_time > 0 and not l.incident)
                for l in player_laps
            ],
        )


def process_race_ibt(
    path: Path,
    api,
    race_store: RaceStore,
    track_db: TrackDB,
    *,
    now: float,
    file_mtime: float,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    grace_s: float = RACE_RESULTS_GRACE_S,
) -> RaceReport:
    """Capture one race IBT into races.db. Never raises."""
    report = RaceReport(path=path)
    try:
        data = ingest_race(path, api, cache_dir=cache_dir)
        report.subsession_id = data.subsession_id
        report.track = data.track_name
        report.car = data.car_name

        results_ready = len(data.results) > 0
        decision = decide_capture(
            results_ready, api is not None, now - file_mtime, grace_s
        )
        if decision == "defer":
            report.deferred = True
            return report

        corners = _load_corners(track_db, data)
        narrative = build_narrative(data, corners)
        race_store.save_race(narrative, ibt_file_path=str(path))
        _record_race_history(track_db, path, data)

        h = narrative.header
        report.start_position = h.start_position
        report.finish_position = h.finish_position
        report.incidents = h.incidents
        report.captured = True
        report.partial = not results_ready
        return report
    except Exception as exc:  # noqa: BLE001 — a bad file must never abort a scan
        report.error = f"{type(exc).__name__}: {exc}"
        return report
