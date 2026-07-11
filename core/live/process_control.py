"""Managed background processes for the Toolbox page.

Streamlit reruns its script on every interaction, so tool processes
(live coach, telemetry watcher) must live OUTSIDE the app process:
spawned detached, tracked by PID file, stopped by tree-kill. This keeps
"is it running?" answerable across app restarts and reruns.

Windows-first (the sim rig); PID files live under data/run/. Stale PID
reuse by an unrelated process is theoretically possible but accepted for
a single-user host tool — the worst case is a wrong "running" badge.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

DEFAULT_RUN_DIR = Path("data/run")

# Windows: detach so the child survives the Streamlit process entirely.
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200

# Windows liveness check. os.kill(pid, 0) is NOT an existence probe there:
# signal 0 is CTRL_C_EVENT, delivered via GenerateConsoleCtrlEvent, which only
# reaches process groups on the CALLER'S console — checked from any other
# console (Streamlit vs the terminal that spawned the tool) it raises
# WinError 87 and a live process reads as stopped. Ask the kernel instead.
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259
_ERROR_ACCESS_DENIED = 5


def _pid_alive_windows(pid: int) -> bool:
    """True when the PID names a live process (kernel query, console-free)."""
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if not handle:
        # Can't open: no such process — unless it exists but is off-limits.
        return ctypes.get_last_error() == _ERROR_ACCESS_DENIED
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


class ManagedProcess:
    """One named background tool: start detached, track, stop by tree."""

    def __init__(
        self,
        name: str,
        command: list[str],
        run_dir: Path = DEFAULT_RUN_DIR,
        workdir: Path | None = None,
    ):
        self.name = name
        self.command = command
        self.run_dir = Path(run_dir)
        self.workdir = workdir
        self.run_dir.mkdir(parents=True, exist_ok=True)

    @property
    def pid_file(self) -> Path:
        return self.run_dir / f"{self.name}.pid"

    @property
    def log_file(self) -> Path:
        return self.run_dir / f"{self.name}.log"

    def pid(self) -> int | None:
        """PID from the pid file, or None."""
        try:
            return int(self.pid_file.read_text().strip())
        except (FileNotFoundError, ValueError):
            return None

    def is_running(self) -> bool:
        """True when the recorded PID is alive."""
        pid = self.pid()
        if pid is None:
            return False
        if os.name == "nt":
            return _pid_alive_windows(pid)
        try:
            os.kill(pid, 0)  # POSIX: signal 0 = existence check
            return True
        except OSError:
            return False

    def start(self) -> int:
        """Spawn detached (idempotent: returns the live PID if running)."""
        if self.is_running():
            return self.pid()  # type: ignore[return-value]
        flags = 0
        if os.name == "nt":
            flags = _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP
        with open(self.log_file, "ab") as log:
            proc = subprocess.Popen(
                self.command,
                cwd=str(self.workdir) if self.workdir else None,
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=flags,
            )
        self.pid_file.write_text(str(proc.pid))
        return proc.pid

    def stop(self) -> bool:
        """Tree-kill the process. Returns False when nothing was running."""
        pid = self.pid()
        if pid is None or not self.is_running():
            self.pid_file.unlink(missing_ok=True)
            return False
        if os.name == "nt":
            # /T kills the tree (SAPI/child threads), /F is unconditional.
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
            )
        else:
            try:
                os.kill(pid, 15)
            except OSError:
                pass
        self.pid_file.unlink(missing_ok=True)
        return True

    def log_tail(self, lines: int = 20) -> str:
        """Last N lines of the process log ('' when no log yet)."""
        try:
            text = self.log_file.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return ""
        return "\n".join(text.splitlines()[-lines:])
