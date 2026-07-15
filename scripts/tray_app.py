"""System-tray controller for the Race Engineer rig (B1).

Absorbs the console launcher's job: on start it revives the watcher and
the app (idempotent, launch.py semantics), then sits in the tray with
Start/Stop for the voice coach and watcher, browser open, live status,
and a full stop. No console windows -- run via pythonw.exe
(scripts/start-tray.bat).

Composes ManagedProcess + launch/stop logic unchanged (spec B1). The
voice coach is NEVER auto-started -- starting it is a deliberate click
(locked decision 2026-07-14). Streamlit runs detached under a PID file
('streamlit-app') instead of as a console child; stop_all's cmdline
fragment kill catches it either way.

Pure and coupling-tested: spawn commands, icon image, menu spec, status
text. Thin untested I/O: the pystray loop and process starts/stops.
"""

from __future__ import annotations

import sys
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.live.process_control import ManagedProcess  # noqa: E402
from scripts.launch import (  # noqa: E402
    PORT,
    STREAMLIT_CMD,
    URL,
    _watcher,
    is_port_listening,
)

_RUN_DIR = _ROOT / "data" / "run"
VENV_PY = _ROOT / ".venv" / "Scripts" / "python.exe"

# Round-2 CLI: bare command == voice on, corner prompts ON. Coupling-
# tested against live_coach.build_parser() (the 2026-07-14 Toolbox
# flag-drift lesson -- a stale flag kills the coach at startup invisibly).
COACH_CMD = [str(VENV_PY), "scripts/live_coach.py"]


def coach_process() -> ManagedProcess:
    return ManagedProcess(
        "live-coach", COACH_CMD, run_dir=_RUN_DIR, workdir=_ROOT
    )


def watcher_process() -> ManagedProcess:
    return _watcher()  # launch.py's -- identical command, PID file, run_dir


def app_process() -> ManagedProcess:
    return ManagedProcess(
        "streamlit-app", STREAMLIT_CMD, run_dir=_RUN_DIR, workdir=_ROOT
    )


def make_icon_image(size: int = 64):
    """Checkered-flag tray icon, drawn in code (no asset file)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (size, size), "#0e1116")
    draw = ImageDraw.Draw(img)
    cell = size // 4
    for row in range(4):
        for col in range(4):
            if (row + col) % 2 == 0:
                draw.rectangle(
                    [
                        col * cell,
                        row * cell,
                        (col + 1) * cell - 1,
                        (row + 1) * cell - 1,
                    ],
                    fill="#00d17a",
                )
    return img


def status_text(
    *, app_up: bool, watcher_up: bool, watcher_when: str | None, coach_up: bool
) -> str:
    """One status line from injected facts (pure -- the tray reads the
    facts, this formats them)."""
    watcher = (
        f"Watcher: running ({watcher_when})"
        if watcher_up and watcher_when
        else ("Watcher: running" if watcher_up else "Watcher: stopped")
    )
    return " \xb7 ".join([
        "App: running" if app_up else "App: stopped",
        watcher,
        "Coach: running" if coach_up else "Coach: stopped",
    ])


def _live_status(_item=None) -> str:
    """Status line from the live rig (called by pystray on menu open)."""
    from app.components.host import (
        relative_time,
        watcher_last_activity,
        watcher_running,
    )

    watcher_up = watcher_running()
    last = watcher_last_activity()
    return status_text(
        app_up=is_port_listening(PORT),
        watcher_up=watcher_up,
        watcher_when=(
            relative_time(last, time.time()) if (watcher_up and last) else None
        ),
        coach_up=coach_process().is_running(),
    )


# --- actions (thin I/O; failures must never kill the tray) ----------------

def _guard(fn: Callable[[], object]) -> Callable[..., None]:
    def run(*_args) -> None:
        try:
            fn()
        except Exception:  # noqa: BLE001 -- tray survives any action failure
            pass

    return run


def _open_app() -> None:
    webbrowser.open(URL)


def _start_rig() -> None:
    """Launcher semantics: revive watcher, then the app if 8501 is dark."""
    try:
        watcher_process().start()
    except Exception:  # noqa: BLE001 -- watcher failure must not block the app
        pass
    if not is_port_listening(PORT):
        app_process().start()


def _stop_everything() -> None:
    from scripts.stop_all import stop_managed, stop_streamlit

    stop_managed()
    stop_streamlit()


@dataclass(frozen=True)
class MenuItemSpec:
    label: str
    action: Callable[..., None] | None


def menu_spec() -> list[MenuItemSpec]:
    """The tray menu as pure data (exact-label tested)."""
    return [
        MenuItemSpec("Open Race Engineer", _guard(_open_app)),
        MenuItemSpec("Status", None),
        MenuItemSpec("Start voice coach",
                     _guard(lambda: coach_process().start())),
        MenuItemSpec("Stop voice coach",
                     _guard(lambda: coach_process().stop())),
        MenuItemSpec("Start watcher",
                     _guard(lambda: watcher_process().start())),
        MenuItemSpec("Stop watcher",
                     _guard(lambda: watcher_process().stop())),
        MenuItemSpec("Stop everything", _guard(_stop_everything)),
        MenuItemSpec("Quit (leave services running)", None),  # bound in main()
    ]


def main(smoke: bool = False) -> int:
    """Start the rig, then run the tray icon (blocking).

    smoke=True skips process starts and the blocking loop -- it builds
    the icon + menu and returns 0 (used by the smoke test; never touches
    the live rig).
    """
    import pystray

    items = []
    for spec in menu_spec():
        if spec.label == "Status":
            items.append(pystray.MenuItem(_live_status, None, enabled=False))
        elif spec.action is None:  # Quit
            items.append(
                pystray.MenuItem(spec.label, lambda icon, _i: icon.stop())
            )
        else:
            items.append(pystray.MenuItem(spec.label, spec.action))
    icon = pystray.Icon(
        "race-engineer", make_icon_image(), "Race Engineer",
        pystray.Menu(*items),
    )
    if smoke:
        return 0
    _start_rig()
    icon.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(smoke="--smoke" in sys.argv))
