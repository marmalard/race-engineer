# Desktop Launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One double-click starts Streamlit + the telemetry watcher and opens the browser; one more double-click cleanly stops everything.

**Architecture:** Logic lives in Python (`scripts/launch.py`, `scripts/stop_all.py`, `scripts/install_shortcut.py`); `.bat` files are thin double-clickable wrappers. The launcher composes the existing `core.live.process_control.ManagedProcess` for the watcher and runs Streamlit as a console child so closing the window stops the app. Only the original logic (TCP port polling, PID-list parsing) is unit-tested; process/browser I/O is not.

**Tech Stack:** Python 3.14 (stdlib `socket`, `subprocess`, `webbrowser`), Windows `.bat`, PowerShell (WScript.Shell for the shortcut, CIM for process lookup), pytest.

---

## File Structure

- `scripts/launch.py` (new) — port helpers + `main()` that starts watcher, launches Streamlit, opens browser.
- `scripts/stop_all.py` (new) — stop managed tools + find/kill Streamlit; pure `_parse_pids` helper.
- `scripts/install_shortcut.py` (new, run once) — create the Desktop `.lnk`.
- `scripts/start-race-engineer.bat` (new) — wrapper → `launch.py`.
- `scripts/stop-race-engineer.bat` (new) — wrapper → `stop_all.py`.
- `tests/test_launch.py` (new) — `is_port_listening`, `wait_for_port`.
- `tests/test_stop_all.py` (new) — `_parse_pids`.

> Note: the spec described the stop logic as "a short Python snippet"; this plan realizes it as `scripts/stop_all.py` (parallel to `install_shortcut.py`) so the `.bat` stays a thin wrapper and the PID parsing is unit-testable.

---

## Task 1: Port helpers in `launch.py`

