"""Driver Profile page — racecraft tendencies + practice readiness.

Display only: everything is computed by core/profile (deterministic,
tested); this file renders it. No AI on this page.
"""

import time
from collections import Counter
from pathlib import Path

import streamlit as st

from app.components.host import (
    is_host,
    relative_time,
    watcher_last_activity,
    watcher_running,
)

from core.profile.builder import load_profile
from core.profile.models import RACECRAFT_MIN_RACES
from core.profile.render import (
    verdict_incidents,
    verdict_pace_vs_result,
    verdict_readiness,
    verdict_starts,
    verdict_trajectory,
)
from core.race.race_store import RaceStore
from core.track.track_db import TrackDB

RACES_DB = Path("data/races.db")
TRACKS_DB = Path("data/tracks.db")


def _resolve_cust_id(store: RaceStore) -> int | None:
    """Most-frequent cust_id in races.db; selectbox when several exist."""
    races = store.list_races()
    if not races:
        return None
    counts = Counter(r.cust_id for r in races)
    if len(counts) == 1:
        return next(iter(counts))
    names = {r.cust_id: r.driver_name for r in races}
    options = [c for c, _ in counts.most_common()]
    return st.selectbox(
        "Driver", options,
        format_func=lambda c: f"{names.get(c, c)} ({c})",
    )


def render_driver_profile_page() -> None:
    st.title("Driver Profile")
    st.markdown(
        "What your races say about how you race — and which combos are "
        "race-ready."
    )
    if is_host():
        last = watcher_last_activity()
        if watcher_running():
            when = relative_time(last, time.time()) if last else "just started"
            st.caption(
                f"History updates automatically — telemetry watcher "
                f"running, last activity {when}."
            )
        elif last is not None:
            st.caption(
                f"History updates automatically — telemetry watcher last "
                f"active {relative_time(last, time.time())}. Start it from "
                f"the Toolbox to keep this fresh."
            )
        else:
            st.caption(
                "The telemetry watcher hasn't run yet — start it from "
                "the Toolbox and this page fills itself in."
            )
    store = RaceStore(RACES_DB)
    track_db = TrackDB(TRACKS_DB)

    cust_id = _resolve_cust_id(store)
    profile = load_profile(store, track_db, cust_id or 0)

    if profile.races_captured == 0 and not profile.readiness:
        st.info(
            "No data yet. Races are captured automatically by the telemetry "
            "watcher after every official race, and practice sessions accrue "
            "the same way — drive, and this page fills itself in."
        )
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Races captured", profile.races_captured)
    c2.metric("Combos tracked", profile.combos_tracked)
    c3.metric("Clean practice laps",
              sum(c.valid_laps for c in profile.readiness))

    st.subheader("Racecraft")
    r = profile.racecraft
    for label, t, verdict in [
        ("Pace vs result", r.pace_vs_result, verdict_pace_vs_result),
        ("Starts", r.starts, verdict_starts),
        ("Incidents", r.incidents, verdict_incidents),
        ("Race trajectory", r.trajectory, verdict_trajectory),
    ]:
        with st.container(border=True):
            st.markdown(f"**{label}**")
            if t.enough_data:
                st.write(verdict(t))
                st.caption(f"Across {t.sample} races.")
            else:
                st.caption(
                    f"Collecting data — {t.sample} of "
                    f"{RACECRAFT_MIN_RACES} races captured."
                )

    st.subheader("Practice readiness")
    if not profile.readiness:
        st.caption("No practice history yet.")
    for combo in profile.readiness:
        if combo.enough_data:
            st.markdown(f"- {verdict_readiness(combo)}")
        else:
            # caption = greyed, matching the racecraft collecting-data style
            st.caption(
                f"{combo.track_name} / {combo.car} — collecting data "
                f"({combo.sessions} {'session' if combo.sessions == 1 else 'sessions'}, "
                f"{combo.valid_laps} {'clean lap' if combo.valid_laps == 1 else 'clean laps'})."
            )
