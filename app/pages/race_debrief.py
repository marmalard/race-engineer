"""Race Debrief page — Surface 1 of the race-intelligence product.

Display-only: all analysis lives in core/race/. The page orchestrates
ingest -> narrative -> store -> render, then AI debrief + chat.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from core.race.ingest import (
    RaceIngestError,
    ingest_race,
)
from core.race.models import RaceNarrative
from core.race.narrative import build_narrative
from core.race.race_store import RaceStore
from core.race.render import render_export_markdown, render_narrative_markdown
from core.telemetry.ibt_parser import IBTParser
from core.track.track_db import TrackDB

logger = logging.getLogger(__name__)

TELEMETRY_DIR = Path(r"C:\Users\antho\Documents\iRacing\telemetry")
TRACKS_DB = Path("data/tracks.db")


def _make_api():
    """LiveIRacingAPI from env creds, or None (partial-narrative mode)."""
    client_id = os.environ.get("IRACING_CLIENT_ID", "")
    client_secret = os.environ.get("IRACING_CLIENT_SECRET", "")
    username = os.environ.get("IRACING_USERNAME", "")
    password = os.environ.get("IRACING_PASSWORD", "")
    if not all([client_id, client_secret, username, password]):
        return None
    from core.benchmark.iracing_api import LiveIRacingAPI

    return LiveIRacingAPI(client_id, client_secret, username, password)


def _load_corners(track_id: int, track_directory: str, track_length_m: float):
    """Corners for annotation, lazy-seeding like the live coach does."""
    try:
        db = TrackDB(TRACKS_DB)
        corners = db.get_corners(str(track_id))
        if not corners:
            from core.track.lovely_seeder import seed_track_from_lovely

            seed_track_from_lovely(
                db, str(track_id), track_directory, track_length_m
            )
            corners = db.get_corners(str(track_id))
        return corners
    except Exception:  # noqa: BLE001 — corner names are enhancement only
        return []


@st.cache_data(show_spinner=False, ttl=300)
def _scan_race_ibts(folder: str) -> list[dict]:
    """Cheap scan of the host telemetry folder for race IBTs."""
    parser = IBTParser()
    races = []
    for path in sorted(Path(folder).glob("*.ibt"), reverse=True):
        try:
            session = parser.parse_session_only(path)
            weekend = (session.raw or {}).get("WeekendInfo", {}) or {}
            if weekend.get("EventType") == "Race" and weekend.get("SubSessionID"):
                races.append(
                    {
                        "path": str(path),
                        "label": f"{session.track_name} — {session.car_name} "
                        f"— {path.stem[-19:]}",
                    }
                )
        except Exception:  # noqa: BLE001 — skip unreadable files
            continue
    return races


def _analyze(source, ibt_path: str, store: RaceStore) -> RaceNarrative:
    """Ingest -> narrative -> persist. Returns the narrative."""
    api = _make_api()
    try:
        data = ingest_race(source, api)
    finally:
        if api is not None:
            api.close()
    corners = _load_corners(
        data.track_id, data.track_directory, data.track_length_m
    )
    narrative = build_narrative(data, corners)
    store.save_race(narrative, ibt_file_path=ibt_path)
    return narrative


def _position_chart(narrative: RaceNarrative) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=[p.lap for p in narrative.position_timeline],
            y=[p.position for p in narrative.position_timeline],
            mode="lines+markers",
            name=narrative.header.driver_name,
        )
    )
    fig.update_yaxes(autorange="reversed", dtick=1, title="Position")
    fig.update_xaxes(dtick=1, title="Lap")
    fig.update_layout(height=300, margin=dict(l=10, r=10, t=30, b=10))
    return fig


def _gap_chart(narrative: RaceNarrative) -> go.Figure:
    fig = go.Figure()
    for rival in narrative.gaps:
        fig.add_trace(
            go.Scatter(
                x=[g.lap for g in rival.gaps],
                y=[g.gap_s for g in rival.gaps],
                mode="lines",
                name=f"{rival.display_name} (P{rival.finish_position})",
            )
        )
    fig.add_hline(y=0.0, line_dash="dot")
    fig.update_yaxes(title="Gap (s) — positive = rival ahead")
    fig.update_xaxes(dtick=1, title="Lap")
    fig.update_layout(height=300, margin=dict(l=10, r=10, t=30, b=10))
    return fig


def _render_debrief_and_chat(narrative: RaceNarrative, store: RaceStore):
    h = narrative.header
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    st.subheader("Engineer's debrief")
    debrief_text = store.get_debrief(h.subsession_id, h.cust_id)

    if not api_key:
        st.info(
            "AI debrief unavailable — ANTHROPIC_API_KEY is not configured. "
            "The narrative above is complete without it."
        )
    else:
        from core.coaching.synthesizer import Synthesizer

        _AI_ERROR = (
            "The engineer is unreachable right now (AI API error). "
            "The narrative above is unaffected — try again later."
        )
        if debrief_text is None:
            if st.button("Generate debrief"):
                with st.spinner("Engineer is reviewing the race..."):
                    try:
                        synth = Synthesizer(api_key=api_key)
                        report = synth.generate_race_debrief(narrative)
                    except Exception:
                        logger.exception("generate_race_debrief failed")
                        st.error(_AI_ERROR)
                    else:
                        store.save_debrief(
                            h.subsession_id, h.cust_id,
                            report.report_text, report.model_used,
                        )
                        st.rerun()
        else:
            st.markdown(debrief_text)

            st.subheader("Ask the engineer")
            history = store.get_chat(h.subsession_id, h.cust_id)
            for msg in history:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])
            question = st.chat_input("Ask about the race...")
            if question:
                with st.spinner("..."):
                    try:
                        synth = Synthesizer(api_key=api_key)
                        reply = synth.race_chat_reply(
                            narrative,
                            debrief_text,
                            history + [{"role": "user", "content": question}],
                        )
                    except Exception:
                        logger.exception("race_chat_reply failed")
                        st.error(_AI_ERROR)
                    else:
                        store.append_chat_message(
                            h.subsession_id, h.cust_id, "user", question
                        )
                        store.append_chat_message(
                            h.subsession_id, h.cust_id, "assistant", reply
                        )
                        st.rerun()

    # Export is always available (works without AI)
    st.divider()
    include_chat = st.checkbox("Include chat in export", value=False)
    chat = (
        store.get_chat(h.subsession_id, h.cust_id) if include_chat else None
    )
    st.download_button(
        "Export debrief (markdown)",
        data=render_export_markdown(narrative, debrief_text, chat),
        file_name=f"{h.track_name.replace(' ', '-').lower()}-"
        f"{h.session_date[:10] or 'race'}-debrief.md",
        mime="text/markdown",
    )


def render_race_debrief_page():
    st.header("Race Debrief")
    st.markdown(
        "Upload a race IBT — the engineer reconstructs what happened and "
        "debriefs you on it."
    )
    store = RaceStore()

    narrative: RaceNarrative | None = st.session_state.get("race_narrative")

    tab_upload, tab_stored = st.tabs(["Analyze a race", "Past debriefs"])

    with tab_upload:
        uploaded = st.file_uploader("Race IBT file", type=["ibt"])
        source = None
        ibt_path = ""
        if uploaded is not None:
            source = uploaded.getvalue()
        elif TELEMETRY_DIR.exists():
            races = _scan_race_ibts(str(TELEMETRY_DIR))
            if races:
                choice = st.selectbox(
                    "...or pick from the host telemetry folder",
                    options=[None] + races,
                    format_func=lambda r: "—" if r is None else r["label"],
                )
                if choice:
                    source = Path(choice["path"])
                    ibt_path = choice["path"]

        if source is not None and st.button("Analyze race", type="primary"):
            try:
                with st.spinner("Reconstructing the race..."):
                    narrative = _analyze(source, ibt_path, store)
                st.session_state["race_narrative"] = narrative
            except RaceIngestError as exc:
                st.error(str(exc))
            except Exception:
                logger.exception("_analyze failed")
                st.error(
                    "Couldn't analyze this file — it may be corrupt, "
                    "incomplete, or not a race IBT."
                )

    with tab_stored:
        stored = store.list_races()
        if not stored:
            st.caption("No debriefed races yet.")
        for meta in stored:
            label = (
                f"{meta.session_date[:10]} — {meta.track_name} — "
                f"{meta.driver_name} — P{meta.finish_position} "
                f"({meta.irating_delta:+d} iR)"
            )
            if st.button(label, key=f"open-{meta.subsession_id}-{meta.cust_id}"):
                narrative = store.get_race(meta.subsession_id, meta.cust_id)
                st.session_state["race_narrative"] = narrative

    if narrative is None:
        return

    st.divider()
    h = narrative.header
    if not narrative.pace and not narrative.gaps:
        st.warning(
            "Some race data was unavailable — pace ranking and rival gaps "
            "are missing. This can happen when official results couldn't be "
            "fetched or lap data was too thin."
        )
    cols = st.columns(4)
    cols[0].metric("Finish", f"P{h.finish_position}", f"from P{h.start_position}")
    if h.irating_new > 0:
        cols[1].metric("iRating", h.irating_new, f"{h.irating_new - h.irating_old:+d}")
    else:
        cols[1].metric("iRating", "—")
    cols[2].metric("SoF", h.sof)
    cols[3].metric("Incidents", f"{h.incidents}x")

    st.plotly_chart(_position_chart(narrative), use_container_width=True)
    if narrative.gaps:
        st.plotly_chart(_gap_chart(narrative), use_container_width=True)

    st.markdown(render_narrative_markdown(narrative))
    st.divider()
    _render_debrief_and_chat(narrative, store)
