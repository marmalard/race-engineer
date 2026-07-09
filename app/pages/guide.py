"""Guide page — friend onboarding + founder reference.

Display-only: markdown constants rendered under themed section headers.
No logic, no state, nothing to test beyond import.
"""

from __future__ import annotations

import streamlit as st

from app.components.theme import section_header

_ONBOARDING = """
Race Engineer reads the telemetry your sim already records, pulls the
official results for your race, reconstructs what actually happened, and
debriefs you on it — like having an engineer on your pit wall. Four steps:

**1. Record telemetry while you race**

iRacing only writes a telemetry file when disk recording is on. Once your
session loads, press **Alt+L** — you'll see *"telemetry recording started"*
in the black box area. (If you run the Garage 61 agent, it already records
automatically and you can skip this.) It has to be an **official race**,
not a practice or AI session.

**2. Find your race file after the session**

Your telemetry lands in `Documents\\iRacing\\telemetry\\` as a `.ibt` file.
After a race weekend you'll usually see a few — the newest one from your
race session is the one you want. Files can be large (50–200 MB); that's
normal.

**3. Upload it on the Race Debrief page**

Go to **🏁 Race Debrief → Analyze a race**, drop the `.ibt` in, and hit
**Analyze**. The engineer fetches your official results, rebuilds the race
(positions, gaps, incidents, stints, pace), and writes it up. Takes a
little while for big files — that's the whole race being reconstructed.

**4. Read it, argue with it, keep it**

Under the charts you'll find the race story and the **Engineer's Debrief**.
Ask follow-up questions in the chat ("walk me through the lap 3 incident",
"should I have defended into the hairpin?"). When you're done, **Export**
gives you a markdown file of the whole debrief to keep or share.
"""

_HONEST_NOTES = """
- **The engineer only knows this race.** Everything it says comes from your
  telemetry and the official results — nothing else. If you ask something
  outside that data ("what tires was P3 on?"), it will say it doesn't have
  that, not guess.
- **"Pace-deserved position"** ranks your clean-lap pace against the rivals
  around you. It's the answer to *"where should my speed have put me?"* —
  the gap between that and where you finished is what the debrief digs into.
- **Numbers labeled "estimate"** (like time lost to an incident) are
  computed at lap granularity and marked as such. The engineer is honest
  about precision — a labeled estimate beats a confident guess.
- **A bad race makes the best debrief.** The engineer works for you: no
  scolding, no sugar-coating. A wrecked race is intelligence for the next
  one — that's the whole point.
"""

_FOUNDER_PAGES = """
| Page | What it does |
|---|---|
| 🏁 **Race Debrief** | The product: upload a race IBT → narrative + AI debrief + chat + export. Past debriefs re-open instantly from the second tab. |
| 🔭 **Scouting Report** | Pre-session briefing for a car/track combo — pace targets, key corners, community wisdom (Claude + web search). |
| ⏱ **Lap Coaching** | Post-session lap analysis vs your best/reference lap — loss regions, per-corner diagnosis, AI coaching narrative. |
"""

_FOUNDER_DATA = """
| Store | Contents |
|---|---|
| `data/races.db` | Race narratives, AI debriefs, chat transcripts — keyed `(subsession_id, cust_id)` |
| `data/race_cache/` | Raw Data API JSON per subsession (never re-fetched) |
| `data/tracks.db` | Tracks + corner names (lovely-track-data / Crew Chief seeded), plus session/lap history written by the watcher |
| `data/reference_laps.db` | Reference laps for coaching (G61 imports + personal bests) |
"""

_FOUNDER_TOOLS = """
- **🎛 Toolbox page** — start/stop/status for the live coach and watcher without touching a terminal, plus a live tail of session activity. Host machine only.
- **Live voice coach:** `.venv/Scripts/python.exe scripts/live_coach.py [--mute] [--corner-prompts]` — run with iRacing open; speaks lap debriefs between laps. Works at every track/car combo you have telemetry for (references come from the watcher below; a Garage 61 import beats your PB when present).
- **Telemetry watcher:** `.venv/Scripts/python.exe scripts/watch_telemetry.py [--watch]` — run after driving (or leave `--watch` polling alongside the sim). Every new session lands in history and your best valid full lap auto-promotes as the reference the live coach uses. Broken laps (tows, resets, laps that stop short of the line) are gated out.
- **Record race fixtures:** `.venv/Scripts/python.exe scripts/record_race_fixture.py <race.ibt>` — refresh the integration-test fixtures.
- **Serve to friends:** `tailscale serve 8501` (tailnet-only) or `tailscale funnel 8501` (public URL) with `streamlit run app/streamlit_app.py` behind it. The URL is the only access control — keep it unlisted.
- **Tests:** `.venv/Scripts/python.exe -m pytest -q`
"""


def render_guide_page() -> None:
    st.header("Guide")
    st.markdown(
        "Everything you need to get your first debrief — and the reference "
        "for the rest of the toolbox."
    )

    section_header("Get your first debrief")
    st.markdown(_ONBOARDING)

    section_header("How to read your debrief")
    st.markdown(_HONEST_NOTES)

    section_header("The rest of the app")
    st.markdown(_FOUNDER_PAGES)

    section_header("Where your data lives")
    st.markdown(_FOUNDER_DATA)

    section_header("Command line & hosting")
    st.markdown(_FOUNDER_TOOLS)
