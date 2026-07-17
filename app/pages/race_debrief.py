"""Race Debrief page — Surface 1 of the race-intelligence product.

Display-only: all analysis lives in core/race/. The page orchestrates
ingest -> narrative -> store -> render, then AI debrief + chat.
"""

from __future__ import annotations

import logging
import os
import traceback
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from app.components.errors import API_DOWN, NO_AI_KEY, explain
from app.components.glossary import help_text
from app.components.host import telemetry_dir
from app.components.sample import load_sample_debrief_text
from app.components.theme import (
    ACCENT,
    RIVAL_COLORS,
    TEXT_MUTED,
    chart_layout,
    header_strip,
    section_header,
)
from core.race.ingest import (
    ingest_race,
)
from core.race.models import RaceNarrative
from core.race.narrative import build_narrative
from core.race.race_store import RaceStore
from core.race.render import render_export_markdown, render_narrative_markdown
from core.telemetry.ibt_parser import IBTParser
from core.track.lovely_seeder import seed_track_from_lovely
from core.track.models import Track, TrackType
from core.track.track_db import TrackDB

logger = logging.getLogger(__name__)

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


def _load_corners(
    track_id: int,
    track_directory: str,
    track_length_m: float,
    track_name: str,
) -> list:
    """Corners for annotation, lazy-seeding like the live coach does.

    The lovely-track-data seeder requires a track row in tracks.db before it
    can attach corners. A race debrief may be the first time this track is
    processed (the offline IBT pipeline creates rows, but the debrief page
    runs independently), so we create a minimal row when missing — same
    pattern as scripts/live_coach.py::_load_corners. Corner names are
    enhancement only: any exception leaves the caller with an empty list
    and position-based fallbacks.
    """
    if not track_id:
        return []
    try:
        db = TrackDB(TRACKS_DB)
        if db.get_track(str(track_id)) is None:
            db.upsert_track(Track(
                track_id=str(track_id),
                name=track_name,
                config=None,
                length_meters=track_length_m,
                track_type=TrackType.ROAD,
                character=None,
            ))
        corners = db.get_corners(str(track_id))
        if not corners:
            seed_track_from_lovely(
                db, str(track_id), track_directory, track_length_m
            )
            corners = db.get_corners(str(track_id))
        return corners
    except Exception:  # noqa: BLE001 — corner names are enhancement only
        return []


def _profile_block(store: RaceStore, cust_id: int) -> str:
    """Compact cross-race profile context for the AI; "" on any failure."""
    try:
        from core.profile.builder import load_profile
        from core.profile.render import profile_prompt_block

        profile = load_profile(store, TrackDB(TRACKS_DB), cust_id)
        return profile_prompt_block(profile)
    except Exception:  # noqa: BLE001 — profile must never break the debrief
        return ""


def dedupe_race_chunks(races: list[dict]) -> list[dict]:
    """One entry per subsession — the largest chunk.

    iRacing writes a new IBT each time recording restarts inside the race
    server (practice segment, quali, the race); every chunk shares the
    SubSessionID, and the race is the largest chunk of its group. Pure;
    preserves the incoming (newest-first) order.
    """
    best: dict[int, dict] = {}
    for r in races:
        cur = best.get(r["subsession_id"])
        if cur is None or r["size"] > cur["size"]:
            best[r["subsession_id"]] = r
    keep = {id(r) for r in best.values()}
    return [r for r in races if id(r) in keep]


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
                        "subsession_id": int(weekend["SubSessionID"]),
                        "size": path.stat().st_size,
                    }
                )
        except Exception:  # noqa: BLE001 — skip unreadable files
            continue
    return dedupe_race_chunks(races)


def _analyze(
    source, ibt_path: str, store: RaceStore, on_phase=None
) -> RaceNarrative:
    """Ingest -> narrative -> persist. Returns the narrative."""
    api = _make_api()
    try:
        data = ingest_race(source, api, on_phase=on_phase)
    finally:
        if api is not None:
            api.close()
    if on_phase is not None:
        on_phase("Reconstructing the race...")
    corners = _load_corners(
        data.track_id, data.track_directory, data.track_length_m, data.track_name
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
            line=dict(color=ACCENT, width=2.5),
            marker=dict(size=6),
        )
    )
    fig.update_yaxes(autorange="reversed", dtick=1, title="Position")
    fig.update_xaxes(dtick=1, title="Lap")
    fig.update_layout(**chart_layout())
    return fig


def _gap_chart(narrative: RaceNarrative) -> go.Figure:
    fig = go.Figure()
    for i, rival in enumerate(narrative.gaps):
        fig.add_trace(
            go.Scatter(
                x=[g.lap for g in rival.gaps],
                y=[g.gap_s for g in rival.gaps],
                mode="lines",
                name=f"{rival.display_name} (P{rival.finish_position})",
                line=dict(color=RIVAL_COLORS[i % len(RIVAL_COLORS)], width=2),
            )
        )
    fig.add_hline(y=0.0, line_dash="dot", line_color=TEXT_MUTED)
    fig.update_yaxes(title="Gap (s) — positive = rival ahead")
    fig.update_xaxes(dtick=1, title="Lap")
    fig.update_layout(**chart_layout())
    return fig


