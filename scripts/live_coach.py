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
import threading
import time
from datetime import datetime
from pathlib import Path

# Ensure project root on path when run as a script.
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Detached (ManagedProcess) stdout is a cp1252 file on Windows; utf-8 keeps
# em-dash nudges readable in the Toolbox log tail (which reads utf-8) and
# makes printing encoding-proof. line_buffering keeps the tail fresh.
if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(
        encoding="utf-8", errors="replace", line_buffering=True
    )

# Load .env ourselves: only Toolbox-spawned instances inherit Streamlit's
# dotenv-loaded env. Any other spawn (launcher, terminal, scheduler) was
# silently running credential-less and the PTT Claude path was offline
# (2026-07-14 watch_telemetry incident — mirrored here).
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import irsdk  # noqa: E402

from core.benchmark.reference_store import ReferenceLap, ReferenceStore  # noqa: E402
from core.coaching.debrief import build_debrief  # noqa: E402
from core.engineer.calls import EngineerCalls  # noqa: E402
from core.engineer.corner_loss import CornerLossTracker  # noqa: E402
from core.engineer.race_state import ENGINEER_CHANNELS, RaceState  # noqa: E402
from core.engineer.radio_budget import RadioBudget  # noqa: E402
from core.live.feed import NudgeFeed, start_web_display  # noqa: E402
from core.live.lap_buffer import SAMPLE_CHANNELS  # noqa: E402
from core.live.exit_verdict import VerdictWatcher  # noqa: E402
from core.live.nudges import (  # noqa: E402
    fault_kinds_from_diagnosis,
    format_asterisk_speech,
    format_dirty_baseline_speech,
    format_discard_speech,
    format_lap_block,
    format_lap_speech,
    format_radio_check,
)
from core.live.race_gate import (  # noqa: E402
    RACE_CUE_MODES,
    FaultStreakTracker,
    current_session_type,
    gate_diagnoses,
)
from core.telemetry.cleanliness import IncidentTracker  # noqa: E402
from core.live.prompt_scheduler import PromptScheduler, build_plan  # noqa: E402
from core.live.session_reader import LapBoundaryTracker  # noqa: E402
from core.live.session_log import SessionLog  # noqa: E402
from core.live.speaker import create_speaker  # noqa: E402
from core.engineer.answers import answer_question, make_claude_ask  # noqa: E402
from core.engineer.mic import MicCapture  # noqa: E402
from core.engineer.ptt_input import PTTButton, open_joystick  # noqa: E402
from core.engineer import stt  # noqa: E402
from core.telemetry.normalizer import Normalizer  # noqa: E402
from core.track.lovely_seeder import seed_track_from_lovely  # noqa: E402
from core.track.models import Track, TrackType  # noqa: E402
from core.track.track_db import TrackDB  # noqa: E402

DB_PATH = Path("data/tracks.db")
REFERENCE_DB = Path("data/reference_laps.db")
LOG_DIR = Path("data/live_sessions")
# Channels the tracker + buffer need: the normalizer-ready set plus the
# boundary/validity flags the state machine reads.
READ_CHANNELS = SAMPLE_CHANNELS + [
    "Lap", "OnPitRoad", "PlayerTrackSurface", "PlayerCarMyIncidentCount",
    "SessionNum",
]
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


def build_parser() -> argparse.ArgumentParser:
    """The coach's CLI. Public so the Toolbox's spawn command can be
    coupling-tested against it — the page passing a stale flag killed the
    coach at startup on 2026-07-14 (round 2 renamed --corner-prompts to
    --no-corner-prompts; the Toolbox was never updated)."""
    parser = argparse.ArgumentParser(description="Live between-lap coach")
    parser.add_argument("--mute", action="store_true",
                        help="disable voice output")
    parser.add_argument("--no-corner-prompts", dest="corner_prompts",
                        action="store_false",
                        help="disable approach cues before flagged corners "
                             "(on by default)")
    parser.add_argument("--race-cues", dest="race_cues",
                        choices=RACE_CUE_MODES, default="persistent",
                        help="cue behavior in Race sessions: full = like "
                             "practice, persistent = only faults seen 2+ "
                             "consecutive laps (default), off = silent")
    parser.add_argument("--no-engineer", dest="engineer",
                        action="store_false",
                        help="disable race engineer calls + PTT "
                             "(on by default; active in Race sessions only)")
    parser.add_argument("--ptt-button", type=int, default=5,
                        help="joystick button index for push-to-talk "
                             "(find yours with scripts/probe_ptt_button.py)")
    parser.set_defaults(corner_prompts=True, engineer=True)
    return parser


