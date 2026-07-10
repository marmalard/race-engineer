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
