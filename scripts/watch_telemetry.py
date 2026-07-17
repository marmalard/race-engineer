"""Telemetry watcher — Stage 3.

Scan the iRacing telemetry folder for new IBT files; for each one:
record session/lap history, auto-promote a personal best into the
ReferenceStore, and print a debrief of the session's best lap.

    .venv/Scripts/python.exe scripts/watch_telemetry.py            # scan once
    .venv/Scripts/python.exe scripts/watch_telemetry.py --watch    # keep polling

All real logic lives in tested modules under core/watcher/; this file
only does argv, folder listing, and printing.
"""

import argparse
import os
import sys
import time
from pathlib import Path

# Ensure project root on path when run as a script.
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Detached (ManagedProcess) stdout is a cp1252 file on Windows; make report
# printing encoding-proof so one exotic char can't kill the daemon again.
# line_buffering keeps the Toolbox log tail fresh (file stdout is otherwise
# block-buffered and lags by kilobytes).
if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(
        encoding="utf-8", errors="replace", line_buffering=True
    )

# Load .env ourselves: only Toolbox-spawned instances inherit Streamlit's
# dotenv-loaded env. Any other spawn (launcher, terminal, scheduler) was
# silently running credential-less and capturing races PARTIAL (2026-07-14).
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from core.benchmark.reference_store import ReferenceStore  # noqa: E402
from core.race.race_store import RaceStore  # noqa: E402
from core.telemetry.ibt_parser import IBTParser  # noqa: E402
from core.track.track_db import TrackDB  # noqa: E402
from core.watcher.processor import SessionReport, process_ibt  # noqa: E402
from core.watcher.race_processor import (  # noqa: E402
    RaceReport,
    classify_ibt,
    process_race_ibt,
)
from core.watcher.scanner import IbtCandidate, find_new_ibts  # noqa: E402

TELEMETRY_DIR = Path(r"C:\Users\antho\Documents\iRacing\telemetry")
DB_PATH = Path("data/tracks.db")
REFERENCE_DB = Path("data/reference_laps.db")
RACES_DB = Path("data/races.db")
POLL_SECONDS = 30.0


def _gather_candidates(folder: Path) -> "list[IbtCandidate] | None":
    """(path, mtime) for every .ibt in the folder; None if folder missing."""
    if not folder.is_dir():
        return None
    return [
        IbtCandidate(path=p, mtime=p.stat().st_mtime)
        for p in folder.glob("*.ibt")
    ]


def _format_report(r: SessionReport) -> str:
    """One printable block per processed file."""
    name = r.path.name
    if r.error is not None:
        return f"FAILED {name}: {r.error} (will retry next scan)"
    lines = [
        f"{name}",
        f"  {r.track} - {r.car}: "
        f"{r.valid_laps}/{r.laps_found} valid laps"
        + (
            f", best {int(r.best_lap_time // 60)}:"
            f"{r.best_lap_time % 60:06.3f}"
            if r.best_lap_time is not None else ", no valid laps"
        ),
    ]
    if r.promoted:
        lines.append("  PB promoted to ReferenceStore")
    if r.diagnoses_recorded:
        lines.append(f"  {r.diagnoses_recorded} region diagnoses recorded")
    if r.dirty_note:
        lines.append(f"  NOTE: {r.dirty_note}")
    if r.debrief_text:
        lines.append("")
        lines.append(r.debrief_text)
    return "\n".join(lines)


def _make_api():
    """LiveIRacingAPI from env creds, or None (partial-capture mode)."""
    # TODO: near-duplicate of app/pages/race_debrief.py::_make_api — extract to
    # core.benchmark.iracing_api.make_api_from_env() when a third call site appears.
    client_id = os.environ.get("IRACING_CLIENT_ID", "")
    client_secret = os.environ.get("IRACING_CLIENT_SECRET", "")
    username = os.environ.get("IRACING_USERNAME", "")
    password = os.environ.get("IRACING_PASSWORD", "")
    if not all([client_id, client_secret, username, password]):
        return None
    from core.benchmark.iracing_api import LiveIRacingAPI
    return LiveIRacingAPI(client_id, client_secret, username, password)


