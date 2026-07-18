"""Toolbox page — start/stop/see the host background tools.

Founder-only surface (renders a notice unless the host telemetry folder
exists). Display-only: process lifecycle lives in
core/live/process_control.py; the watcher pipeline in core/watcher/.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import streamlit as st

from app.components.host import telemetry_dir
from app.components.theme import section_header
from core.live.feed import format_transcript_line
from core.live.process_control import ManagedProcess

SESSION_LOG_DIR = Path("data/live_sessions")
_PY = str(Path(".venv/Scripts/python.exe").resolve())


# PID files must resolve to the same place regardless of CWD (same pinning
# as scripts/launch.py) or the status badges desync from reality.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUN_DIR = _REPO_ROOT / "data" / "run"


def _coach(mute: bool = False, corner_prompts: bool = True,
           engineer: bool = True) -> ManagedProcess:
    """Coach spawn command. Round-2 CLI: corner prompts are ON by default,
    --no-corner-prompts disables (coupling-tested in test_toolbox_commands --
    a stale flag here killed the coach at startup on 2026-07-14)."""
    cmd = [_PY, "scripts/live_coach.py"]
    if mute:
        cmd.append("--mute")
    if not corner_prompts:
        cmd.append("--no-corner-prompts")
    if not engineer:
        cmd.append("--no-engineer")
    return ManagedProcess(
        "live-coach", cmd, run_dir=_RUN_DIR, workdir=_REPO_ROOT
    )


def _watcher() -> ManagedProcess:
    return ManagedProcess(
        "telemetry-watcher",
        [_PY, "scripts/watch_telemetry.py", "--watch"],
        run_dir=_RUN_DIR,
        workdir=_REPO_ROOT,
    )


def _latest_session_events(n: int = 12) -> list[dict]:
    """Last N events from the newest live-session log."""
    logs = sorted(
        SESSION_LOG_DIR.glob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not logs:
        return []
    events = []
    for line in logs[0].read_text(encoding="utf-8").splitlines()[-n:]:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _status_line(proc: ManagedProcess) -> str:
    if proc.is_running():
        return f"🟢 **Running** (PID {proc.pid()})"
    return "⚪ Stopped"


def render_toolbox_page() -> None:
    st.header("Toolbox")
    st.markdown("Start, stop, and watch the pit-wall tools on this machine.")

    if not telemetry_dir().exists():
        st.info(
            "The Toolbox controls processes on the host machine — it's not "
            "available from this device."
        )
        return

    # --- Live voice coach ------------------------------------------------
    section_header("\U0001f399 Live voice coach")
    coach = _coach()
    st.markdown(_status_line(coach))

    col_start, col_stop = st.columns(2)
    with col_start:
        mute = st.checkbox("Mute (text only)", value=False, key="coach_mute")
        prompts = st.checkbox(
            "Corner prompts", value=True, key="coach_prompts",
            help="Approach-triggered in-corner cues (on by default since "
                 "voice round 2)",
        )
        engineer = st.checkbox(
            "Race engineer", value=True, key="coach_engineer",
            help="Gap calls and race intelligence (active in Race sessions "
                 "only; on by default)",
        )
        if st.button("Start coach", disabled=coach.is_running()):
            proc = _coach(mute, prompts, engineer)
            proc.start()
            # An instant death (bad flag, import error) must not be silent:
            # the 2026-07-14 argparse crash showed 'running' for one rerun
            # and the user drove without radio.
            time.sleep(1.0)
            if not proc.is_running():
                st.error(
                    "Coach exited immediately - last log lines:\n\n"
                    + (proc.log_tail(5) or "(no log output)")
                )
            else:
                st.rerun()
    with col_stop:
        if st.button("Stop coach", disabled=not coach.is_running()):
            coach.stop()
            st.rerun()

    events = _latest_session_events(12)
    if events:
        st.caption("Latest session activity (newest last):")
        for e in events:
            line = format_transcript_line(e)
            if line:
                st.text(line)
        with st.expander("Raw events (host debugging)"):
            st.code(
                "\n".join(json.dumps(e) for e in events), language="json"
            )
    if coach.log_tail():
        with st.expander("Coach process log (tail)"):
            st.code(coach.log_tail(25), language=None)

    # --- Telemetry watcher ------------------------------------------------
    section_header("\U0001f4e1 Telemetry watcher")
    watcher = _watcher()
    st.markdown(_status_line(watcher))

    col_w1, col_w2, col_w3 = st.columns(3)
    with col_w1:
        if st.button("Scan now"):
            with st.spinner("Scanning telemetry folder..."):
                result = subprocess.run(
                    [_PY, "scripts/watch_telemetry.py"],
                    capture_output=True, text=True, cwd=str(Path.cwd()),
                )
            st.code(result.stdout[-3000:] or result.stderr[-1000:], language=None)
    with col_w2:
        if st.button("Start --watch", disabled=watcher.is_running()):
            watcher.start()
            time.sleep(1.0)
            if not watcher.is_running():
                st.error(
                    "Watcher exited immediately - last log lines:\n\n"
                    + (watcher.log_tail(5) or "(no log output)")
                )
            else:
                st.rerun()
    with col_w3:
        if st.button("Stop --watch", disabled=not watcher.is_running()):
            watcher.stop()
            st.rerun()
    if watcher.log_tail():
        with st.expander("Watcher process log (tail)"):
            st.code(watcher.log_tail(25), language=None)
