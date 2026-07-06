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

import argparse
import socket
import sys
import time
from pathlib import Path

# Ensure project root on path when run as a script.
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import irsdk  # noqa: E402

from core.benchmark.reference_store import ReferenceLap, ReferenceStore  # noqa: E402
from core.coaching.debrief import build_debrief  # noqa: E402
from core.live.feed import NudgeFeed, start_web_display  # noqa: E402
from core.live.lap_buffer import SAMPLE_CHANNELS  # noqa: E402
from core.live.nudges import format_lap_block, format_lap_speech  # noqa: E402
from core.live.prompt_scheduler import PromptScheduler, build_schedule  # noqa: E402
from core.live.session_reader import LapBoundaryTracker  # noqa: E402
from core.live.speaker import create_speaker  # noqa: E402
from core.telemetry.normalizer import Normalizer  # noqa: E402
from core.track.lovely_seeder import seed_track_from_lovely  # noqa: E402
from core.track.models import Track, TrackType  # noqa: E402
from core.track.track_db import TrackDB  # noqa: E402

DB_PATH = Path("data/tracks.db")
REFERENCE_DB = Path("data/reference_laps.db")
# Channels the tracker + buffer need: the normalizer-ready set plus the
# boundary/validity flags the state machine reads.
READ_CHANNELS = SAMPLE_CHANNELS + ["Lap", "OnPitRoad", "PlayerTrackSurface"]
TICK_SECONDS = 1.0 / 60.0


def _lan_ip() -> str:
    """Best-guess primary LAN IP for the 'open this on your iPad' message."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


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


def _load_corners(
    track_id: str, track_dir: str, track_length_m: float, track_display: str
) -> list:
    """Named corners for labeling, seeding from lovely-track-data on first use.

    A live session may be at a track never processed offline (the tracks
    table is only populated by the offline IBT pipeline), so we create a
    minimal track row from the live session metadata first — otherwise
    corner seeding has nothing to attach to and every loss region falls
    back to a bare distance. track_dir is iRacing's directory string (e.g.
    "oran gp"), which the lovely seeder turns into its slug. Already-named
    tracks return their existing corners without re-seeding.
    """
    if not track_id:
        return []
    db = TrackDB(DB_PATH)
    if db.get_track(track_id) is None:
        db.upsert_track(Track(
            track_id=track_id,
            name=track_display,
            config=None,
            length_meters=track_length_m,
            track_type=TrackType.ROAD,
            character=None,
        ))
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


def _car_name(ir: "irsdk.IRSDK") -> str:
    """The driver's CarScreenName — the exact field the offline pipeline
    (IBTParser) stores references under, so ReferenceStore lookups match."""
    info = ir["DriverInfo"] or {}
    drivers = info.get("Drivers", [])
    idx = int(info.get("DriverCarIdx", 0) or 0)
    if drivers and idx < len(drivers):
        return str(drivers[idx].get("CarScreenName", "") or "")
    return ""


def _load_reference(track_id: str, car: str) -> "ReferenceLap | None":
    """Stored reference lap for this combo, or None — with a visible reason,
    because a silent car-string mismatch would just look like missing
    trail coaching."""
    if not track_id or not car:
        return None
    try:
        ref = ReferenceStore(REFERENCE_DB).get(track_id, car)
    except Exception as exc:
        print(f"Reference lookup failed for ({track_id!r}, {car!r}): {exc}")
        return None
    if ref is None:
        print(f"No stored reference for ({track_id!r}, {car!r}); "
              "coaching against session best.")
    return ref


def main() -> None:
    args = _parse_args()
    ir = irsdk.IRSDK()
    print("Race Engineer live coach - waiting for iRacing...")

    feed = NudgeFeed()
    start_web_display(feed)
    print(f"Web display: http://{_lan_ip()}:8042  (open in Safari on your iPad)")

    speaker = create_speaker(mute=args.mute)

    def emit(block: str) -> None:
        print(block)
        feed.add(block)

    tracker = LapBoundaryTracker()
    normalizer = Normalizer()
    scheduler = PromptScheduler()
    reference_lap = None       # stored (G61/PB) lap; never replaced mid-session
    session_best = None        # fallback comparison lap when no stored reference
    corners: list = []
    meta_loaded = False
    prev_flagged: set = set()
    prev_delta: float | None = None

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
                corners = _load_corners(
                    track_id, track_dir, track_length_m, track_display
                )
                car = _car_name(ir)
                ref = _load_reference(track_id, car)
                reference_lap = ref.lap if ref is not None else None
                session_best = None
                scheduler.set_schedule([])
                prev_flagged = set()
                prev_delta = None
                meta_loaded = True
                if ref is not None:
                    emit(
                        f"Reference loaded: {ref.meta.source}, "
                        f"{ref.meta.lap_time:.3f}s"
                        + (f" ({ref.meta.driver_name})"
                           if ref.meta.driver_name else "")
                    )
                    speaker.say("Reference lap loaded. Coaching from lap one.")
                    print(f"Connected: {track_display}.")
                else:
                    print(f"Connected: {track_display}. "
                          "Drive a lap to set baseline.")

            ir.freeze_var_buffer_latest()
            sample = {ch: ir[ch] for ch in READ_CHANNELS}

            completed = tracker.feed(sample)

            if args.corner_prompts and not sample.get("OnPitRoad"):
                prompt = scheduler.feed(float(sample["LapDist"] or 0.0))
                if prompt is not None:
                    print(f"  >> {prompt}")
                    speaker.say(prompt)

            if completed is not None:
                scheduler.rearm()
                # track_length_m was captured at connect time and is stable
                # for the session, so reuse it rather than re-reading the YAML.
                nlap = normalizer.normalize_lap(
                    completed.dataframe, completed.lap_number, track_length_m
                )
                if nlap.is_valid:
                    comparison = (
                        reference_lap if reference_lap is not None
                        else session_best
                    )
                    if comparison is None:
                        session_best = nlap
                        emit(format_lap_block(
                            nlap.lap_number, nlap.lap_time, 0.0, [],
                            is_baseline=True,
                        ))
                        speech, prev_flagged = format_lap_speech(
                            nlap.lap_time, 0.0, [], is_baseline=True,
                        )
                        speaker.say(speech)
                    else:
                        result = build_debrief(nlap, comparison, corners)
                        emit(format_lap_block(
                            nlap.lap_number, nlap.lap_time,
                            result.total_time_delta, result.diagnoses,
                        ))
                        improved = (
                            prev_delta is not None
                            and result.total_time_delta < prev_delta
                        )
                        speech, prev_flagged = format_lap_speech(
                            nlap.lap_time, result.total_time_delta,
                            result.diagnoses,
                            prev_flagged=prev_flagged, improved=improved,
                        )
                        speaker.say(speech)
                        prev_delta = result.total_time_delta
                        if args.corner_prompts:
                            scheduler.set_schedule(build_schedule(
                                result.diagnoses, corners, track_length_m,
                            ))
                        if (reference_lap is None
                                and nlap.lap_time < session_best.lap_time):
                            session_best = nlap

            time.sleep(TICK_SECONDS)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        speaker.close()
        ir.shutdown()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Live between-lap coach")
    parser.add_argument("--mute", action="store_true",
                        help="disable voice output")
    parser.add_argument("--corner-prompts", action="store_true",
                        help="speak approach prompts before flagged corners "
                             "(phase 2, validate --mute-less laps first)")
    return parser.parse_args()


if __name__ == "__main__":
    main()
