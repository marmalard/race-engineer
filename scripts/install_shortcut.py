"""One-time: create a Desktop shortcut to start-race-engineer.bat.

Run once:  .venv\\Scripts\\python.exe scripts\\install_shortcut.py

Uses the Windows Script Host COM object via PowerShell (no pywin32 dep) and
resolves the Desktop through the shell special folder so OneDrive-redirected
Desktops still work.

The target is cmd.exe /c <bat>, not the .bat itself: Windows only offers
'Pin to taskbar' on shortcuts whose target is an executable. Double-click
behavior is identical either way.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_BAT = _ROOT / "scripts" / "start-race-engineer.bat"
_SHORTCUT_NAME = "Race Engineer.lnk"
_CMD = r"C:\Windows\System32\cmd.exe"


def create_shortcut() -> str:
    """Create (or overwrite) the Desktop .lnk; returns its path."""
    ps = (
        "$desktop = [Environment]::GetFolderPath('Desktop'); "
        f"$lnk = Join-Path $desktop '{_SHORTCUT_NAME}'; "
        "$ws = New-Object -ComObject WScript.Shell; "
        "$s = $ws.CreateShortcut($lnk); "
        f"$s.TargetPath = '{_CMD}'; "
        f"$s.Arguments = '/c \"\"{_BAT}\"\"'; "
        f"$s.WorkingDirectory = '{_ROOT}'; "
        "$s.Description = 'Start Race Engineer (Streamlit + watcher)'; "
        "$s.Save(); "
        "Write-Output $lnk"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


if __name__ == "__main__":
    path = create_shortcut()
    print(f"Created shortcut: {path}")