def _parse_args() -> argparse.Namespace:
    return build_parser().parse_args()


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
    """Stored reference lap for this combo, or None — with a visible reason.

    A silent car-string mismatch would be indistinguishable from having no
    reference at all: the coach would quietly fall back to session-best mode
    and trail-braking coaching (which needs a G61 lap that actually trails)
    would never fire."""
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


def _ptt_worker(audio, stt_model, snapshot: dict, ask, speaker,
                emit, session_log, budget) -> None:
    """Runs on a worker thread: STT -> answer -> priority speech. Never
    raises into the tick loop; every failure becomes a spoken line."""
    import time as _time
    try:
        transcript = stt.transcribe(stt_model, audio)
        text, source = answer_question(transcript, snapshot, ask=ask)
        speaker.say_priority(text)
        budget.note_priority(_time.monotonic())
    except Exception:
        speaker.say_priority("Say again?")
        return
    try:
        emit(f"  [PTT] {transcript or '(unintelligible)'} -> {text}")
        if session_log is not None:
            session_log.log("ptt", transcript=transcript, answer=text,
                            source=source, snapshot=snapshot)
    except Exception:
        pass


def _diag_fields(d) -> dict:
    """RegionDiagnosis -> flat dict for the session log (all tuning numbers)."""
    return {
        "label": d.label,
        "time_lost": d.region.time_lost,
        "region_start_m": d.region.distance_start,
        "region_end_m": d.region.distance_end,
        "braking_delta_m": d.braking_delta_m,
        "min_speed_delta_ms": d.min_speed_delta_ms,
        "brake_release_delta_m": d.brake_release_delta_m,
        "exit_speed_delta_ms": d.exit_speed_delta_ms,
        "throttle_delta_m": d.throttle_delta_m,
        "reference_brake_onset_m": d.reference_brake_onset_m,
    }


