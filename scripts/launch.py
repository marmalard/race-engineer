"""One-click launcher for the Race Engineer rig.

Double-clicked via scripts/start-race-engineer.bat. Starts the telemetry
watcher (detached, managed), launches Streamlit as a child of this console,
waits for the port, and opens the browser. Closing the console stops
Streamlit; the watcher survives (stop it from the Toolbox or with
stop-race-engineer.bat).

Only the port helpers are original logic and unit-tested; process spawning
and browser opening are thin I/O over ManagedProcess / subprocess.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.live.process_control import ManagedProcess  # noqa: E402

HOST = "127.0.0.1"
PORT = 8501
URL = f"http://localhost:{PORT}"
VENV_PY = _ROOT / ".venv" / "Scripts" / "python.exe"
PORT_WAIT_TIMEOUT_S = 15.0
PORT_POLL_INTERVAL_S = 0.3


def is_port_listening(port: int, host: str = HOST) -> bool:
    """True when a TCP connect to (host, port) succeeds."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def wait_for_port(
    port: int,
    timeout_s: float = PORT_WAIT_TIMEOUT_S,
    interval_s: float = PORT_POLL_INTERVAL_S,
    host: str = HOST,
) -> bool:
    """Poll until the port is listening or the timeout elapses.

    Returns True as soon as the port accepts a connection, False if the
    deadline passes first.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if is_port_listening(port, host):
            return True
        time.sleep(interval_s)
    return False