def _render_debrief_and_chat(narrative: RaceNarrative, store: RaceStore):
    h = narrative.header
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    section_header("\U0001f399 Engineer's debrief")
    debrief_text = store.get_debrief(h.subsession_id, h.cust_id)

    if not api_key:
        st.info(NO_AI_KEY)
    else:
        from core.coaching.synthesizer import Synthesizer

        _AI_ERROR = (
            "The engineer is unreachable right now (AI API error). "
            "The narrative above is unaffected — try again later."
        )
        def _generate_and_save(clear_chat: bool) -> None:
            with st.spinner("Engineer is reviewing the race..."):
                try:
                    synth = Synthesizer(api_key=api_key)
                    report = synth.generate_race_debrief(
                        narrative,
                        profile_block=_profile_block(
                            store, narrative.header.cust_id
                        ),
                    )
                except Exception:
                    logger.exception("generate_race_debrief failed")
                    st.error(_AI_ERROR)
                else:
                    if clear_chat:
                        store.clear_chat(h.subsession_id, h.cust_id)
                    store.save_debrief(
                        h.subsession_id, h.cust_id,
                        report.report_text, report.model_used,
                    )
                    st.rerun()

        if debrief_text is None:
            if st.button("Generate debrief"):
                _generate_and_save(clear_chat=False)
        else:
            with st.container(border=True):
                st.markdown(debrief_text)
            if st.button(
                "Regenerate debrief",
                help="Re-run the engineer on this race. Replaces this "
                     "debrief and clears its chat.",
            ):
                _generate_and_save(clear_chat=True)

            section_header("Ask the engineer")
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
                            profile_block=_profile_block(
                                store, narrative.header.cust_id
                            ),
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
        uploaded = st.file_uploader("Race IBT file", type=["ibt"], help=help_text("IBT"))
        source = None
        ibt_path = ""
        if uploaded is not None:
            source = uploaded.getvalue()
        elif telemetry_dir().exists():
            races = _scan_race_ibts(str(telemetry_dir()))
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
                with st.status("Analyzing the race...", expanded=False) as status:
                    narrative = _analyze(
                        source, ibt_path, store,
                        on_phase=lambda label: status.update(label=label),
                    )
                    status.update(
                        label="Race reconstructed.", state="complete"
                    )
                st.session_state["race_narrative"] = narrative
                st.session_state["sample_mode"] = False
            except Exception as exc:
                logger.exception("_analyze failed")
                st.error(explain(exc))
                with st.expander("Technical details (for the host)"):
                    st.code(traceback.format_exc(), language=None)

    with tab_stored:
        stored = store.list_races()
        if not stored:
            st.caption("No debriefed races yet.")
            if st.button("No race yet? See what a debrief looks like"):
                from app.components.sample import load_sample_narrative

                st.session_state["race_narrative"] = load_sample_narrative()
                st.session_state["sample_mode"] = True
                st.rerun()
        for meta in stored:
            label = (
                f"{meta.session_date[:10]} — {meta.track_name} — "
                f"{meta.driver_name} — P{meta.finish_position} "
                f"({meta.irating_delta:+d} iR)"
            )
            if st.button(label, key=f"open-{meta.subsession_id}-{meta.cust_id}"):
                narrative = store.get_race(meta.subsession_id, meta.cust_id)
                st.session_state["race_narrative"] = narrative
                st.session_state["sample_mode"] = False

    if narrative is None:
        return

    st.divider()
    h = narrative.header
    if not narrative.pace and not narrative.gaps:
        st.warning(API_DOWN)

    config = f" ({h.track_config})" if h.track_config else ""
    header_strip(
        [
            f"{h.track_name}{config}",
            h.car_name,
            h.series_name,
            h.session_date[:10],
            h.driver_name,
        ],
        bold=(0, 4),
    )
    cols = st.columns(4)
    cols[0].metric("Finish", f"P{h.finish_position}", f"from P{h.start_position}")
    if h.irating_new > 0:
        cols[1].metric("iRating", h.irating_new, f"{h.irating_new - h.irating_old:+d}", help=help_text("iRating"))
    else:
        cols[1].metric("iRating", "—", help=help_text("iRating"))
    cols[2].metric("SoF", h.sof, help=help_text("SoF"))
    cols[3].metric("Incidents", f"{h.incidents}x")

    section_header("Position")
    st.plotly_chart(_position_chart(narrative), use_container_width=True)
    if narrative.gaps:
        section_header("Gaps to rivals")
        st.plotly_chart(_gap_chart(narrative), use_container_width=True)

    section_header("Race story")
    st.markdown(render_narrative_markdown(narrative, include_header=False))
    st.divider()
    if st.session_state.get("sample_mode"):
        section_header("\U0001f399 Engineer's debrief — example")
        st.info(
            "This is a sample race with fictional drivers — it shows "
            "what a debrief looks like before you upload your own. "
            "The engineer's text below is a canned example, not live AI."
        )
        with st.container(border=True):
            st.markdown(load_sample_debrief_text())
    else:
        _render_debrief_and_chat(narrative, store)