**Files:**
- Create: `scripts/launch.py`
- Test: `tests/test_launch.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_launch.py
"""Tests for the pure port helpers in scripts/launch.py."""

import importlib.util
import socket
import time
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "launch",
    Path(__file__).resolve().parent.parent / "scripts" / "launch.py",
)
launch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(launch)


def _free_port() -> int:
    """A port number nothing is listening on (bound then released)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_is_port_listening_true_for_open_socket():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert launch.is_port_listening(port) is True
    finally:
        srv.close()


def test_is_port_listening_false_for_closed_port():
    assert launch.is_port_listening(_free_port()) is False


def test_wait_for_port_returns_true_immediately_when_open():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert launch.wait_for_port(port, timeout_s=1.0, interval_s=0.05) is True
    finally:
        srv.close()


def test_wait_for_port_times_out_for_closed_port():
    start = time.monotonic()
    ok = launch.wait_for_port(_free_port(), timeout_s=0.2, interval_s=0.05)
    elapsed = time.monotonic() - start
    assert ok is False
    assert elapsed < 1.0  # honored the short timeout, did not hang
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_launch.py -v`
Expected: FAIL — `scripts/launch.py` does not exist / attributes not defined.

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/launch.py
"""One-click launcher for the Race Engineer rig.

Double-clicked via scripts/start-race-engineer.bat. Starts the telemetry
watcher (detached, managed), launches Streamlit as a child of this console,
waits for the port, and opens the browser. Closing the console stops
Streamlit; the watcher survives (stop it from the Toolbox or with
stop-race-engineer.bat).

Only the port helpers are original logic and unit-tested; process spawning
and browser opening are thin I/O over ManagedProcess / subprocess.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.live.process_control import ManagedProcess  # noqa: E402

HOST = "127.0.0.1"
PORT = 8501
URL = f"http://localhost:{PORT}"
VENV_PY = _ROOT / ".venv" / "Scripts" / "python.exe"
PORT_WAIT_TIMEOUT_S = 15.0
PORT_POLL_INTERVAL_S = 0.3


def is_port_listening(port: int, host: str = HOST) -> bool:
    """True when a TCP connect to (host, port) succeeds."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def wait_for_port(
    port: int,
    timeout_s: float = PORT_WAIT_TIMEOUT_S,
    interval_s: float = PORT_POLL_INTERVAL_S,
    host: str = HOST,
) -> bool:
    """Poll until the port is listening or the timeout elapses.

    Returns True as soon as the port accepts a connection, False if the
    deadline passes first.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if is_port_listening(port, host):
            return True
        time.sleep(interval_s)
    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_launch.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/launch.py tests/test_launch.py
git commit -m 'feat(launcher): TCP port helpers for launch.py'
```

---

## Task 2: `main()` — watcher + Streamlit + browser

**Files:**
- Modify: `scripts/launch.py` (append `_watcher()` and `main()`)

No unit test — this is process/browser I/O. Verified by the manual smoke test in Task 7.

- [ ] **Step 1: Append the wiring to `scripts/launch.py`**

```python
def _watcher() -> ManagedProcess:
    return ManagedProcess(
        "telemetry-watcher",
        [str(VENV_PY), "scripts/watch_telemetry.py", "--watch"],
        workdir=_ROOT,
    )


def main() -> int:
    # Idempotency: if the app is already up, just surface it.
    if is_port_listening(PORT):
        print(f"Race Engineer already running at {URL} — opening browser.")
        webbrowser.open(URL)
        return 0

    # Watcher first (detached, idempotent). A watcher failure must never
    # block the app — it can be started later from the Toolbox.
    try:
        pid = _watcher().start()
        print(f"Telemetry watcher running (pid {pid}).")
    except Exception as exc:  # noqa: BLE001 - log and continue
        print(f"WARNING: watcher failed to start ({exc}); continuing.")

    # Streamlit as a child of this console so closing the window stops it.
    print("Starting Streamlit ...")
    proc = subprocess.Popen(
        [str(VENV_PY), "-m", "streamlit", "run",
         "app/streamlit_app.py", "--server.headless", "true"],
        cwd=str(_ROOT),
    )

    if wait_for_port(PORT):
        print(f"Opening {URL}")
    else:
        print(f"Streamlit slow to start; opening {URL} anyway — refresh if blank.")
    webbrowser.open(URL)

    proc.wait()
    return proc.returncode or 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Verify the module still imports and tests pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_launch.py -v`
Expected: PASS (4 tests — the new code is import-safe, `main()` not called).

- [ ] **Step 3: Commit**

```bash
git add scripts/launch.py
git commit -m 'feat(launcher): main() starts watcher + Streamlit, opens browser'
```

---

## Task 3: `start-race-engineer.bat`

**Files:**
- Create: `scripts/start-race-engineer.bat`

- [ ] **Step 1: Write the wrapper**

```bat
@echo off
REM One-click launcher — starts Streamlit + telemetry watcher, opens the browser.
REM Closing this window stops Streamlit; the watcher keeps running (use
REM stop-race-engineer.bat or the Toolbox Stop button to stop it).
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo .venv not found. Run "uv sync" in the repo root first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" scripts\launch.py
```

- [ ] **Step 2: Smoke-run the wrapper (with a fresh port)**

First ensure nothing is on 8501 (stop any running app). Then:
Run: `scripts\start-race-engineer.bat`
Expected: prints "Telemetry watcher running (pid ...)", "Starting Streamlit ...", "Opening http://localhost:8501"; browser opens the app. Leave it running for Task 7, or Ctrl-C to stop.

- [ ] **Step 3: Commit**

```bash
git add scripts/start-race-engineer.bat
git commit -m 'feat(launcher): start-race-engineer.bat wrapper'
```

---

## Task 4: `stop_all.py` — stop managed tools + Streamlit

**Files:**
- Create: `scripts/stop_all.py`
- Test: `tests/test_stop_all.py`

- [ ] **Step 1: Write the failing test for the PID parser**

```python
# tests/test_stop_all.py
"""Tests for the pure PID-list parser in scripts/stop_all.py."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "stop_all",
    Path(__file__).resolve().parent.parent / "scripts" / "stop_all.py",
)
stop_all = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stop_all)


