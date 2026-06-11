"""Lap Coaching page — post-session telemetry analysis and coaching."""

import os
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from app.components.track_map import build_loss_map
from app.components.units import (
    distance_unit,
    distance_value,
    fmt_distance,
    fmt_speed,
    speed_unit,
    speed_value,
)
from core.benchmark.g61_import import G61ImportError, import_g61_csv
from core.benchmark.reference_store import ReferenceLap, ReferenceStore
from core.coaching.analyzer import CoachingAnalysis, analyze_session
from core.coaching.debrief import build_debrief
from core.track.track_db import TrackDB

DB_PATH = Path("data/tracks.db")
REFERENCE_DB = Path("data") / "reference_laps.db"
from core.coaching.synthesizer import Synthesizer


def _is_imperial() -> bool:
    """Check if the user has selected imperial units."""
    return st.session_state.get("unit_system", "Metric") == "Imperial"


def render_coaching_page() -> None:
    """Render the lap coaching page."""
    st.header("Lap Coaching")
    st.markdown(
        "Upload a telemetry file from your iRacing session to get "
        "prioritized coaching on where you're leaving the most time."
    )

    # --- Input ---
    uploaded_file = st.file_uploader(
        "Upload IBT File",
        type=["ibt"],
        help="iRacing telemetry files are in Documents/iRacing/telemetry/",
    )

    col1, col2 = st.columns(2)
    with col1:
        track_type = st.selectbox(
            "Track type",
            ["road", "street", "oval"],
            help="Affects corner detection sensitivity",
        )
    with col2:
        run_ai = st.checkbox("Generate AI coaching tips", value=True)

    if uploaded_file is None:
        st.markdown(
            "**How it works:**\n\n"
            "1. Drive a practice session in iRacing\n"
            "2. Upload the .ibt telemetry file here\n"
            "3. Get coaching on the 2-3 corners where you're leaving the most time\n\n"
            "The system compares your laps against your own best performance "
            "to find where you're inconsistent or leaving time on the table."
        )
        return

    # --- Analysis ---
    # Results are kept in session state so widgets in the sections below
    # (e.g. the reference-lap import) can trigger reruns without losing
    # the analysis.
    if st.button("Analyze Session", type="primary"):
        with st.spinner("Parsing telemetry and analyzing laps..."):
            try:
                st.session_state["coaching_analysis"] = analyze_session(
                    ibt_data=bytes(uploaded_file.getbuffer()),
                    track_type=track_type,
                    db_path=DB_PATH,
                )
            except ValueError as e:
                st.error(str(e))
                return
            except Exception as e:
                st.error(f"Analysis failed: {e}")
                return

    analysis: CoachingAnalysis | None = st.session_state.get("coaching_analysis")
    if analysis is None:
        return

    # --- Session Summary ---
    st.markdown("---")
    st.subheader(f"{analysis.car_name} at {analysis.track_name}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Best Lap", _fmt_time(analysis.best_lap_time))
    c2.metric("Theoretical Best", _fmt_time(analysis.theoretical_best_time))
    c3.metric("Gap to Theoretical", f"+{analysis.gap_to_theoretical:.3f}s")
    c4.metric("Valid Laps", f"{analysis.valid_lap_count} / {analysis.lap_count}")

    # --- Lap Times ---
    with st.expander("All Lap Times"):
        for lap_num, lap_time in analysis.lap_times:
            marker = " **[best]**" if lap_time == analysis.best_lap_time else ""
            st.markdown(f"- Lap {lap_num}: {_fmt_time(lap_time)}{marker}")

    # --- Reference Lap (import + debrief) ---
    reference = _render_reference_section(analysis)
    if reference is not None:
        _render_debrief_section(analysis, reference, _is_imperial())

    # --- Speed Trace Plot ---
    st.subheader("Speed Comparison")
    st.markdown(
        f"Best lap ({analysis.best_lap.lap_number}) vs "
        f"comparison lap ({analysis.comparison_lap.lap_number})"
    )
    imp = _is_imperial()
    st.plotly_chart(_speed_trace_plot(analysis, imp), use_container_width=True)

    # --- Time Delta Plot ---
    st.subheader("Cumulative Time Delta")
    st.plotly_chart(_time_delta_plot(analysis, imp), use_container_width=True)

    # --- Priority Corners ---
    st.subheader("Priority Corners")
    corner_segments = {
        c.corner_number: c for c in analysis.segmentation.corners
    }
    if not analysis.priority_corners:
        st.info("No significant corner deltas detected.")
    else:
        for i, pc in enumerate(analysis.priority_corners, 1):
            delta_str = f"+{pc.time_lost:.3f}s" if pc.time_lost > 0 else f"{pc.time_lost:.3f}s"
            seg = corner_segments.get(pc.corner_number)
            corner_label = pc.corner_name or f"Corner {pc.corner_number}"
            if seg and analysis.segmentation.track_length > 0:
                pct = seg.apex_distance / analysis.segmentation.track_length * 100
                pos_str = f" — {pct:.0f}% into lap ({fmt_distance(seg.apex_distance, _is_imperial())})"
            else:
                pos_str = ""
            st.markdown(f"**#{i} — {corner_label}{pos_str}** ({delta_str})")

            cols = st.columns(4)
            cols[0].metric("Issue", pc.issue_type.title())
            cols[1].metric(
                "Braking",
                fmt_distance(pc.braking_delta, _is_imperial(), signed=True),
                help="Positive = comparison brakes later",
            )
            cols[2].metric(
                "Apex Speed",
                fmt_speed(pc.apex_speed_delta, _is_imperial()),
                help="Positive = comparison faster at apex",
            )
            cols[3].metric(
                "Exit Speed",
                fmt_speed(pc.exit_speed_delta, _is_imperial()),
                help="Positive = comparison faster at exit",
            )

    # --- AI Coaching ---
    if run_ai:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            st.warning("Set ANTHROPIC_API_KEY in .env to enable AI coaching tips.")
        else:
            st.subheader("AI Coaching")
            with st.spinner("Generating coaching tips..."):
                try:
                    synthesizer = Synthesizer(api_key=api_key)
                    report = synthesizer.generate_coaching_narrative(analysis)
                except Exception as e:
                    st.error(f"AI coaching generation failed: {e}")
                    return

            st.markdown(report.report_text)

            with st.expander("AI Metadata"):
                st.markdown(
                    f"- **Model**: {report.model_used}\n"
                    f"- **Input tokens**: {report.input_tokens:,}\n"
                    f"- **Output tokens**: {report.output_tokens:,}"
                )


