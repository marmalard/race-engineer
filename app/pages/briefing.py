"""Race Briefing page (week-plan slice 1). Display only - all logic in
core/briefing. Spinner phases per the UX-review finding (no bare spinners)."""

import json
import os
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from core.benchmark.iracing_api import LiveIRacingAPI
from core.briefing.curve import smoothed_medians
from core.briefing.ingest import (
    SeriesCandidate,
    build_briefing,
    max_license_group,
    rank_series_candidates,
)
from core.briefing.render import fmt_lap, render_briefing
from core.track.track_db import TrackDB

DB_PATH = Path("data/tracks.db")
RACES_DB = Path("data/races.db")


def candidate_label(c: SeriesCandidate) -> str:
    depth = (
        f"{c.practice_sessions} practice sessions"
        if c.practice_sessions
        else "new track for you"
    )
    return f"{c.series_name} - {c.track_name} ({depth})"


def _briefing_profile_block() -> str:
    """Cross-race profile context for the AI briefing; '' on any failure.

    Resolves cust_id as the most-frequent driver in races.db (same mechanism
    as driver_profile.py::_resolve_cust_id, minus the selectbox — the AI call
    is non-interactive so we pick the dominant driver automatically).
    """
    try:
        from core.profile.builder import load_profile
        from core.profile.render import profile_prompt_block
        from core.race.race_store import RaceStore

        store = RaceStore(RACES_DB)
        races = store.list_races()
        if not races:
            return ""
        counts = Counter(r.cust_id for r in races)
        cust_id = counts.most_common(1)[0][0]
        profile = load_profile(store, TrackDB(DB_PATH), cust_id)
        return profile_prompt_block(profile)
    except Exception:  # noqa: BLE001 — profile must never break the briefing
        return ""


def _get_api() -> LiveIRacingAPI | None:
    cid = os.environ.get("IRACING_CLIENT_ID")
    secret = os.environ.get("IRACING_CLIENT_SECRET")
    user = os.environ.get("IRACING_USERNAME")
    pw = os.environ.get("IRACING_PASSWORD")
    if not all([cid, secret, user, pw]):
        return None
    return LiveIRacingAPI(
        client_id=cid, client_secret=secret, username=user, password=pw
    )


@st.cache_data(ttl=3600, show_spinner=False)
def _load_seasons_cached():
    api = _get_api()
    if api is None:
        return []
    try:
        return api.get_series_seasons()
    finally:
        api.close()


@st.cache_data(ttl=3600, show_spinner=False)
def _load_license_group():
    """The user's highest license group, or None (then never filter)."""
    api = _get_api()
    if api is None:
        return None
    try:
        return max_license_group(api.get_member_info())
    except Exception:
        return None
    finally:
        api.close()