def test_parse_pids_extracts_integers():
    out = "1234\n5678\n"
    assert stop_all._parse_pids(out) == [1234, 5678]


def test_parse_pids_ignores_blank_and_nonnumeric_lines():
    out = "\n  9012 \nProcessId\n---\n3456\n"
    assert stop_all._parse_pids(out) == [9012, 3456]


def test_parse_pids_empty_output():
    assert stop_all._parse_pids("") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stop_all.py -v`
Expected: FAIL — `scripts/stop_all.py` does not exist.

- [ ] **Step 3: Write the implementation**

```python
# scripts/stop_all.py
"""Clean shutdown for the Race Engineer rig.

Invoked by stop-race-engineer.bat. Stops the telemetry-watcher and
live-coach ManagedProcesses (PID-file tree-kill), then finds Streamlit
(no PID file — it runs as the launcher console's child) by command line
and tree-kills it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.live.process_control import ManagedProcess  # noqa: E402

_MANAGED = ("telemetry-watcher", "live-coach")
_STREAMLIT_MARKER = "streamlit run app/streamlit_app.py"


def _parse_pids(stdout: str) -> list[int]:
    """Integers from a newline-separated PID list; non-numeric lines ignored."""
    pids: list[int] = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def stop_managed() -> None:
    for name in _MANAGED:
        proc = ManagedProcess(name, [], workdir=_ROOT)
        if proc.stop():
            print(f"Stopped {name}.")
        else:
            print(f"{name} was not running.")


def _streamlit_pids() -> list[int]:
    """PIDs of python processes running the app's Streamlit server."""
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -like '*" + _STREAMLIT_MARKER + "*' } | "
        "ForEach-Object { $_.ProcessId }"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True,
    )
    return _parse_pids(result.stdout)


def stop_streamlit() -> None:
    pids = _streamlit_pids()
    if not pids:
        print("Streamlit was not running.")
        return
    for pid in pids:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True
        )
        print(f"Stopped Streamlit (pid {pid}).")


def main() -> int:
    stop_managed()
    stop_streamlit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stop_all.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/stop_all.py tests/test_stop_all.py
