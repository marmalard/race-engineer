# Desktop Launcher — one-click start/stop for the rig

**Date:** 2026-07-12
**Status:** Design approved, pending spec review
**Branch:** (new) `desktop-launcher`

## Problem

Starting a testing session takes a terminal and a remembered command. The Toolbox
page already exposes start/stop/status buttons for the watcher and live coach, but
*something* has to launch Streamlit first — a chicken-and-egg step that keeps the
whole rig tied to a terminal. Prior sessions have also left **orphan processes**
(duplicate watchers / live-coaches, no Streamlit) when tools were started but never
shut down cleanly.

Goal: sit down, double-click, drive. Shut down with one more double-click.

## Scope

In scope:
- A double-clickable launcher that starts Streamlit + the telemetry watcher and opens
  the browser.
- A double-clickable clean-shutdown that stops the managed tools and Streamlit.
- A Desktop shortcut pointing at the launcher.

Explicitly out of scope:
- The **live coach** stays a Toolbox button — it is deliberate (driving-only, may want
  `--mute` / cue flags). The launcher does not touch it on start.
- Always-on durability (Task Scheduler) — noted in project memory as a separate,
  queued concern. This launcher is the manual, in-control version.

## Design

Logic lives in Python (tested); the `.bat` files are thin wrappers. This mirrors the
project rule "no business logic in Streamlit files."

### Components

**`scripts/launch.py`** — the launcher. Flow:
1. **Idempotency guard.** If `localhost:8501` is already serving, open the browser and
   exit 0. Prevents a second Streamlit trying to bind the port (double double-click, or
   an already-running instance).
2. **Start the watcher** via the existing `ManagedProcess("telemetry-watcher", …)` —
   idempotent by its own PID-file check, so Toolbox status/stop stay accurate. Same
   command the Toolbox uses: `[venv_py, "scripts/watch_telemetry.py", "--watch"]`.
3. **Launch Streamlit** as a *child* of this process (not detached):
   `venv_py -m streamlit run app/streamlit_app.py --server.headless true`. Because it is
   a child, closing the console window cleanly stops the app.
4. **Wait for the port**, then open the browser. Poll `is_port_listening(8501)` up to
   ~15s; open the browser the moment it is up (no arbitrary sleep, no
   connection-refused flash). If the timeout elapses, open the browser anyway and let
   the user refresh.
5. **Wait** on the Streamlit process. The console is the app's live log + handle.

**`scripts/start-race-engineer.bat`** — one-liner wrapper: `cd /d "%~dp0.."` to the repo
root, then `.venv\Scripts\python.exe scripts\launch.py`. Target of the Desktop shortcut.

**`scripts/stop-race-engineer.bat`** — clean shutdown. Runs a short Python snippet that
calls `ManagedProcess(...).stop()` for `telemetry-watcher` and `live-coach` (tree-kill
via the existing code). Streamlit is *not* a `ManagedProcess` (it has no PID file — it
runs as the launcher console's child), so it is found by scanning for the python process
whose command line contains `streamlit run app/streamlit_app.py` and tree-killing it
(`taskkill /PID <pid> /T /F`). Normally closing the launcher console already stops
Streamlit; this handles the case where the console was left open or you want everything
gone in one click. Answers the orphan-on-console-close tradeoff: one double-click stops
everything.

**Desktop shortcut** — a `.lnk` on the user's Desktop pointing at
`start-race-engineer.bat`, working directory = repo root. Created by a one-time helper
(`scripts/install_shortcut.py`, run once via PowerShell `WScript.Shell`). Uses the
default icon — no `.ico` exists in the repo today; icon is best-effort and non-blocking.

### Lifecycle summary

| Action | Streamlit | Watcher | Live coach |
|---|---|---|---|
| Double-click launcher | starts (console child) | starts (detached, managed) | untouched |
| Close console window | dies (clean) | keeps running (detached) | untouched |
| Double-click stop | killed (tree) | stopped (managed) | stopped (managed) |
| Toolbox Stop buttons | — | stops | stops |

The watcher surviving a console close is the accepted tradeoff for auto-start; the stop
`.bat` and the Toolbox buttons both close that gap.

### Testable units (`tests/test_launch.py`)

- `is_port_listening(port: int, host: str = "127.0.0.1") -> bool` — true when a TCP
  connect succeeds. Test: bind a throwaway socket on an ephemeral port → listening;
  a closed port → not listening.
- `wait_for_port(port, timeout_s, interval_s) -> bool` — polls `is_port_listening`
  until true or timeout. Test: returns True quickly for an open port; returns False
  after timeout for a closed one (use a tiny timeout so the test is fast).

Process-spawning and browser-opening are thin I/O over `ManagedProcess` /
`subprocess` / `webbrowser` and stay untested (as `ManagedProcess` I/O already is).

## Error handling

- **Port already in use** → idempotency guard turns it into "open browser, exit" rather
  than a crash.
- **Watcher fails to start** → `ManagedProcess.start()` returns/raises as it does today;
  the launcher logs and still brings up Streamlit (the app is the priority; the watcher
  can be started from the Toolbox).
- **Streamlit exits nonzero** → the console shows its output; `launch.py` exits with the
  same code.
- **`.venv` missing** → the `.bat` reports a clear "run `uv sync` first" message instead
  of a raw Python error. (Guard on `.venv\Scripts\python.exe` existing.)

## Files

- `scripts/launch.py` (new)
- `scripts/start-race-engineer.bat` (new)
- `scripts/stop-race-engineer.bat` (new)
- `scripts/install_shortcut.py` (new, run once)
- `tests/test_launch.py` (new)

No changes to existing modules — the launcher composes `ManagedProcess` as-is.
