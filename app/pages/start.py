"""Start page — the state-aware landing surface (A1).

North-star down-payment: before showing entry paths, check state and
lead with the one thing that matters now — an undebriefed captured
race beats everything. Display-only: state checks are thin reads over
RaceStore and the watcher's run files; all copy is founder-reviewable
draft (product voice).
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import streamlit as st

from app.components.host import (
    is_host,
    relative_time,
    telemetry_dir,
    watcher_last_activity,
    watcher_running,
)
from app.components.sample import load_sample_narrative
from app.components.theme import section_header
from app.navigation import page_for
from core.race.race_store import RaceStore, StoredRaceMeta
from core.update.version import get_version

_REPO_ROOT = Path(__file__).resolve().parents[2]

# DRAFT copy — founder reviews wording before merge (spec open item).
INTRO = (
    "Your personal race engineer for iRacing. **Never start a race "
    "blind** — the briefing reads the field before you load in. "
    "**Never race alone** — the debrief and the voice coach sit on "
    "your pit wall. Every race you run makes them smarter."
)


def pick_undebriefed(
    metas: list[StoredRaceMeta], has_debrief
) -> StoredRaceMeta | None:
    """Newest captured race with no AI debrief yet, else None.

    has_debrief: callable(subsession_id, cust_id) -> bool. Pure logic
    with injected store access — unit-tested without a database. Any
    store error means no lead card, never a broken landing page.
    """
    try:
        for meta in metas:  # list_races is newest-first (created_at DESC)
            if not has_debrief(meta.subsession_id, meta.cust_id):
                return meta
    except Exception:  # noqa: BLE001 — landing page must always render
        return None
    return None


@st.cache_data(show_spinner=False)
def _app_version() -> str:
    """git short SHA of the running checkout; 'unknown' off-git."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=_REPO_ROOT, timeout=3,
        )
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001 — cosmetic only
        return "unknown"


def _open_stored_race(meta: StoredRaceMeta) -> None:
    store = RaceStore()
    st.session_state["race_narrative"] = store.get_race(
        meta.subsession_id, meta.cust_id
    )
    st.session_state["sample_mode"] = False


def render_start_page() -> None:
    st.header("Start")
    st.markdown(INTRO)

    # --- State-aware lead: the one thing that matters now ---------------
    store = RaceStore()
    try:
        lead = pick_undebriefed(
            store.list_races(),
            lambda s, c: store.get_debrief(s, c) is not None,
        )
    except Exception:  # noqa: BLE001 — empty state is a valid state
        lead = None

    if lead is not None:
        with st.container(border=True):
            # Partial captures (results not posted yet) carry a zero
            # rating delta — showing "+0 iR" would read as a real result.
            ir_txt = (
                f", {lead.irating_delta:+d} iR" if lead.irating_delta else ""
            )
            st.markdown(
                f"**Your race at {lead.track_name} on "
                f"{lead.session_date[:10]} is ready to debrief** — "
                f"P{lead.finish_position}{ir_txt}."
            )
            if st.button("Open the debrief", type="primary"):
                _open_stored_race(lead)
                st.switch_page(page_for("debrief"))

    # Week-plan teaser — the push's second touchpoint.
    try:
        from core.weekplan.render import headline as _wp_headline
        from app.pages.week_plan import _current_week_plan
        from core.weekplan.store import WeekPlanStore

        wp = _current_week_plan(WeekPlanStore())
    except Exception:  # noqa: BLE001 — landing page must always render
        wp = None
    if wp is not None:
        with st.container(border=True):
            st.markdown(f"**{_wp_headline(wp)}**")
            st.page_link(page_for("week-plan"), label="Open the week plan")

    # --- Entry paths (fallback for empty state + the guest path) --------
    section_header("Where to next")
    col1, col2 = st.columns(2)
    with col1:
        with st.container(border=True):
            st.markdown("**I just raced — debrief it**")
            st.caption(
                "Upload your race's telemetry file and the engineer "
                "reconstructs what actually happened."
            )
            st.page_link(page_for("debrief"), label="Go to Race Debrief")
    with col2:
        with st.container(border=True):
            st.markdown("**I'm about to race — brief me**")
            st.caption(
                "Field strength, pace targets, and where your rating "
                "says you'll run this week."
            )
            st.page_link(page_for("briefing"), label="Go to Race Briefing")

    with st.expander("Where is my telemetry (.ibt) file?"):
        st.markdown(
            "iRacing records telemetry when you press **Alt+L** in the "
            "car (the Garage 61 agent records automatically). Files "
            f"land in `{telemetry_dir()}` — after a race, the newest "
            ".ibt from your race session is the one to upload."
        )

    if st.button("See a sample debrief"):
        st.session_state["race_narrative"] = load_sample_narrative()
        st.session_state["sample_mode"] = True
        st.switch_page(page_for("debrief"))

    # --- Status strip ----------------------------------------------------
    try:
        version = f"v{get_version()}"
    except Exception:  # noqa: BLE001 -- cosmetic only, like _app_version
        version = "v?"
    sha = _app_version()
    if sha != "unknown":
        version += f" ({sha})"
    parts = [
        version,
        "host mode" if is_host() else "guest mode",
    ]
    if is_host():
        if watcher_running():
            last = watcher_last_activity()
            when = (
                relative_time(last, time.time()) if last else "just started"
            )
            parts.append(f"telemetry watcher: running, last activity {when}")
        else:
            parts.append("telemetry watcher: stopped")
    st.caption(" · ".join(parts))
