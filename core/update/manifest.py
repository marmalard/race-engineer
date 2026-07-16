"""What a release contains and how an install is recognized (B2).

RELEASE_ENTRIES is the whitelist shared by build_release (what goes in
the zip) and apply_update (what a swap replaces) -- data/, .env and
.venv are preserved across updates by NOT appearing here.
"""

from __future__ import annotations

from pathlib import Path

RELEASE_ENTRIES: tuple[str, ...] = (
    "app", "core", "scripts",
    "pyproject.toml", "uv.lock", ".python-version",
)


def is_installed_layout(code_root: Path) -> bool:
    """Return True when running from an installed tree (bundled uv.exe beside
    the code). Never true in a dev checkout -- the tray uses this to keep
    the update channel off dev rigs (git manages those).
    """
    return (Path(code_root) / "uv.exe").is_file()
