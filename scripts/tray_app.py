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
fragment kill catches it either way. Quit stops the whole rig (founder
call 2026-07-15: a closed tray must not leave invisible services);
'Stop everything' stops the rig but keeps the tray, and 'Open' revives
a stopped rig before opening the browser.

Pure and coupling-tested: spawn commands, icon image, menu spec, status
text. Thin untested I/O: the pystray loop and process starts/stops.
"""

from __future__ import annotations

import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime
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
    wait_for_port,
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


def open_app() -> None:
    """Revive the rig if it's down, THEN open the browser.

    'Open' must never point at a dead server — founder acceptance
    2026-07-15 found that Stop everything left no way back (the old
    action only opened a browser). Same idempotent semantics as tray
    startup; the wait keeps the browser from landing on a blank page.
    """
    _start_rig()
    wait_for_port(PORT, timeout_s=20.0)
    webbrowser.open(URL)


def _start_rig() -> None:
    """Launcher semantics: revive watcher, then the app if 8501 is dark."""
    _watcher_intended.set()
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


# --- watcher watchdog ------------------------------------------------------
# The recurring incident class on this rig is never 'watcher on when
# unwanted' -- it's 'watcher silently dead while the app looks fine'
# (2026-07-12, -14, -15: races went uncaptured). The tray is long-lived,
# so it revives a dead watcher every couple of minutes. The intent flag
# keeps it honest: a DELIBERATE stop (Stop watcher / Stop everything /
# Quit) clears it, and the watchdog never resurrects against your will.

WATCHDOG_INTERVAL_S = 120.0

_watcher_intended = threading.Event()


def watchdog_tick(intended: bool, proc, log_file: Path, now_iso: str) -> bool:
    """Revive the watcher when it should be running but isn't.

    Injected process/log/clock so tests never touch the live rig.
    Returns True when a revival was attempted.
    """
    if not intended or proc.is_running():
        return False
    try:
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(
                f"[tray watchdog] watcher was down - revived {now_iso}\n"
            )
    except OSError:
        pass  # the revival matters more than the log line
    proc.start()
    return True


def _watchdog_loop() -> None:
    while True:
        time.sleep(WATCHDOG_INTERVAL_S)
        try:
            proc = watcher_process()
            watchdog_tick(
                _watcher_intended.is_set(),
                proc,
                proc.log_file,
                datetime.now().isoformat(timespec="seconds"),
            )
        except Exception:  # noqa: BLE001 -- the watchdog itself never dies
            pass


def _start_watcher() -> None:
    _watcher_intended.set()
    watcher_process().start()


def _stop_watcher() -> None:
    _watcher_intended.clear()
    watcher_process().stop()


def _stop_rig() -> None:
    _watcher_intended.clear()
    _stop_everything()


@dataclass(frozen=True)
class MenuItemSpec:
    label: str
    action: Callable[..., None] | None


def menu_spec() -> list[MenuItemSpec]:
    """The tray menu as pure data (exact-label tested)."""
    return [
        MenuItemSpec("Open Race Engineer", _guard(open_app)),
        MenuItemSpec("Status", None),
        MenuItemSpec("Start voice coach",
                     _guard(lambda: coach_process().start())),
        MenuItemSpec("Stop voice coach",
                     _guard(lambda: coach_process().stop())),
        MenuItemSpec("Start watcher", _guard(_start_watcher)),
        MenuItemSpec("Stop watcher", _guard(_stop_watcher)),
        MenuItemSpec("Stop everything", _guard(_stop_rig)),
        # Quit tears the whole rig down (founder call 2026-07-15: a
        # closed tray must not leave invisible services running). The
        # action is bound in main() -- it needs the icon reference.
        MenuItemSpec("Quit (stops everything)", None),
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
        elif spec.action is None:  # Quit: stop the rig, then the tray
            def _quit(icon, _item) -> None:
                _guard(_stop_rig)()
                icon.stop()

            items.append(pystray.MenuItem(spec.label, _quit))
        else:
            items.append(pystray.MenuItem(spec.label, spec.action))
    icon = pystray.Icon(
        "race-engineer", make_icon_image(), "Race Engineer",
        pystray.Menu(*items),
    )
    if smoke:
        return 0
    _start_rig()
    threading.Thread(target=_watchdog_loop, daemon=True).start()
    icon.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(smoke="--smoke" in sys.argv))