# --- Helpers ---


def _fmt_time(seconds: float) -> str:
    """Format seconds as M:SS.mmm."""
    mins = int(seconds // 60)
    secs = seconds % 60
    return f"{mins}:{secs:06.3f}"


def _combo_key(analysis: CoachingAnalysis) -> str:
    """Stable ReferenceStore key for the session's track.

    Prefers the iRacing numeric track ID; falls back to the track name
    when the IBT file did not carry an ID (the store just needs keys
    that are consistent across sessions).
    """
    return analysis.track_id or analysis.track_name


def _render_reference_section(analysis: CoachingAnalysis) -> ReferenceLap | None:
    """Reference lap status and Garage 61 CSV import. Returns the stored
    reference for this car/track combo, or None if there isn't one."""
    store = ReferenceStore(REFERENCE_DB)
    reference = store.get(_combo_key(analysis), analysis.car_name)

    with st.expander("Reference Lap", expanded=reference is None):
        if reference is not None:
            driver = f" by {reference.meta.driver_name}" if reference.meta.driver_name else ""
            st.markdown(
                f"Current reference: **{_fmt_time(reference.meta.lap_time)}**"
                f"{driver} (source: {reference.meta.source})"
            )
        else:
            st.markdown(
                "No reference lap stored for this car/track combo yet. "
                "Import a Garage 61 lap CSV to enable the reference debrief."
            )

        csv_file = st.file_uploader("Garage 61 lap CSV", type=["csv"], key="g61_csv")
        driver_name = st.text_input(
            "Reference driver name (optional)", key="g61_driver_name"
        )
        if csv_file is not None and st.button("Save as reference"):
            try:
                csv_file.seek(0)
                lap = import_g61_csv(
                    csv_file, track_length_m=analysis.best_lap.track_length
                )
            except G61ImportError as e:
                st.error(str(e))
            else:
                store.save(
                    _combo_key(analysis),
                    analysis.car_name,
                    lap,
                    source="g61",
                    driver_name=driver_name or None,
                )
                st.rerun()

    return reference


def _render_debrief_section(
    analysis: CoachingAnalysis, reference: ReferenceLap, imperial: bool
) -> None:
    """Debrief the driver's best lap against the stored reference lap."""
    st.subheader("Reference Debrief")

    corners = (
        TrackDB(DB_PATH).get_corners(analysis.track_id) if analysis.track_id else []
    )

    try:
        result = build_debrief(analysis.best_lap, reference.lap, corners)
    except Exception as e:
        st.error(f"Debrief failed: {e}")
        return

    st.caption(
        f"Your lap {_fmt_time(result.driver_lap_time)} vs reference "
        f"{_fmt_time(result.reference_lap_time)} "
        f"(gap {result.total_time_delta:+.3f}s, alignment offset "
        f"{fmt_distance(result.alignment_offset_m, imperial, signed=True)})"
    )

    best = analysis.best_lap
    if np.any(best.lat) and np.any(best.lon):
        # The debrief grid is truncated to the shorter of driver/reference;
        # slice GPS to match so the region masks line up.
        n = len(result.distance)
        st.plotly_chart(
            build_loss_map(
                best.lat[:n],
                best.lon[:n],
                result.distance,
                [d.region for d in result.diagnoses],
                labels=[d.label for d in result.diagnoses],
            ),
            use_container_width=True,
        )

    if not result.diagnoses:
        st.info("No significant loss regions found against the reference.")
        return

    for diag in result.diagnoses:
        with st.container(border=True):
            st.markdown(f"**{diag.label}** — +{diag.region.time_lost:.2f}s lost")
            c1, c2, c3 = st.columns(3)
            c1.metric(
                "Braking Point",
                fmt_distance(diag.braking_delta_m, imperial, signed=True)
                if diag.braking_delta_m is not None
                else "—",
                help="Negative = you brake earlier than the reference",
            )
            c2.metric(
                "Min Speed",
                fmt_speed(diag.min_speed_delta_ms, imperial),
                help="Negative = you over-slow the corner",
            )
            c3.metric(
                "Back to Power",
                fmt_distance(diag.throttle_delta_m, imperial, signed=True)
                if diag.throttle_delta_m is not None
                else "—",
                help="Positive = you pick up throttle later than the reference",
            )


def _speed_trace_plot(analysis: CoachingAnalysis, imperial: bool) -> go.Figure:
    """Build a Plotly speed comparison chart."""
    best = analysis.best_lap
    comp = analysis.comparison_lap
    min_len = min(len(best.distance), len(comp.distance))

    fig = go.Figure()

    x_best = distance_value(best.distance[:min_len], imperial)
    x_comp = distance_value(comp.distance[:min_len], imperial)

    # Best lap
    fig.add_trace(go.Scatter(
        x=x_best,
        y=speed_value(best.speed[:min_len], imperial),
        name=f"Lap {best.lap_number} (best)",
        line=dict(color="#00cc66", width=1.5),
    ))

    # Comparison lap
    fig.add_trace(go.Scatter(
        x=x_comp,
        y=speed_value(comp.speed[:min_len], imperial),
        name=f"Lap {comp.lap_number} (comparison)",
        line=dict(color="#ff4444", width=1.5),
    ))

    # Corner shading
    for corner in analysis.segmentation.corners:
        label = analysis.corner_names.get(corner.corner_number, f"C{corner.corner_number}")
        fig.add_vrect(
            x0=distance_value(corner.distance_start, imperial),
            x1=distance_value(corner.distance_end, imperial),
            fillcolor="rgba(100,100,100,0.1)",
            line_width=0,
            annotation_text=label,
            annotation_position="top left",
            annotation_font_size=9,
        )

    fig.update_layout(
        xaxis_title=f"Distance ({distance_unit(imperial)})",
        yaxis_title=f"Speed ({speed_unit(imperial)})",
        height=400,
        margin=dict(l=40, r=20, t=20, b=40),
        legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99),
        hovermode="x unified",
    )

    return fig


