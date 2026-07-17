"""The watcher->tray toast handshake. This module is the ONLY owner of
the marker path, shape, and toast copy — the watcher imports
write_marker, the tray imports consume_marker + the strings. One toast
per week is structural: the watcher writes the marker on plan CREATE
only, and consume deletes it."""

from datetime import datetime, timezone
import json
from pathlib import Path

MARKER_RELPATH = Path("data/run/weekplan_ready.json")

TOAST_TITLE = "Race Engineer"
TOAST_MESSAGE = (
    "Week plan's ready — the week flips Tuesday. Open Race Engineer."
)


def write_marker(
    week_start: str, marker_path: Path = MARKER_RELPATH
) -> None:
    """Written by the watcher when a NEW week's plan is first saved."""
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(
        json.dumps({
            "week_start": week_start,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }),
        encoding="utf-8",
    )


def consume_marker(marker_path: Path = MARKER_RELPATH) -> dict | None:
    """Read-and-delete. None when absent; corrupt markers are deleted
    too (a bad marker must not toast forever)."""
    if not marker_path.exists():
        return None
    try:
        data = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = None
    try:
        marker_path.unlink()
    except OSError:
        pass
    return data if isinstance(data, dict) else None
