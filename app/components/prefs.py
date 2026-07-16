"""Tiny server-side UI preference store (host default).

The unit toggle lives in st.session_state, which is per browser tab and
resets on every reload. This persists the last choice to
data/ui_prefs.json so a new session starts where the last one left off.
Deliberately a HOST-level default, not per-viewer: last writer wins —
fine for one founder plus a guest; per-user prefs need cookies/auth
(Phase 6 territory).
"""

from __future__ import annotations

import json
from pathlib import Path

_PREFS_PATH = Path("data/ui_prefs.json")
_VALID_UNITS = ("Metric", "Imperial")


def load_unit_system(path: Path | None = None) -> str:
    """Last saved unit system; 'Metric' when unset, corrupt, or invalid."""
    p = path or _PREFS_PATH
    try:
        value = json.loads(p.read_text(encoding="utf-8")).get("unit_system")
    except (OSError, ValueError, AttributeError):
        return "Metric"
    return value if value in _VALID_UNITS else "Metric"


def save_unit_system(value: str, path: Path | None = None) -> None:
    """Persist the unit choice; never raises (display pref, best effort)."""
    if value not in _VALID_UNITS:
        return
    p = path or _PREFS_PATH
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"unit_system": value}), encoding="utf-8")
    except OSError:
        pass
