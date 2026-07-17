"""Progression page — the Strava layer (spec §6).

Display only: streak, pace trends, PB timeline, iR/SR history, technique
trends, pace-implied iR. Every block renders a collecting state below
threshold — the page is useful at any corpus size. These numbers inform;
nothing here gates.
"""

from datetime import date
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from app.pages.briefing import _get_api, _load_seasons_cached
from app.pages.driver_profile import _resolve_cust_id
from core.benchmark.reference_store import ReferenceStore
from core.briefing.render import fmt_lap
from core.profile.models import TECHNIQUE_MIN_SESSIONS
from core.profile.pace import build_readiness
from core.profile.render import FAULT_LABELS
from core.progression.implied_ir import aggregate_implied_ir
from core.progression.ingest import (
    compute_week_implied_ir, fetch_rating_history, normalize_sr,
)
from core.progression.store import ImpliedIRStore
from core.progression.streak import build_streak, iracing_week_start
from core.progression.trends import (
    combo_pace_series, fault_trend_series, pb_timeline,
)
from core.race.race_store import RaceStore
from core.track.track_db import TrackDB

RACES_DB = Path("data/races.db")
TRACKS_DB = Path("data/tracks.db")
REFS_DB = Path("data/reference_laps.db")


def _lap_axis_ticks(values: list[float]) -> tuple[list[float], list[str]]:
    """Five evenly spaced y ticks formatted m:ss.mmm (briefing fmt_lap)."""
    lo, hi = min(values), max(values)
    if hi == lo:
        lo, hi = lo - 0.5, hi + 0.5
    vals = [lo + (hi - lo) * i / 4 for i in range(5)]
    return vals, [fmt_lap(v) for v in vals]


def _week_band_series(
    history: list[tuple[str, list]],
) -> tuple[list[str], list[int], list[int]]:
    """Weekly aggregated implied-iR bands for the trend chart."""
    weeks, los, his = [], [], []
    for week, rows in history:
        agg = aggregate_implied_ir(rows)
        if agg is None:
            continue
        weeks.append(week)
        los.append(agg.lo)
        his.append(agg.hi)
    return weeks, los, his