git commit -m 'feat(launcher): stop_all.py stops managed tools + Streamlit'
```

---

## Task 5: `stop-race-engineer.bat`

**Files:**
- Create: `scripts/stop-race-engineer.bat`

- [ ] **Step 1: Write the wrapper**

```bat
@echo off
REM Clean shutdown — stops the telemetry watcher, live coach, and Streamlit.
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo .venv not found. Run "uv sync" in the repo root first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" scripts\stop_all.py
```

- [ ] **Step 2: Commit**

```bash
git add scripts/stop-race-engineer.bat
git commit -m 'feat(launcher): stop-race-engineer.bat wrapper'
```

---

## Task 6: `install_shortcut.py` — create the Desktop shortcut

**Files:**
- Create: `scripts/install_shortcut.py`

No unit test — it is a one-time COM/PowerShell side effect. Verified by running it once and checking the Desktop.

- [ ] **Step 1: Write the script**

```python
# scripts/install_shortcut.py
"""One-time: create a Desktop shortcut to start-race-engineer.bat.

Run once:  .venv\\Scripts\\python.exe scripts\\install_shortcut.py

Uses the Windows Script Host COM object via PowerShell (no pywin32 dep) and
resolves the Desktop through the shell special folder so OneDrive-redirected
Desktops still work.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_BAT = _ROOT / "scripts" / "start-race-engineer.bat"
_SHORTCUT_NAME = "Race Engineer.lnk"


def create_shortcut() -> str:
    ps = (
        "$desktop = [Environment]::GetFolderPath('Desktop'); "
        f"$lnk = Join-Path $desktop '{_SHORTCUT_NAME}'; "
        "$ws = New-Object -ComObject WScript.Shell; "
        "$s = $ws.CreateShortcut($lnk); "
        f"$s.TargetPath = '{_BAT}'; "
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
```

- [ ] **Step 2: Run it once**

Run: `.venv\Scripts\python.exe scripts\install_shortcut.py`
Expected: prints `Created shortcut: C:\Users\antho\...\Desktop\Race Engineer.lnk`; the shortcut appears on the Desktop.

- [ ] **Step 3: Commit**

```bash
git add scripts/install_shortcut.py
git commit -m 'feat(launcher): install_shortcut.py creates the Desktop .lnk'
```

---

## Task 7: Full manual smoke test + docs

**Files:**
- Modify: `CLAUDE.md` (Current Status — add a launcher line)

- [ ] **Step 1: End-to-end smoke test**

1. Ensure nothing is on 8501 and no watcher/live-coach running (run `scripts\stop-race-engineer.bat` once).
2. Double-click the Desktop **Race Engineer** shortcut.
   - Expected: a console appears, watcher starts, Streamlit boots, browser opens `http://localhost:8501`.
3. In the app, open the **Toolbox** page — the telemetry-watcher shows **running**.
4. Double-click the shortcut again (idempotency).
   - Expected: the *second* console prints "already running ... opening browser" and exits; only one Streamlit is up.
5. Run `scripts\stop-race-engineer.bat`.
   - Expected: prints "Stopped telemetry-watcher.", "live-coach was not running.", "Stopped Streamlit (pid ...)."; the browser tab errors on refresh (app down).
6. Confirm no leftover processes:
   Run: `powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'streamlit|watch_telemetry|live_coach' } | Select-Object ProcessId,CommandLine"`
   Expected: no rows.

- [ ] **Step 2: Run the full test suite (no regressions)**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: previous pass count + 7 new tests (4 in test_launch, 3 in test_stop_all), 0 failures.

- [ ] **Step 3: Add a CLAUDE.md Current Status note**

Add under an appropriate Current Status subsection:

```markdown
- **Desktop launcher** (branch desktop-launcher): double-click `Race Engineer` shortcut → `scripts/start-race-engineer.bat` → `scripts/launch.py` starts the telemetry watcher (managed) + Streamlit (console child) and opens the browser; idempotent on port 8501. `scripts/stop-race-engineer.bat` → `scripts/stop_all.py` stops watcher + live-coach (ManagedProcess) and tree-kills Streamlit (found by command-line match). Live coach stays a Toolbox button. Shortcut created once via `scripts/install_shortcut.py`.
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m 'docs: note desktop launcher in Current Status'
```

---

## Self-Review

**Spec coverage:**
- Idempotency guard → Task 2 `main()` + Task 7 step 4. ✓
- Start watcher via ManagedProcess → Task 2 `_watcher()`. ✓
- Streamlit as console child → Task 2. ✓
- Poll port then open browser → Task 1 + Task 2. ✓
- `start-race-engineer.bat` → Task 3. ✓
- `stop-race-engineer.bat` + streamlit-by-command-line kill → Tasks 4–5. ✓
- Desktop `.lnk` via one-time helper → Task 6. ✓
- `.venv` missing → clear message → Tasks 3 & 5 guard. ✓
- Tests for `is_port_listening` / `wait_for_port` → Task 1; PID parser → Task 4. ✓
- Lifecycle table (watcher survives console close; stop.bat closes gap) → Task 7 smoke test. ✓

**Placeholder scan:** none — every code/command step is complete.

**Type consistency:** `is_port_listening(port, host)` and `wait_for_port(port, timeout_s, interval_s, host)` used identically in tests and impl. `_parse_pids(stdout) -> list[int]`, `ManagedProcess(name, command, workdir=...)` and `.stop()` match existing `process_control.py`. `_STREAMLIT_MARKER` = `"streamlit run app/streamlit_app.py"` matches the Streamlit command in `main()`.