def _format_race_report(r: RaceReport) -> str:
    """One printable block per race IBT (captured / partial / deferred / failed)."""
    name = r.path.name
    if r.error is not None:
        return f"FAILED {name}: {r.error} (will retry next scan)"
    if r.non_race_segment:
        return (f"{name}\n  Race-server chunk ({r.non_race_segment}) — "
                f"not the race; sending to the lap path "
                f"(subsession {r.subsession_id})")
    if r.deferred:
        return (f"{name}\n  Race {r.track} — results not ready, "
                f"will retry (subsession {r.subsession_id})")
    tag = " (partial — no results yet)" if r.partial else ""
    # ASCII arrow: U+2192 is not encodable under the detached process's
    # cp1252 stdout and killed the daemon on 2026-07-12 (em-dashes are
    # cp1252-safe; the arrow is not).
    return (f"{name}\n  Race captured{tag}: {r.track}, {r.car}, "
            f"P{r.start_position}->P{r.finish_position} "
            f"(subsession {r.subsession_id})")


def _process_candidate(cand, api, track_db, ref_store, race_store, now) -> str:
    """Route one candidate to the race or lap processor; return a print block."""
    try:
        session = IBTParser().parse_session_only(cand.path)
        weekend = (session.raw or {}).get("WeekendInfo", {}) or {}
    except Exception as exc:  # noqa: BLE001 — unreadable/half-written file, retry
        return (f"FAILED {cand.path.name}: {type(exc).__name__}: {exc} "
                "(will retry next scan)")
    if classify_ibt(weekend) == "race":
        race_report = process_race_ibt(
            cand.path, api, race_store, track_db,
            now=now, file_mtime=cand.mtime,
        )
        if not race_report.non_race_segment:
            return _format_race_report(race_report)
        # Pre-race chunk (practice/quali on the race server): its laps are
        # real pace data — run the normal lap pipeline under the segment's
        # true type so readiness counts them ('Race' rows are excluded).
        lap_report = process_ibt(
            cand.path, track_db, ref_store,
            session_type_override=race_report.non_race_segment,
        )
        return (_format_race_report(race_report) + "\n"
                + _format_report(lap_report))
    return _format_report(process_ibt(cand.path, track_db, ref_store))


def _scan_once(folder: Path, track_db, ref_store, race_store, api) -> int:
    """One pass. Returns number of files processed (0 is fine)."""
    candidates = _gather_candidates(folder)
    if candidates is None:
        print(f"Telemetry folder not found: {folder}")
        raise SystemExit(1)
    new = find_new_ibts(
        candidates, processed=track_db.processed_ibt_paths(), now=time.time(),
    )
    for cand in new:
        print(_process_candidate(cand, api, track_db, ref_store, race_store,
                                 time.time()))
        print()
    return len(new)


def main() -> None:
    args = _parse_args()
    folder = Path(args.folder)
    track_db = TrackDB(DB_PATH)
    ref_store = ReferenceStore(REFERENCE_DB)
    race_store = RaceStore(RACES_DB)
    api = _make_api()
    if api is None:
        print("No iRacing API creds — races will be captured partial "
              "(positions/results absent); practice unaffected.")
    try:
        n = _scan_once(folder, track_db, ref_store, race_store, api)
        if not args.watch:
            print(f"Processed {n} new file(s).")
            return
        print(f"Watching {folder} (every {POLL_SECONDS:.0f}s, Ctrl-C to stop)...")
        while True:
            time.sleep(POLL_SECONDS)
            # A long-running daemon must outlive one bad scan (transient DB
            # lock, half-written file, print error). SystemExit (folder gone)
            # and KeyboardInterrupt still propagate.
            try:
                _scan_once(folder, track_db, ref_store, race_store, api)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:  # noqa: BLE001 — retry next poll
                print(f"SCAN FAILED: {type(exc).__name__}: {exc} "
                      "(retrying next poll)")
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        if api is not None:
            api.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Process new IBT telemetry into history + references"
    )
    parser.add_argument("--folder", default=str(TELEMETRY_DIR),
                        help="telemetry folder to scan")
    parser.add_argument("--watch", action="store_true",
                        help="keep polling instead of exiting after one scan")
    return parser.parse_args()


if __name__ == "__main__":
    main()