def render_progression_page() -> None:
    st.title("Progression")
    st.markdown(
        "Your season at a glance — race volume, pace trends, and what the "
        "numbers say about where you're heading."
    )

    store = RaceStore(RACES_DB)
    track_db = TrackDB(TRACKS_DB)

    # ---- 1. Race-volume streak -------------------------------------------
    st.subheader("Race streak")
    try:
        races = store.list_races()
    except Exception:
        races = []
    streak = build_streak(
        [(r.session_date, r.created_at) for r in races], date.today()
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("Current streak", f"{streak.streak_weeks} wk")
    c2.metric("Races this week", streak.races_this_week)
    c3.metric("Races captured", streak.total_races)
    if streak.total_races == 0:
        st.caption(
            "No races captured yet — race, and the watcher fills this in "
            "automatically."
        )

    # ---- 2. Per-combo pace trend -----------------------------------------
    st.subheader("Pace trend")
    try:
        sessions = track_db.list_session_history()
    except Exception:
        sessions = []
    series = combo_pace_series(sessions)
    if not series:
        st.caption("Collecting — practice sessions build this chart.")
    else:
        laps = {}
        try:
            laps = {s.session_id: track_db.get_session_laps(s.session_id)
                    for s in sessions}
        except Exception:
            pass
        ordered = [
            (r.track_id, r.car, r.track_name)
            for r in build_readiness(sessions, laps)
            if (r.track_id, r.car) in series
        ]
        # readiness may exclude thin combos — append the rest, practiced-first
        seen = {(t, c) for t, c, _ in ordered}
        names = {s.track_id: s.track_name for s in sessions}
        rest = sorted(
            (k for k in series if k not in seen),
            key=lambda k: -len(series[k]),
        )
        options = ordered + [(t, c, names.get(t, t)) for t, c in rest]
        choice = st.selectbox(
            "Combo", options,
            format_func=lambda o: f"{o[2]} — {o[1]}",
        )
        pts = series[(choice[0], choice[1])]
        fig = go.Figure(go.Scatter(
            x=[d for d, _ in pts], y=[v for _, v in pts],
            mode="lines+markers", line=dict(color="#00cc66", width=2),
            customdata=[[fmt_lap(v)] for _, v in pts],
            hovertemplate="%{x}<br>%{customdata[0]}<extra></extra>",
        ))
        vals, texts = _lap_axis_ticks([v for _, v in pts])
        fig.update_layout(
            height=320, margin=dict(l=60, r=20, t=10, b=40),
            yaxis=dict(tickvals=vals, ticktext=texts, title="Session best"),
            xaxis=dict(title=""),
        )
        st.plotly_chart(fig, use_container_width=True)
        if len(pts) < 2:
            st.caption("One session so far at this combo — trends need two.")

    # ---- 3. PB timeline --------------------------------------------------
    st.subheader("Personal bests")
    try:
        pbs = pb_timeline(ReferenceStore(REFS_DB).list_all())
    except Exception:
        pbs = []
    if not pbs:
        st.caption(
            "No personal-best references yet — the watcher promotes your "
            "fastest clean lap per combo automatically."
        )
    else:
        names = {s.track_id: s.track_name for s in sessions}
        st.table([
            {
                "Set": m.imported_at[:10],
                "Combo": f"{names.get(m.track_id, m.track_id)} — {m.car}",
                "Lap": fmt_lap(m.lap_time),
            }
            for m in reversed(pbs)  # newest first for reading
        ])

    # ---- 4. iRating / Safety Rating over time ----------------------------
    st.subheader("iRating & Safety Rating")
    api = _get_api()
    cust_id = _resolve_cust_id(store)
    if api is None or cust_id is None:
        st.caption(
            "Needs iRacing credentials and at least one captured race — "
            "then your official rating history appears here."
        )
    else:
        ir_pts, sr_pts = fetch_rating_history(api, cust_id)
        if not ir_pts:
            st.caption("Rating history unavailable right now — it'll retry.")
        else:
            fig = go.Figure(go.Scatter(
                x=[p.when for p in ir_pts], y=[p.value for p in ir_pts],
                mode="lines", line=dict(color="#00cc66", width=2),
                name="iRating",
            ))
            fig.update_layout(height=280, margin=dict(l=50, r=20, t=10, b=30),
                              yaxis_title="iRating")
            st.plotly_chart(fig, use_container_width=True)
        sr = normalize_sr(sr_pts)
        if sr:
            fig = go.Figure(go.Scatter(
                x=[w for w, _ in sr], y=[v for _, v in sr],
                mode="lines", line=dict(color="#4aa3ff", width=2),
                name="Safety Rating",
            ))
            fig.update_layout(height=220, margin=dict(l=50, r=20, t=10, b=30),
                              yaxis_title="SR")
            st.plotly_chart(fig, use_container_width=True)

    # ---- 5. Technique trends ---------------------------------------------
    st.subheader("Technique trends")
    try:
        diag_rows = track_db.list_region_diagnoses()
    except Exception:
        diag_rows = []
    fault_series = fault_trend_series(diag_rows)
    n_sessions = len({r.session_id for r in diag_rows})
    if not fault_series:
        st.caption(
            f"Technique trends unlock as diagnosed sessions accrue "
            f"({n_sessions} of {TECHNIQUE_MIN_SESSIONS})."
        )
    else:
        fig = go.Figure()
        for kind, pts in sorted(fault_series.items()):
            fig.add_trace(go.Scatter(
                x=[d for d, _ in pts], y=[t for _, t in pts],
                mode="lines+markers", name=FAULT_LABELS.get(kind, kind),
            ))
        fig.update_layout(
            height=340, margin=dict(l=50, r=20, t=10, b=40),
            yaxis_title="Time lost per session (s)",
            legend=dict(orientation="h", y=-0.2),
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            f"Time lost per session by habit, across {n_sessions} diagnosed "
            f"sessions — down and to the right is the goal. Measured against "
            f"the reference of the day: a new PB can make later losses look "
            f"bigger."
        )

    # ---- 6. Pace-implied iRating -----------------------------------------
    st.subheader("Pace-implied iRating")
    for w in st.session_state.pop("recompute_warnings", []):
        st.caption(f"Note: {w}")
    ir_store = ImpliedIRStore()
    latest = ir_store.latest_week()
    if latest is not None:
        week, rows = latest
        agg = aggregate_implied_ir(rows)
        if agg is not None:
            st.markdown(
                f"### {agg.lo:,}–{agg.hi:,}"
            )
            st.caption(
                f"Where your practice pace sits on this week's field curves, "
                f"across {agg.combo_count} combo"
                f"{'s' if agg.combo_count != 1 else ''} (week of {week}). "
                f"A progress stat, not a permission slip."
            )
            st.table([
                {
                    "Combo": f"{r.track_name} — {r.car}",
                    "Series curve": r.series_name,
                    "Your lap": fmt_lap(r.lap_s),
                    "Implied iR": f"{r.implied_lo:,}–{r.implied_hi:,}",
                }
                for r in rows
            ])
        weeks, los, his = _week_band_series(ir_store.history())
        if len(weeks) >= 2:
            fig = go.Figure([
                go.Scatter(x=weeks, y=his, mode="lines", line=dict(width=0),
                           showlegend=False, hoverinfo="skip"),
                go.Scatter(x=weeks, y=los, mode="lines", fill="tonexty",
                           line=dict(color="#00cc66", width=1),
                           fillcolor="rgba(0,204,102,0.2)", name="Implied iR"),
            ])
            fig.update_layout(height=260, margin=dict(l=50, r=20, t=10, b=30),
                              yaxis_title="Implied iR band")
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption(
            "Not computed yet — this places your practice pace on this "
            "week's field curves, the same math as the Race Briefing."
        )
    if api is None:
        st.caption("Computing needs iRacing credentials (Settings & Keys).")
    elif st.button("Recompute for this week"):
        with st.spinner("Harvesting this week's fields..."):
            seasons = _load_seasons_cached()
            try:
                sessions = track_db.list_session_history()
                laps = {s.session_id: track_db.get_session_laps(s.session_id)
                        for s in sessions}
            except Exception:
                sessions, laps = [], {}
            rows, warnings = compute_week_implied_ir(
                api, seasons, sessions, laps)
            ir_store.save_week(
                iracing_week_start(date.today()).isoformat(), rows)
        st.session_state["recompute_warnings"] = warnings
        st.rerun()
