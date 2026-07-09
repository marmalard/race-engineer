"""Per-file watcher pipeline: parse -> normalize -> record -> promote -> debrief.

One IBT file in, one SessionReport out. Any exception is caught into the
report — a corrupt or half-written file must never abort a folder scan,
and a failed file is NOT recorded as processed, so it retries next scan.
"""

from dataclasses import dataclass
from pathlib import Path

from core.benchmark.reference_store import ReferenceStore
from core.coaching.debrief import build_debrief
from core.live.nudges import format_lap_block
from core.telemetry.ibt_parser import IBTParser
from core.telemetry.normalizer import Normalizer
from core.track.lovely_seeder import seed_track_from_lovely
from core.track.models import Track, TrackType
from core.track.track_db import TrackDB
from core.watcher.scanner import covers_full_lap, is_plausible_lap, should_promote


@dataclass
class SessionReport:
    """What one processed IBT produced; the CLI prints it, tests assert it."""

    path: Path
    track: str = ""
    car: str = ""
    laps_found: int = 0
    valid_laps: int = 0
    best_lap_time: float | None = None
    promoted: bool = False
    debrief_text: str | None = None
    error: str | None = None


def _load_corners(
    track_db: TrackDB,
    track_id: str,
    track_directory: str,
    track_length_m: float,
) -> list:
    """Named corners, lazy-seeding from lovely-track-data on first use.

    Mirrors the live coach's connect-time behavior: lovely-track-data
    first (slug from the directory string), silently degrading to
    whatever the DB already has.

    The real track row is always created by process_ibt before this is
    called, so we only handle corner seeding here.
    """
    if not track_id:
        return []
    corners = track_db.get_corners(track_id)
    if not corners:
        try:
            seed_track_from_lovely(
                track_db, track_id=track_id,
                ibt_track_name=track_directory,
                track_length_m=track_length_m,
            )
            corners = track_db.get_corners(track_id)
        except Exception:
            corners = []
    return corners


def process_ibt(
    path: Path, track_db: TrackDB, ref_store: ReferenceStore
) -> SessionReport:
    """Process one IBT file end-to-end. Never raises."""
    report = SessionReport(path=path)
    try:
        parser = IBTParser()
        ibt = parser.parse(path)
        session = ibt.session
        track_id = str(session.track_id)
        track_length_m = session.track_length_km * 1000.0
        report.track = session.track_name
        report.car = session.car_name

        lap_dfs = parser.get_laps(ibt)
        lap_numbers = [int(df["Lap"].iloc[0]) for df in lap_dfs]
        laps = Normalizer().normalize_session(
            lap_dfs, lap_numbers, track_length_m
        )
        report.laps_found = len(lap_dfs)
        valid = [l for l in laps if l.is_valid]
        report.valid_laps = len(valid)

        # Defense in depth before best-selection and promotion: a
        # normalizer-valid lap can still be physically impossible (towed /
        # aborted / partial laps whose recorded time covers only a fraction
        # of the track — see is_plausible_lap). Never let one become the
        # session best or a promoted PB; the ReferenceStore is the live
        # coach's ground truth.
        plausible = [
            l for l in valid
            if is_plausible_lap(l.lap_time, track_length_m)
            and covers_full_lap(
                float(l.distance[-1]) if len(l.distance) > 0 else 0.0,
                track_length_m,
            )
        ]
        best = min(plausible, key=lambda l: l.lap_time) if plausible else None
        report.best_lap_time = best.lap_time if best else None

        # Upsert the real track row BEFORE record_session so that
        # record_session's INSERT OR IGNORE sees a populated row rather
        # than writing a stub (track_id, track_id) that would obscure
        # the real name and length for the life of the database.
        track_db.upsert_track(Track(
            track_id=track_id,
            name=session.track_name,
            config=None,
            length_meters=track_length_m,
            track_type=TrackType.ROAD,
            character=None,
        ))

        # History rows first — recording marks the file processed even for
        # an empty session (so it doesn't rescan forever).
        session_id = path.stem
        track_db.record_session(
            session_id=session_id,
            track_id=track_id,
            car=session.car_name,
            session_type=session.session_type or "unknown",
            # iRacing stamps filenames "... YYYY-MM-DD HH-MM-SS"; a renamed
            # file stores a garbage substring here — metadata only, never
            # parsed back, so it degrades harmlessly.
            session_date=path.stem[-19:],
            best_lap_time=report.best_lap_time,
            lap_count=len(valid),
            ibt_file_path=str(path),
        )
        track_db.record_laps(
            session_id,
            [(l.lap_number, l.lap_time, bool(l.is_valid)) for l in valid],
        )

        if best is None:
            return report

        # Promotion: compare against the existing personal_best ONLY —
        # a faster g61 lap must not block recording the driver's own PB.
        existing_pb = next(
            (m for m in ref_store.list_all()
             if m.track_id == track_id and m.car == session.car_name
             and m.source == "personal_best"),
            None,
        )
        if should_promote(
            best.lap_time,
            existing_pb.lap_time if existing_pb else None,
        ):
            ref_store.save(
                track_id, session.car_name, best,
                source="personal_best", driver_name=session.driver_name,
            )
            report.promoted = True

        # Debrief the best lap against the best available reference —
        # unless that reference IS the lap we just promoted (first session
        # at a combo: nothing meaningful to compare against).
        ref = ref_store.get(track_id, session.car_name)
        is_own_new_pb = (
            report.promoted and ref is not None
            and ref.source == "personal_best"
        )
        if ref is not None and not is_own_new_pb:
            corners = _load_corners(
                track_db, track_id, session.track_directory,
                track_length_m,
            )
            result = build_debrief(best, ref.lap, corners)
            report.debrief_text = format_lap_block(
                best.lap_number, best.lap_time,
                result.total_time_delta, result.diagnoses, top_n=3,
            )
        return report
    except Exception as exc:
        report.error = f"{type(exc).__name__}: {exc}"
        return report
