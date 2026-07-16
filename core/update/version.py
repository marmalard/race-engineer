"""App version source of truth for the update channel (B2, spec 5.1).

The [project] version in pyproject.toml is the single source; the
status strip, Setup page footer, update check, and build_release all
read it from here.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_CODE_ROOT = Path(__file__).resolve().parent.parent.parent


def get_version(pyproject: Path | None = None) -> str:
    """Return the [project] version string from pyproject.toml."""
    path = pyproject if pyproject is not None else _CODE_ROOT / "pyproject.toml"
    with open(path, "rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def bump_version(version: str, part: str) -> str:
    """Return an incremented version string.

    '0.1.0' + 'patch' -> '0.1.1'; 'minor' resets patch to 0.
    Raises ValueError on a malformed version or unknown part name.
    """
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if match is None:
        raise ValueError(f"not an x.y.z version: {version!r}")
    major, minor, patch = (int(g) for g in match.groups())
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"unknown bump part: {part!r}")
