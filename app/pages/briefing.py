"""Race Briefing page (week-plan slice 1). Display only - all logic in
core/briefing. Spinner phases per the UX-review finding (no bare spinners)."""

import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from core.benchmark.iracing_api import LiveIRacingAPI
from core.briefing.ingest import (
    SeriesCandidate,
    build_briefing,
    rank_series_candidates,
)
from core.briefing.render import render_briefing
from core.track.track_db import TrackDB

DB_PATH = Path("data/tracks.db")


def candidate_label(c: SeriesCandidate) -> str:
    depth = (
        f"{c.practice_sessions} practice sessions"
        if c.practice_sessions
        else "new track for you"
    )
    return f"{c.series_name} - {c.track_name} ({depth})"


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

    pick = st.selectbox(
        "Series", candidates, format_func=candidate_label, index=0
    )
    season = next(s for s in seasons if s.season_id == pick.season_id)

    cars_at_track = sorted(
        {
            s.car
            for s in sessions
            if s.track_id == str(pick.track_id) and s.session_type != "Race"
        }
    )
    car = (
        st.selectbox("Your car", cars_at_track)
        if cars_at_track
        else st.text_input(
            "Your car (no practice history at this track yet)", ""
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
        ))
        fig.add_trace(go.Scatter(
            x=[b.ir_center for b in data.curve.bins],
            y=[b.median_lap_s for b in data.curve.bins],
            mode="lines+markers", name="Median",
        ))
        if data.placement is not None:
            fig.add_hline(
                y=data.placement.lap_s, line_dash="dash",
                annotation_text="You (practice best)",
            )
        if data.user_irating:
            fig.add_vline(
                x=data.user_irating, line_dash="dot",
                annotation_text=f"Your iR {data.user_irating:,}",
            )
        fig.update_layout(
            xaxis_title="Driver iRating",
            yaxis_title="Best race lap (s)",
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
                synth.generate_briefing_narrative(briefing_json)
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
