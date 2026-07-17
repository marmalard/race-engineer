"""Back-fill region diagnoses for recorded practice history.

Re-debriefs each recorded session's best plausible lap against the
CURRENT reference for its combo and persists the diagnoses (overwriting
any prior rows for that session — idempotent). Never promotes, never
touches sessions/laps rows, never writes to the ReferenceStore.

Measuring history against the current reference is deliberate: one
consistent yardstick per combo makes magnitude trends comparable;
reference_source/reference_lap_time on every row keep it honest.

    .venv/Scripts/python.exe scripts/backfill_diagnoses.py [--dry-run]
"""

import argparse
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
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

from core.benchmark.reference_store import ReferenceStore
from core.coaching.debrief import build_debrief
from core.track.track_db import DiagnosisContext, TrackDB
from core.watcher.processor import load_corners, parse_best_lap

TRACKS_DB = Path("data/tracks.db")
REFS_DB = Path("data/reference_laps.db")


def backfill(
    track_db: TrackDB, ref_store: ReferenceStore, dry_run: bool = False
) -> dict[str, int]:
    """One pass over all recorded sessions. Returns skip/record counters."""
    counts = {
        "recorded": 0, "skipped_race": 0, "skipped_missing": 0,
        "skipped_no_ref": 0, "skipped_no_lap": 0, "failed": 0,
    }
    for row in track_db.list_session_history():
        name = Path(row.ibt_file_path).name if row.ibt_file_path else row.session_id
        if row.session_type == "Race":
            counts["skipped_race"] += 1
            continue
        if not row.ibt_file_path or not Path(row.ibt_file_path).exists():
            counts["skipped_missing"] += 1
            print(f"skip {name}: file missing")
            continue
        try:
            parsed = parse_best_lap(Path(row.ibt_file_path))
            if parsed.best is None:
                counts["skipped_no_lap"] += 1
                print(f"skip {name}: no plausible lap")
                continue
            ref = ref_store.get(row.track_id, row.car)
            if ref is None:
                counts["skipped_no_ref"] += 1
                print(f"skip {name}: no reference for combo")
                continue
            corners = load_corners(
                track_db, row.track_id, parsed.session.track_directory,
                parsed.track_length_m,
            )
            result = build_debrief(parsed.best, ref.lap, corners)
            if not dry_run:
                track_db.record_region_diagnoses(
                    row.session_id,
                    DiagnosisContext(
                        driver_lap_number=parsed.best.lap_number,
                        driver_lap_time=parsed.best.lap_time,
                        reference_source=ref.source,
                        reference_lap_time=ref.meta.lap_time,
                        total_time_delta_s=result.total_time_delta,
                    ),
                    result.diagnoses,
                )
            counts["recorded"] += 1
            verb = "would record" if dry_run else "recorded"
            print(f"{verb} {len(result.diagnoses)} regions for {name}")
        except Exception as exc:  # noqa: BLE001 — one bad file must not stop the run
            counts["failed"] += 1
            print(f"FAILED {name}: {type(exc).__name__}: {exc}")
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be recorded without writing")
    args = ap.parse_args()
    counts = backfill(TrackDB(TRACKS_DB), ReferenceStore(REFS_DB),
                      dry_run=args.dry_run)
    print()
    print("  ".join(f"{k}={v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