def _time_delta_plot(analysis: CoachingAnalysis, imperial: bool) -> go.Figure:
    """Build a Plotly cumulative time delta chart."""
    comp = analysis.lap_comparison
    min_len = len(comp.cumulative_time_delta)
    distance = distance_value(analysis.best_lap.distance[:min_len], imperial)
    delta = comp.cumulative_time_delta

    # Split into positive (slower) and negative (faster) for coloring
    pos_delta = np.where(delta > 0, delta, 0)
    neg_delta = np.where(delta < 0, delta, 0)

    fig = go.Figure()

    # Slower regions (red fill)
    fig.add_trace(go.Scatter(
        x=distance, y=pos_delta,
        fill="tozeroy",
        fillcolor="rgba(255,68,68,0.3)",
        line=dict(color="rgba(255,68,68,0)", width=0),
        showlegend=False,
        hoverinfo="skip",
    ))

    # Faster regions (green fill)
    fig.add_trace(go.Scatter(
        x=distance, y=neg_delta,
        fill="tozeroy",
        fillcolor="rgba(0,204,102,0.3)",
        line=dict(color="rgba(0,204,102,0)", width=0),
        showlegend=False,
        hoverinfo="skip",
    ))

    # Main line
    fig.add_trace(go.Scatter(
        x=distance, y=delta,
        name="Time delta",
        line=dict(color="white", width=1.5),
    ))

    # Corner apex markers
    for corner in analysis.segmentation.corners:
        label = analysis.corner_names.get(corner.corner_number, f"C{corner.corner_number}")
        fig.add_vline(
            x=distance_value(corner.apex_distance, imperial),
            line=dict(color="rgba(150,150,150,0.4)", width=1, dash="dot"),
            annotation_text=label,
            annotation_position="top",
            annotation_font_size=9,
        )

    fig.update_layout(
        xaxis_title=f"Distance ({distance_unit(imperial)})",
        yaxis_title="Time Delta (s)",
        height=300,
        margin=dict(l=40, r=20, t=20, b=40),
        hovermode="x unified",
    )

    return fig