def render_briefing_page() -> None:
    st.title("Race Briefing")
    st.caption(
        "Where your pace sits in this week's field - and when to run "
        "the race."
    )

    api_probe = _get_api()
    if api_probe is None:
        st.warning(
            "The briefing needs iRacing Data API credentials "
            "(IRACING_CLIENT_ID / SECRET / USERNAME / PASSWORD in .env). "
            "Unlike the debrief, it can't work from an upload."
        )
        return
    api_probe.close()

    with st.spinner("Loading this week's series calendar..."):
        seasons = _load_seasons_cached()
    if not seasons:
        st.error("Couldn't load the season calendar - check credentials.")
        return

    db = TrackDB(DB_PATH)
    sessions = db.list_session_history()
    candidates = rank_series_candidates(seasons, sessions)
    if not candidates:
        st.error("No series with a current-week schedule found.")
        return

    group = _load_license_group()
    filter_col, license_col = st.columns([2, 1])
    query = filter_col.text_input(
        "Find a series", "", placeholder="e.g. Porsche, GT4, Formula..."
    )
    licensed_only = license_col.checkbox(
        "My license only",
        value=group is not None,
        disabled=group is None,
        help="Hides series above your license class. Content ownership "
        "isn't exposed by the iRacing API, so owned-content filtering "
        "isn't possible - the practice-depth ordering is the proxy.",
    )
    filtered = candidates
    if licensed_only and group is not None:
        filtered = [
            c for c in filtered
            if c.license_group == 0 or c.license_group <= group
        ]
    if query:
        q = query.lower()
        filtered = [
            c for c in filtered if q in candidate_label(c).lower()
        ]
    if not filtered:
        st.info("No series match - clear the filter to see all of them.")
        return

    pick = st.selectbox(
        "Series", filtered, format_func=candidate_label, index=0
    )
    season = next(s for s in seasons if s.season_id == pick.season_id)

    cars_at_track = sorted(
        {
            s.car
            for s in sessions
            if s.track_id == str(pick.track_id) and s.session_type != "Race"
        }
    )
    other_cars = sorted(
        {s.car for s in sessions if s.session_type != "Race"}
        - set(cars_at_track)
    )
    car_options = cars_at_track + other_cars
    car = (
        st.selectbox(
            "Your car",
            car_options,
            help="Cars you've practiced at this week's track are listed "
            "first. Any other car still gets the field briefing - pace "
            "placement needs practice laps at this combo.",
        )
        if car_options
        else st.text_input(
            "Your car (no practice history recorded yet)", ""
        )
    )

    user_ir = st.number_input(
        "Your iRating (sport)", min_value=0, max_value=12000,
        value=st.session_state.get("briefing_ir", 1350), step=25,
    )
    st.session_state["briefing_ir"] = user_ir

    if st.button("Build briefing", type="primary"):
        cache_key = (pick.season_id, pick.race_week, car, user_ir)
        if st.session_state.get("briefing_key") != cache_key:
            laps = {}
            with st.spinner("Reading your practice history..."):
                for s in sessions:
                    laps[s.session_id] = db.get_session_laps(s.session_id)
            api = _get_api()
            try:
                with st.spinner(
                    "Fetching this week's races (first build for a series "
                    "takes ~30s; cached after)..."
                ):
                    data = build_briefing(
                        api=api, season=season, sessions=sessions, laps=laps,
                        car=car, user_irating=user_ir or None,
                        now_utc=datetime.now(timezone.utc),
                    )
            finally:
                if api is not None:
                    api.close()
            st.session_state["briefing_key"] = cache_key
            st.session_state["briefing_data"] = data
            st.session_state.pop("briefing_narrative", None)
            st.session_state.pop("briefing_chat", None)

    data = st.session_state.get("briefing_data")
    if data is None:
        return
    st.caption("Showing the last built briefing - press Build briefing to refresh.")

    if data.curve is not None and data.curve.points:
        irs = [p[0] for p in data.curve.points]
        lapss = [p[1] for p in data.curve.points]
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=irs, y=lapss, mode="markers", name="Field",
            marker=dict(size=5, opacity=0.45),
            customdata=[fmt_lap(v) for v in lapss],
            hovertemplate="%{customdata} - %{x:,} iR<extra></extra>",
        ))
        smoothed = smoothed_medians(data.curve)
        fig.add_trace(go.Scatter(
            x=[p[0] for p in smoothed],
            y=[p[1] for p in smoothed],
            mode="lines+markers", name="Field median",
            customdata=[fmt_lap(p[1]) for p in smoothed],
            hovertemplate="median %{customdata} @ %{x:,} iR<extra></extra>",
        ))
        if data.placement is not None:
            fig.add_hline(
                y=data.placement.lap_s, line_dash="dash",
                annotation_text=f"You ({fmt_lap(data.placement.lap_s)})",
            )
        if data.user_irating:
            fig.add_vline(
                x=data.user_irating, line_dash="dot",
                annotation_text=f"Your iR {data.user_irating:,}",
            )
        # Clamp the display band so one wreck-limped 'best' lap can't
        # squash the whole chart; ticks in sim-standard m:ss.
        ys = sorted(lapss)
        y_lo = ys[0]
        y_hi = ys[min(len(ys) - 1, int(0.95 * len(ys)))]
        if data.placement is not None:
            y_lo = min(y_lo, data.placement.lap_s)
            y_hi = max(y_hi, data.placement.lap_s)
        pad = max(0.3, (y_hi - y_lo) * 0.05)
        step = max(0.5, round((y_hi - y_lo) / 6, 1))
        tick = y_lo - (y_lo % step)
        tickvals = []
        while tick <= y_hi + pad:
            tickvals.append(round(tick, 3))
            tick += step
        fig.update_yaxes(
            range=[y_lo - pad, y_hi + pad],
            tickvals=tickvals,
            ticktext=[fmt_lap(v) for v in tickvals],
            title="Best race lap",
        )
        fig.update_layout(
            xaxis_title="Driver iRating",
            height=420, showlegend=True,
        )
        st.plotly_chart(fig, use_container_width=True)

    st.markdown(render_briefing(data))

    # --- optional AI layer (mirrors the debrief page pattern) ---
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return
    from core.coaching.synthesizer import Synthesizer

    briefing_json = json.dumps(asdict(data), default=str)
    if st.button("Engineer's briefing (AI)"):
        synth = Synthesizer(api_key=os.environ["ANTHROPIC_API_KEY"])
        with st.spinner("Your engineer is preparing the briefing..."):
            st.session_state["briefing_narrative"] = (
                synth.generate_briefing_narrative(
                    briefing_json,
                    profile_block=_briefing_profile_block(),
                )
            )
    narrative = st.session_state.get("briefing_narrative")
    if narrative:
        st.markdown(narrative)
        st.divider()
        history = st.session_state.setdefault("briefing_chat", [])
        for m in history:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])
        if q := st.chat_input("Ask your engineer about this race..."):
            history.append({"role": "user", "content": q})
            synth = Synthesizer(api_key=os.environ["ANTHROPIC_API_KEY"])
            with st.spinner("..."):
                reply = synth.briefing_chat(briefing_json, narrative, history)
            history.append({"role": "assistant", "content": reply})
            st.rerun()
