"""Create the Desktop shortcut for Race Engineer.

Run once:  .venv\\Scripts\\python.exe scripts\\install_shortcut.py [--target tray]

Targets (B2 spec 6):
  launcher (default) -- cmd.exe /c start-race-engineer.bat, the dev rig's
      console launcher. cmd.exe as target keeps 'Pin to taskbar' offered.
  tray -- pythonw.exe scripts/tray_app.py directly: no console flash, an
      exe target (pinnable). Used by the installer.

Uses the Windows Script Host COM object via PowerShell (no pywin32 dep)
and resolves the Desktop through the shell special folder so
OneDrive-redirected Desktops still work.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_BAT = _ROOT / "scripts" / "start-race-engineer.bat"
_SHORTCUT_NAME = "Race Engineer.lnk"
_CMD = r"C:\Windows\System32\cmd.exe"
_ICON = _ROOT / "data" / "tray_icon.ico"
_ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)]


@dataclass(frozen=True)
class ShortcutSpec:
    target_path: str
    arguments: str
    description: str


def shortcut_spec(target: str = "launcher") -> ShortcutSpec:
    """Pure shortcut definition per target (coupling-tested)."""
    if target == "launcher":
        return ShortcutSpec(
            target_path=_CMD,
            arguments=f'/c ""{_BAT}""',
            description="Start Race Engineer (Streamlit + watcher)",
        )
    if target == "tray":
        pythonw = _ROOT / ".venv" / "Scripts" / "pythonw.exe"
        tray = _ROOT / "scripts" / "tray_app.py"
        return ShortcutSpec(
            target_path=str(pythonw),
            arguments=f'"{tray}"',
            description="Start Race Engineer (system tray)",
        )
    raise ValueError(f"unknown shortcut target: {target!r}")


def ensure_icon() -> Path:
    """Render the tray's checkered-flag drawing to data/tray_icon.ico.

    The image is imported from tray_app (not copied) so the Desktop icon
    can never drift from the tray icon.
    """
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from scripts.tray_app import make_icon_image

    img = make_icon_image(256)
    _ICON.parent.mkdir(parents=True, exist_ok=True)
    img.save(_ICON, format="ICO", sizes=_ICO_SIZES)
    return _ICON


def create_shortcut(target: str = "launcher") -> str:
    """Create (or overwrite) the Desktop .lnk; returns its path."""
    spec = shortcut_spec(target)
    try:
        icon_clause = f"$s.IconLocation = '{ensure_icon()},0'; "
    except Exception:  # noqa: BLE001 -- a default icon beats no shortcut
        icon_clause = ""
    ps = (
        "$desktop = [Environment]::GetFolderPath('Desktop'); "
        f"$lnk = Join-Path $desktop '{_SHORTCUT_NAME}'; "
        "$ws = New-Object -ComObject WScript.Shell; "
        "$s = $ws.CreateShortcut($lnk); "
        f"$s.TargetPath = '{spec.target_path}'; "
        f"$s.Arguments = '{spec.arguments}'; "
        f"$s.WorkingDirectory = '{_ROOT}'; "
        f"$s.Description = '{spec.description}'; "
        f"{icon_clause}"
        "$s.Save(); "
        "Write-Output $lnk"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create the Desktop shortcut.")
    parser.add_argument(
        "--target", choices=("launcher", "tray"), default="launcher",
        help="what the shortcut starts (default: the console launcher)",
    )
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    path = create_shortcut(args.target)
    print(f"Created shortcut: {path}")
