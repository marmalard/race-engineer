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


def _watcher() -> ManagedProcess:
    return ManagedProcess(
        "telemetry-watcher",
        [str(VENV_PY), "scripts/watch_telemetry.py", "--watch"],
        workdir=_ROOT,
    )


def main() -> int:
    # Idempotency: if the app is already up, just surface it.
    if is_port_listening(PORT):
        print(f"Race Engineer already running at {URL} - opening browser.")
        webbrowser.open(URL)
        return 0

    # Watcher first (detached, idempotent). A watcher failure must never
    # block the app - it can be started later from the Toolbox.
    try:
        pid = _watcher().start()
        print(f"Telemetry watcher running (pid {pid}).")
    except Exception as exc:  # noqa: BLE001 - log and continue
        print(f"WARNING: watcher failed to start ({exc}); continuing.")

    # Streamlit as a child of this console so closing the window stops it.
    print("Starting Streamlit ...")
    proc = subprocess.Popen(
        [str(VENV_PY), "-m", "streamlit", "run",
         "app/streamlit_app.py", "--server.headless", "true"],
        cwd=str(_ROOT),
    )

    if wait_for_port(PORT):
        print(f"Opening {URL}")
    else:
        print(f"Streamlit slow to start; opening {URL} anyway - refresh if blank.")
    webbrowser.open(URL)

    proc.wait()
    return proc.returncode or 0


if __name__ == "__main__":
    raise SystemExit(main())
