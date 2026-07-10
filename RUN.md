# Running Race Engineer

The one-page "how do I start this" runbook. Reachable even when nothing is
running (that's the point — the in-app Guide can't help you until the app is up).

## The mental model

**Start the app once from a terminal. Start everything else from the Toolbox page.**

The app itself is a web server you have to launch from a terminal. Once it's up,
the watcher and live voice coach are buttons on the **🎛 Toolbox** page — no more
commands to remember.

---

## 1. Start the app (do this first, every time)

Open a terminal (PowerShell) **in the project folder** and run:

```powershell
.venv\Scripts\streamlit.exe run app\streamlit_app.py
```

Leave that window open — it *is* the app. Then open it in your browser:

- This machine: **http://localhost:8501**
- iPad / phone on the same Wi-Fi: the **Network URL** the terminal prints
  (e.g. `http://192.168.86.93:8501`)

To stop the app: close that terminal window (or Ctrl-C in it).

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
