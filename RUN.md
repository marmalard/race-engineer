# Running Race Engineer

The one-page "how do I start this" runbook. Reachable even when nothing is
running (that's the point — the in-app Guide can't help you until the app is up).

## The mental model

**Double-click the desktop shortcut. Start the live coach from the Toolbox page.**

The **Race Engineer** shortcut (Desktop / taskbar pin) starts the app AND the
telemetry watcher and opens the browser. The live voice coach stays a button on
the **🎛 Toolbox** page — you only want it running when you're in the car.

---

## 1. Start the app (do this first, every time)

Double-click **Race Engineer** (Desktop shortcut or taskbar pin). It:

- starts the telemetry watcher (auto-captures your sessions),
- starts the app — the console window that appears *is* the app,
- opens **http://localhost:8501** in your browser.

Double-clicking again while it's already running just re-opens the browser — safe.

- iPad / phone on the same Wi-Fi: **http://192.168.86.93:8501**

To stop **everything** (app + watcher + live coach): double-click
`scripts\stop-race-engineer.bat`. Closing the console window stops just the
app — the watcher keeps capturing.

<details>
<summary>No shortcut? Terminal fallback</summary>

```powershell
scripts\start-race-engineer.bat
# or the raw command (app only, no watcher):
.venv\Scripts\streamlit.exe run app\streamlit_app.py
```

Re-create the shortcut anytime: `.venv\Scripts\python.exe scripts\install_shortcut.py`
</details>

---

## 2. Everything else → the Toolbox page

Once the app is up, go to **🎛 Toolbox**. Each tool shows a status
(🟢 Running / ⚪ Stopped) and Start/Stop buttons:

| Want to… | Do this on the Toolbox page |
|---|---|
| Turn my races into references + history | Start the **Telemetry watcher** (leave it running) |
| Coach me by voice while I drive | Start the **Live voice coach** (iRacing open first) |
| Process races right now without leaving it running | **Scan now** under the watcher |

The Toolbox spawns these as detached background processes tracked by PID file,
so their status survives app restarts. Stop them with the same buttons.

---

## 3. Serve it to a friend (optional)

From the host PC, with the app already running:

```powershell
tailscale serve 8501     # tailnet-only (private)
tailscale funnel 8501    # public URL — you must run/authorize this yourself
```

The URL is the only access control — keep it unlisted.

---

## Command-line equivalents (if you'd rather not use Toolbox)

```powershell
# Telemetry watcher — poll after/while you drive
.venv\Scripts\python.exe scripts\watch_telemetry.py --watch

# Live voice coach — iRacing open; speaks lap debriefs between laps
.venv\Scripts\python.exe scripts\live_coach.py            # add --mute for text-only

# Run the tests
.venv\Scripts\python.exe -m pytest -q
```

> Note: if you start the watcher from a terminal **and** from Toolbox you'll get
> two of them. Pick one. The Toolbox tracks its own via `data\run\*.pid`.
