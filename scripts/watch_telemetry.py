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
import sys
import time
from pathlib import Path

# Ensure project root on path when run as a script.
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.benchmark.reference_store import ReferenceStore  # noqa: E402
from core.track.track_db import TrackDB  # noqa: E402
from core.watcher.processor import SessionReport, process_ibt  # noqa: E402
from core.watcher.scanner import IbtCandidate, find_new_ibts  # noqa: E402

TELEMETRY_DIR = Path(r"C:\Users\antho\Documents\iRacing\telemetry")
DB_PATH = Path("data/tracks.db")
REFERENCE_DB = Path("data/reference_laps.db")
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
    if r.error is not None:
        return f"FAILED {r.path.name}: {r.error} (will retry next scan)"
    lines = [
        f"{r.path.name}",
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
    if r.debrief_text:
        lines.append("")
        lines.append(r.debrief_text)
    return "\n".join(lines)


def _scan_once(folder: Path) -> int:
    """One pass. Returns number of files processed (0 is fine)."""
    candidates = _gather_candidates(folder)
    if candidates is None:
        print(f"Telemetry folder not found: {folder}")
        raise SystemExit(1)
    track_db = TrackDB(DB_PATH)
    ref_store = ReferenceStore(REFERENCE_DB)
    new = find_new_ibts(
        candidates, processed=track_db.processed_ibt_paths(),
        now=time.time(),
    )
    for cand in new:
        print(_format_report(process_ibt(cand.path, track_db, ref_store)))
        print()
    return len(new)


def main() -> None:
    args = _parse_args()
    folder = Path(args.folder)
    n = _scan_once(folder)
    if not args.watch:
        print(f"Processed {n} new file(s).")
        return
    print(f"Watching {folder} (every {POLL_SECONDS:.0f}s, Ctrl-C to stop)...")
    try:
        while True:
            time.sleep(POLL_SECONDS)
            _scan_once(folder)
    except KeyboardInterrupt:
        print("\nStopped.")


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
