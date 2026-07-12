"""Clean shutdown for the Race Engineer rig.

Invoked by stop-race-engineer.bat. Stops the telemetry-watcher and
live-coach ManagedProcesses (PID-file tree-kill), then finds Streamlit
(no PID file - it runs as the launcher console's child) by command-line
fragments and tree-kills it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.live.process_control import ManagedProcess  # noqa: E402

_MANAGED = ("telemetry-watcher", "live-coach")
_RUN_DIR = _ROOT / "data" / "run"
# A python.exe is 'our Streamlit' when its command line contains ALL of
# these fragments. str(_ROOT) scopes to this repo (the venv interpreter /
# console-script path carries it); the other two match both launch styles
# ('-m streamlit run app/streamlit_app.py' and 'streamlit.exe run
# app/streamlit_app.py').
_CMDLINE_FRAGMENTS = (str(_ROOT), "streamlit", "streamlit_app.py")


def _parse_pids(stdout: str) -> list[int]:
    """Integers from a newline-separated PID list; non-numeric lines ignored."""
    pids: list[int] = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def stop_managed() -> None:
    """Stop the PID-file-managed tools (watcher, live coach)."""
    for name in _MANAGED:
        proc = ManagedProcess(name, [], run_dir=_RUN_DIR, workdir=_ROOT)
        if proc.stop():
            print(f"Stopped {name}.")
        else:
            print(f"{name} was not running.")


def _streamlit_pids() -> list[int]:
    """PIDs of python processes running this repo's Streamlit server."""
    conds = " -and ".join(
        f"$_.CommandLine -like '*{frag}*'" for frag in _CMDLINE_FRAGMENTS
    )
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { " + conds + " } | "
        "ForEach-Object { $_.ProcessId }"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True,
    )
    return _parse_pids(result.stdout)


def stop_streamlit() -> None:
    """Tree-kill any Streamlit server found by command-line match."""
    pids = _streamlit_pids()
    if not pids:
        print("Streamlit was not running.")
        return
    for pid in pids:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True
        )
        print(f"Stopped Streamlit (pid {pid}).")


def main() -> int:
    """Stop everything: managed tools first, then Streamlit."""
    stop_managed()
    stop_streamlit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
