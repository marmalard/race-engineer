"""Host-vs-guest helpers and watcher freshness reads.

The app serves two audiences from one process: the founder's host
machine (telemetry folder, background processes) and guests over
tailscale. Everything host-only keys off telemetry_dir() existing —
previously a hardcoded founder path in two pages (spec A6).
"""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUN_DIR = _REPO_ROOT / "data" / "run"
_DEFAULT_TELEMETRY = Path.home() / "Documents" / "iRacing" / "telemetry"


def telemetry_dir() -> Path:
    """The iRacing telemetry folder (TELEMETRY_DIR env var overrides)."""
    override = os.environ.get("TELEMETRY_DIR")
    return Path(override) if override else _DEFAULT_TELEMETRY


def is_host() -> bool:
    """True when this process runs on the machine with the sim."""
    return telemetry_dir().exists()


def watcher_running() -> bool:
    """True when the telemetry watcher's managed process is alive."""
    from core.live.process_control import ManagedProcess

    # Command is irrelevant for a status read — liveness comes from the
    # PID file in run_dir (same name the Toolbox/launcher use).
    return ManagedProcess(
        "telemetry-watcher", ["status-only"], run_dir=_RUN_DIR
    ).is_running()


def watcher_last_activity(run_dir: Path | None = None) -> float | None:
    """mtime of the watcher log (last output); None when it never ran."""
    log = (run_dir or _RUN_DIR) / "telemetry-watcher.log"
    try:
        return log.stat().st_mtime
    except OSError:
        return None


def relative_time(then_s: float, now_s: float) -> str:
    """'just now' / '4m ago' / '2h ago' / '3d ago'."""
    delta = max(0, int(now_s - then_s))
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"
