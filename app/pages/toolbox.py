"""Toolbox page — start/stop/see the host background tools.

Founder-only surface (renders a notice unless the host telemetry folder
exists). Display-only: process lifecycle lives in
core/live/process_control.py; the watcher pipeline in core/watcher/.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import streamlit as st

from app.components.theme import section_header
from core.live.process_control import ManagedProcess

TELEMETRY_DIR = Path(r"C:\Users\antho\Documents\iRacing\telemetry")
SESSION_LOG_DIR = Path("data/live_sessions")
_PY = str(Path(".venv/Scripts/python.exe").resolve())


def _coach(mute: bool = False, corner_prompts: bool = False) -> ManagedProcess:
    cmd = [_PY, "scripts/live_coach.py"]
    if mute:
        cmd.append("--mute")
    if corner_prompts:
        cmd.append("--corner-prompts")
    return ManagedProcess("live-coach", cmd, workdir=Path.cwd())


def _watcher() -> ManagedProcess:
    return ManagedProcess(
        "telemetry-watcher",
        [_PY, "scripts/watch_telemetry.py", "--watch"],
        workdir=Path.cwd(),
    )


def _latest_session_events(n: int = 8) -> list[dict]:
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

    if not TELEMETRY_DIR.exists():
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
            "Corner prompts", value=False, key="coach_prompts",
            help="Approach-triggered in-corner prompts (validate plain voice first)",
        )
        if st.button("Start coach", disabled=coach.is_running()):
            _coach(mute, prompts).start()
            st.rerun()
    with col_stop:
        if st.button("Stop coach", disabled=not coach.is_running()):
            coach.stop()
            st.rerun()

    events = _latest_session_events()
    if events:
        st.caption("Latest session activity (newest last):")
        for e in events:
            kind = e.get("event", "?")
            if kind == "connect":
                ref = e.get("reference") or {}
                ref_txt = (
                    f"reference {ref.get('source')} "
                    f"{ref.get('lap_time', 0):.3f}s"
                    if ref else "no reference (lap 1 becomes baseline)"
                )
                st.text(
                    f"connected: {e.get('track')} — {e.get('car')} — {ref_txt}"
                )
            else:
                st.text(json.dumps(e)[:160])
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
            st.rerun()
    with col_w3:
        if st.button("Stop --watch", disabled=not watcher.is_running()):
            watcher.stop()
            st.rerun()
    if watcher.log_tail():
        with st.expander("Watcher process log (tail)"):
            st.code(watcher.log_tail(25), language=None)
