"""Live between-lap coaching — terminal spike.

Run this with iRacing open and on track:

    .venv/Scripts/python.exe scripts/live_coach.py

After each completed flying lap it prints coaching nudges derived from the
existing loss-region engine, comparing the lap to your best lap so far in
the session. Pit laps, out/in-laps, and resets are suppressed.

This is the de-risk spike: it proves lap-boundary detection and nudge
quality before any HUD is built. All real logic lives in tested modules
under core/live/ and core/coaching/; this file only drives pyirsdk.
"""

import sys
import time
from pathlib import Path

# Ensure project root on path when run as a script.
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import irsdk  # noqa: E402

from core.coaching.debrief import build_debrief  # noqa: E402
from core.live.lap_buffer import SAMPLE_CHANNELS  # noqa: E402
from core.live.nudges import format_lap_block  # noqa: E402
from core.live.session_reader import LapBoundaryTracker  # noqa: E402
from core.telemetry.normalizer import Normalizer  # noqa: E402
from core.track.lovely_seeder import seed_track_from_lovely  # noqa: E402
from core.track.track_db import TrackDB  # noqa: E402

DB_PATH = Path("data/tracks.db")
# Channels the tracker + buffer need: the normalizer-ready set plus the
# boundary/validity flags the state machine reads.
READ_CHANNELS = SAMPLE_CHANNELS + ["Lap", "OnPitRoad", "PlayerTrackSurface"]
TICK_SECONDS = 1.0 / 60.0


def _parse_track_length_km(weekend_info: dict) -> float:
    """TrackLength like '7.00 km' -> 7.0 (km)."""
    raw = str(weekend_info.get("TrackLength", "0 km"))
    try:
        return float(raw.split()[0])
    except (ValueError, IndexError):
        return 0.0


def _session_meta(ir: "irsdk.IRSDK") -> tuple[str, float, str, str]:
    """Return (track_id_str, track_length_m, track_dir, track_display).

    track_dir is iRacing's directory string ("spa 2024 up") used to build
    the lovely-track-data slug; track_display is the pretty name for output.
    """
    weekend = ir["WeekendInfo"] or {}
    track_id = str(weekend.get("TrackID", "") or "")
    track_length_m = _parse_track_length_km(weekend) * 1000.0
    track_dir = str(weekend.get("TrackName", "") or "")
    track_display = str(weekend.get("TrackDisplayName", "track"))
    return track_id, track_length_m, track_dir, track_display


def _load_corners(track_id: str, track_dir: str, track_length_m: float) -> list:
    """Named corners for labeling, seeding from lovely-track-data on first use.

    track_dir is iRacing's directory string (e.g. "spa 2024 up"), which the
    lovely seeder turns into its slug. Already-seeded tracks return existing
    corners without re-seeding.
    """
    if not track_id:
        return []
    db = TrackDB(DB_PATH)
    if db.get_track(track_id) is None:
        # No track row -> nothing to attach corners to; skip seeding.
        return []
    corners = db.get_corners(track_id)
    if not corners:
        try:
            seed_track_from_lovely(
                db, track_id=track_id,
                ibt_track_name=track_dir,
                track_length_m=track_length_m,
            )
            corners = db.get_corners(track_id)
        except Exception:
            corners = []
    return corners


def main() -> None:
    ir = irsdk.IRSDK()
    print("Race Engineer live coach - waiting for iRacing...")

    tracker = LapBoundaryTracker()
    normalizer = Normalizer()
    session_best = None
    corners: list = []
    meta_loaded = False

    try:
        while True:
            if not (ir.is_initialized and ir.is_connected):
                ir.shutdown()
                meta_loaded = False
                ir.startup()
                time.sleep(0.5)
                continue

            if not meta_loaded:
                track_id, track_length_m, track_dir, track_display = _session_meta(ir)
                corners = _load_corners(track_id, track_dir, track_length_m)
                session_best = None
                meta_loaded = True
                print(f"Connected: {track_display}. Drive a lap to set baseline.")

            ir.freeze_var_buffer_latest()
            sample = {ch: ir[ch] for ch in READ_CHANNELS}

            completed = tracker.feed(sample)
            if completed is not None:
                # track_length_m was captured at connect time and is stable
                # for the session, so reuse it rather than re-reading the YAML.
                nlap = normalizer.normalize_lap(
                    completed.dataframe, completed.lap_number, track_length_m
                )
                if nlap.is_valid:
                    if session_best is None:
                        session_best = nlap
                        print(format_lap_block(
                            nlap.lap_number, nlap.lap_time, 0.0, [],
                            is_baseline=True,
                        ))
                    else:
                        result = build_debrief(nlap, session_best, corners)
                        print(format_lap_block(
                            nlap.lap_number, nlap.lap_time,
                            result.total_time_delta, result.diagnoses,
                        ))
                        if nlap.lap_time < session_best.lap_time:
                            session_best = nlap

            time.sleep(TICK_SECONDS)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        ir.shutdown()


if __name__ == "__main__":
    main()
