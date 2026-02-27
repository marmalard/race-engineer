"""Lap Coaching page — post-session telemetry analysis and coaching."""

import os

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from core.coaching.analyzer import CoachingAnalysis, analyze_session
from core.coaching.synthesizer import Synthesizer


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

    if not st.button("Analyze Session", type="primary"):
        return

    # --- Analysis ---
    with st.spinner("Parsing telemetry and analyzing laps..."):
        try:
            analysis = analyze_session(
                ibt_data=bytes(uploaded_file.getbuffer()),
                track_type=track_type,
            )
        except ValueError as e:
            st.error(str(e))
            return
        except Exception as e:
            st.error(f"Analysis failed: {e}")
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

    # --- Speed Trace Plot ---
    st.subheader("Speed Comparison")
    st.markdown(
        f"Best lap ({analysis.best_lap.lap_number}) vs "
        f"comparison lap ({analysis.comparison_lap.lap_number})"
    )
    st.plotly_chart(_speed_trace_plot(analysis), use_container_width=True)

    # --- Time Delta Plot ---
    st.subheader("Cumulative Time Delta")
    st.plotly_chart(_time_delta_plot(analysis), use_container_width=True)

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
            if seg and analysis.segmentation.track_length > 0:
                pct = seg.apex_distance / analysis.segmentation.track_length * 100
                pos_str = f" — {pct:.0f}% into lap ({seg.apex_distance:.0f}m)"
            else:
                pos_str = ""
            st.markdown(f"**#{i} — Corner {pc.corner_number}{pos_str}** ({delta_str})")

            cols = st.columns(4)
            cols[0].metric("Issue", pc.issue_type.title())
            cols[1].metric(
                "Braking",
                f"{pc.braking_delta:+.1f}m",
                help="Positive = comparison brakes later",
            )
            cols[2].metric(
                "Apex Speed",
                f"{pc.apex_speed_delta * 3.6:+.1f} km/h",
                help="Positive = comparison faster at apex",
            )
            cols[3].metric(
                "Exit Speed",
                f"{pc.exit_speed_delta * 3.6:+.1f} km/h",
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


def _speed_trace_plot(analysis: CoachingAnalysis) -> go.Figure:
    """Build a Plotly speed comparison chart."""
    best = analysis.best_lap
    comp = analysis.comparison_lap
    min_len = min(len(best.distance), len(comp.distance))

    fig = go.Figure()

    # Best lap
    fig.add_trace(go.Scatter(
        x=best.distance[:min_len],
        y=best.speed[:min_len] * 3.6,  # m/s → km/h
        name=f"Lap {best.lap_number} (best)",
        line=dict(color="#00cc66", width=1.5),
    ))

    # Comparison lap
    fig.add_trace(go.Scatter(
        x=comp.distance[:min_len],
        y=comp.speed[:min_len] * 3.6,
        name=f"Lap {comp.lap_number} (comparison)",
        line=dict(color="#ff4444", width=1.5),
    ))

    # Corner shading
    for corner in analysis.segmentation.corners:
        fig.add_vrect(
            x0=corner.distance_start,
            x1=corner.distance_end,
            fillcolor="rgba(100,100,100,0.1)",
            line_width=0,
            annotation_text=f"C{corner.corner_number}",
            annotation_position="top left",
            annotation_font_size=9,
        )

    fig.update_layout(
        xaxis_title="Distance (m)",
        yaxis_title="Speed (km/h)",
        height=400,
        margin=dict(l=40, r=20, t=20, b=40),
        legend=dict(yanchor="top", y=0.99, xanchor="right", x=0.99),
        hovermode="x unified",
    )

    return fig


def _time_delta_plot(analysis: CoachingAnalysis) -> go.Figure:
    """Build a Plotly cumulative time delta chart."""
    comp = analysis.lap_comparison
    min_len = len(comp.cumulative_time_delta)
    distance = analysis.best_lap.distance[:min_len]
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
        fig.add_vline(
            x=corner.apex_distance,
            line=dict(color="rgba(150,150,150,0.4)", width=1, dash="dot"),
            annotation_text=f"C{corner.corner_number}",
            annotation_position="top",
            annotation_font_size=9,
        )

    fig.update_layout(
        xaxis_title="Distance (m)",
        yaxis_title="Time Delta (s)",
        height=300,
        margin=dict(l=40, r=20, t=20, b=40),
        hovermode="x unified",
    )

    return fig