def main() -> None:
    args = _parse_args()
    ir = irsdk.IRSDK()
    print("Race Engineer live coach - waiting for iRacing...")

    feed = NudgeFeed()
    start_web_display(feed)
    print(f"Web display: http://{_lan_ip()}:8042  (open in Safari on your iPad)")

    speaker = create_speaker(mute=args.mute)

    ptt_poll = open_joystick(args.ptt_button) if args.engineer else None
    ptt_button = PTTButton()
    mic = MicCapture()
    ptt_ask = make_claude_ask() if args.engineer else None
    stt_model = None
    stt_ready = threading.Event()

    def _load_stt() -> None:
        nonlocal stt_model
        stt_model = stt.load_model()
        if stt_model is None:
            print("PTT: speech model failed to load -- questions will get "
                  "'Say again?' (run uv sync --group rig).")
        stt_ready.set()

    if args.engineer and ptt_poll is not None:
        threading.Thread(target=_load_stt, daemon=True).start()
        print(f"PTT: joystick 0 button {args.ptt_button} "
              f"(probe with scripts/probe_ptt_button.py). "
              f"Claude path: {'on' if ptt_ask else 'OFF (no API key)'}.")
    elif args.engineer:
        print("PTT: no joystick found -- engineer calls only.")

    def emit(block: str) -> None:
        print(block)
        feed.add(block)

    tracker = LapBoundaryTracker()
    normalizer = Normalizer()
    scheduler = PromptScheduler()
    verdict_watcher = VerdictWatcher()
    streaks = FaultStreakTracker()
    session_num: int | None = None
    session_type = ""
    incident_tracker = IncidentTracker()
    session_log: SessionLog | None = None
    reference_lap = None       # stored (G61/PB) lap; never replaced mid-session
    session_best = None        # fallback comparison lap when no stored reference
    corners: list = []
    meta_loaded = False
    prev_flagged: set = set()
    prev_delta: float | None = None
    race_state: RaceState | None = None
    engineer_calls: EngineerCalls | None = None
    corner_loss: CornerLossTracker | None = None

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
                verdict_watcher.set_plan([], track_length_m)
                streaks = FaultStreakTracker()
                session_num = None
                session_type = ""
                incident_tracker = IncidentTracker()
                prev_flagged = set()
                prev_delta = None
                driver_info = ir["DriverInfo"] or {}
                player_idx = int(driver_info.get("DriverCarIdx", 0) or 0)
                race_state = RaceState(player_idx)
                race_state.set_roster(driver_info.get("Drivers", []))
                engineer_calls = EngineerCalls(RadioBudget())
                corner_loss = CornerLossTracker([
                    (c.distance_start_meters, c.distance_end_meters, c.name)
                    for c in corners
                    if c.name and c.distance_start_meters is not None
                    and c.distance_end_meters is not None
                ])
                meta_loaded = True
                if session_log is not None:
                    session_log.close()
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                slug = track_dir.replace(" ", "-") or "unknown"
                session_log = SessionLog(
                    LOG_DIR / f"{slug}_{stamp}.jsonl"
                )
                session_log.log(
                    "connect",
                    track_id=track_id, track=track_display, car=car,
                    track_length_m=track_length_m,
                    corners=len(corners),
                    reference=(
                        {"source": ref.meta.source,
                         "lap_time": ref.meta.lap_time,
                         "driver": ref.meta.driver_name}
                        if ref is not None else None
                    ),
                    corner_prompts=args.corner_prompts, mute=args.mute,
                    race_cues=args.race_cues,
                )
                print(f"Session log: {session_log.path}")
                if ref is not None:
                    emit(
                        f"Reference loaded: {ref.meta.source}, "
                        f"{ref.meta.lap_time:.3f}s"
                        + (f" ({ref.meta.driver_name})"
                           if ref.meta.driver_name else "")
                    )
                    print(f"Connected: {track_display}.")
                else:
                    print(f"Connected: {track_display}. "
                          "Drive a lap to set baseline.")
                speaker.say(
                    format_radio_check(ref.meta if ref is not None else None)
                )

            ir.freeze_var_buffer_latest()
            sample = {ch: ir[ch] for ch in READ_CHANNELS}

            # pyirsdk hands back lists (whole-buffer churn) around session
            # transitions — one such tick crashed the coach mid-session
            # (2026-07-12). Skip the whole tick so no downstream consumer
            # (tracker, incident tracker, scheduler) sees non-scalar values.
            if any(isinstance(v, list) for v in sample.values()):
                time.sleep(TICK_SECONDS)
                continue

            # Session-type refresh — the YAML is parsed only when SessionNum
            # changes (practice -> qualify -> race transitions), never per
            # tick. WeekendInfo.EventType is NOT trustworthy here: it reads
            # "Race" for practice sessions on a race server.
            snum = sample.get("SessionNum")
            if (isinstance(snum, (int, float)) and not isinstance(snum, bool)
                    and int(snum) != session_num):
                session_num = int(snum)
                try:
                    session_type = current_session_type(
                        ir["SessionInfo"], session_num
                    )
                except Exception:
                    session_type = ""
                if session_log is not None:
                    session_log.log("session_type", session_num=session_num,
                                    session_type=session_type)

            # Engineer feed -- separate read because CarIdx channels are
            # arrays; the scalar churn guard above must not see them. The
            # feed runs in every session (harmless, keeps history warm);
            # only EMISSION is gated on Race via engineer_active.
            try:
                engineer_active = (args.engineer and session_type == "Race"
                                   and race_state is not None)
                eng_boundary = False
                if race_state is not None:
                    eng_sample = {ch: ir[ch] for ch in ENGINEER_CHANNELS}
                    eng_boundary = race_state.feed(eng_sample)
                    if engineer_active:
                        _dist = sample.get("LapDist")
                        _gap = race_state.current_gap_ahead()
                        if (_dist is not None and _gap is not None
                                and corner_loss is not None):
                            corner_loss.feed(
                                lap_dist_m=float(_dist), gap_ahead_s=_gap[1],
                                ahead_idx=_gap[0],
                                lap=int(sample.get("Lap") or 0),
                            )
                if (engineer_active and eng_boundary
                        and engineer_calls is not None):
                    extra = None
                    if corner_loss is not None:
                        snap_ahead = race_state.snapshot().get("ahead") or {}
                        extra = corner_loss.take_call(
                            target_name=snap_ahead.get("name", "him")
                        )
                    spoken, dropped = engineer_calls.on_lap(
                        race_state, now=time.monotonic(), extra_call=extra,
                    )
                    for line in spoken:
                        emit(f"  [ENG] {line}")
                    # One utterance so lines can't self-clobber (latest-wins
                    # queue). Known limit: a lap-summary say() arriving while
                    # the speaker is mid-utterance can still replace a pending
                    # engineer call (one-slot latest-wins by design); logged
                    # as queued, not aired.
                    if spoken:
                        speaker.say(" ".join(spoken))
                    if session_log is not None and (spoken or dropped):
                        session_log.log(
                            "engineer_call", queued=spoken, dropped=dropped,
                            snapshot=race_state.snapshot(),
                        )
                if not engineer_active and ptt_poll is not None:
                    # Session flipped away from Race mid-hold: scratch the
                    # recording now, or the open stream leaks and the next
                    # race's first tick fires a phantom release/answer.
                    if ptt_button.feed(False) == "release":
                        mic.stop()
                if engineer_active and ptt_poll is not None:
                    event = ptt_button.feed(ptt_poll())
                    if event == "press":
                        speaker.cancel_pending()  # driver keyed the radio
                        mic.start()
                    elif event == "release":
                        audio = mic.stop()
                        if stt_ready.is_set() and race_state is not None:
                            threading.Thread(
                                target=_ptt_worker,
                                args=(audio, stt_model, race_state.snapshot(),
                                      ptt_ask, speaker, emit, session_log,
                                      engineer_calls.budget),
                                daemon=True,
                            ).start()
                        else:
                            speaker.say_priority(
                                "Radio's still warming up — give me a second."
                            )
            except Exception:  # noqa: BLE001 -- never kill the coach
                pass

            tick = tracker.feed(sample)
            completed = tick.completed
            if tick.discarded is not None:
                discard_speech = format_discard_speech(tick.discarded)
                emit(discard_speech)
                speaker.say(discard_speech)
                if session_log is not None:
                    session_log.log(
                        "discard", reason=tick.discarded.value,
                        speech=discard_speech,
                    )
                incident_tracker.reset()
            else:
                _dist = sample.get("LapDist")
                if _dist is not None and not sample.get("OnPitRoad"):
                    incident_tracker.feed(
                        sample.get("PlayerCarMyIncidentCount"), float(_dist),
                    )

            # LapDist is None while towed/out-of-world; feeding 0.0 then would
            # look like a start/finish wrap and false-fire a pending prompt.
            # While skipping, also forget the scheduler's last position so the
            # jump back on track isn't mistaken for a wrap either.
            if args.corner_prompts:
                lap_dist = sample.get("LapDist")
                if lap_dist is not None and not sample.get("OnPitRoad"):
                    prompt = scheduler.feed(float(lap_dist))
                    if prompt is not None:
                        print(f"  >> {prompt}")
                        speaker.say(prompt)
                        if session_log is not None:
                            session_log.log(
                                "prompt", text=prompt,
                                lap_dist_m=float(lap_dist),
                                lap=int(sample.get("Lap") or 0),
                            )
                    try:
                        verdict = verdict_watcher.feed(
                            float(lap_dist), float(sample.get("Speed") or 0.0),
                            float(sample.get("Brake") or 0.0),
                            float(sample.get("Throttle") or 0.0),
                        )
                    except Exception:  # noqa: BLE001 -- never kill the coach
                        verdict = None
                    if verdict is not None:
                        emit(f"  << {verdict.text}")
                        speaker.say(verdict.text)
                        if session_log is not None:
                            session_log.log(
                                "verdict", text=verdict.text,
                                corner=verdict.label,
                                fault=verdict.kind.value,
                                bucket=verdict.bucket,
                                live_delta=verdict.live_delta,
                                brake_onset_m=verdict.observed_brake_onset_m,
                                min_speed_ms=verdict.observed_min_speed_ms,
                                throttle_on_m=verdict.observed_throttle_on_m,
                                lap=int(sample.get("Lap") or 0),
                            )
                else:
                    scheduler.reset_position()
                    verdict_watcher.reset_position()

            if completed is not None:
                marks = incident_tracker.close_lap()
                scheduler.rearm()
                verdict_watcher.rearm()
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
                        if marks:
                            skip_speech = format_dirty_baseline_speech(marks)
                            emit(skip_speech)
                            speaker.say(skip_speech)
                            if session_log is not None:
                                session_log.log(
                                    "dirty_baseline_skipped",
                                    lap=nlap.lap_number,
                                    lap_time=nlap.lap_time,
                                    marks=[
                                        {"distance_m": m.distance_m,
                                         "delta": m.delta}
                                        for m in marks
                                    ],
                                    speech=skip_speech,
                                )
                        else:
                            session_best = nlap
                            emit(format_lap_block(
                                nlap.lap_number, nlap.lap_time, 0.0, [],
                                is_baseline=True,
                            ))
                            speech, prev_flagged = format_lap_speech(
                                nlap.lap_time, 0.0, [], is_baseline=True,
                            )
                            speaker.say(speech)
                            if session_log is not None:
                                session_log.log(
                                    "baseline", lap=nlap.lap_number,
                                    lap_time=nlap.lap_time, speech=speech,
                                )
                    else:
                        result = build_debrief(nlap, comparison, corners)
                        asterisk = format_asterisk_speech(marks, corners)
                        emit(format_lap_block(
                            nlap.lap_number, nlap.lap_time,
                            result.total_time_delta, result.diagnoses,
                        ) + asterisk)
                        # prev_delta compares deltas against a FIXED reference;
                        # in session-best fallback mode the baseline moves after
                        # each PB lap, so `improved` is approximate there.
                        improved = (
                            prev_delta is not None
                            and result.total_time_delta < prev_delta
                        )
                        speech, prev_flagged = format_lap_speech(
                            nlap.lap_time, result.total_time_delta,
                            result.diagnoses,
                            prev_flagged=prev_flagged, improved=improved,
                        )
                        speech += asterisk
                        speaker.say(speech)
                        if session_log is not None:
                            session_log.log(
                                "lap", lap=nlap.lap_number,
                                lap_time=nlap.lap_time,
                                delta=result.total_time_delta,
                                improved=improved, speech=speech,
                                dirty=bool(marks),
                                marks=[
                                    {"distance_m": m.distance_m,
                                     "delta": m.delta}
                                    for m in marks
                                ],
                                diagnoses=[
                                    _diag_fields(d) for d in result.diagnoses
                                ],
                            )
                        prev_delta = result.total_time_delta
                        if args.corner_prompts:
                            # Exactly once per completed comparison lap, with
                            # the FULL fault set — absent keys reset streaks
                            # (FaultStreakTracker.update contract).
                            # Streaks count COACHED laps, not calendar laps:
                            # invalid/baseline/dirty-baseline laps produce no
                            # diagnoses and don't reset streaks. A fault can
                            # therefore reach the race gate across an invalid-
                            # lap gap — accepted v1 semantics.
                            streaks.update({
                                (d.label, kinds[0])
                                for d in result.diagnoses
                                if (kinds := fault_kinds_from_diagnosis(d))
                            })
                            gated = gate_diagnoses(
                                result.diagnoses, mode=args.race_cues,
                                is_race=(session_type == "Race"),
                                tracker=streaks,
                            )
                            prompts, verdicts = build_plan(
                                gated, corners, track_length_m,
                            )
                            scheduler.set_schedule(prompts)
                            verdict_watcher.set_plan(verdicts, track_length_m)
                            if session_log is not None:
                                session_log.log("schedule", prompts=[
                                    {"trigger_m": p.trigger_m, "text": p.text}
                                    for p in prompts
                                ], verdicts=[
                                    v.diagnosis.label for v in verdicts
                                ], gated_out=len(result.diagnoses) - len(gated))
                        if (reference_lap is None and not marks
                                and nlap.lap_time < session_best.lap_time):
                            session_best = nlap
                else:
                    invalid_speech = "That lap won't count — data's incomplete."
                    emit(invalid_speech)
                    speaker.say(invalid_speech)
                    if session_log is not None:
                        session_log.log(
                            "invalid", lap=nlap.lap_number,
                            speech=invalid_speech,
                        )

            time.sleep(TICK_SECONDS)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        speaker.close()
        if session_log is not None:
            session_log.close()
        ir.shutdown()


if __name__ == "__main__":
    main()
