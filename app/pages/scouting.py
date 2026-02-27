"""Scouting Report page — pre-session briefing for a car/track combo."""

import os

import streamlit as st

from core.coaching.synthesizer import Synthesizer


def render_scouting_page() -> None:
    """Render the scouting report page."""
    st.header("Scouting Report")
    st.markdown(
        "Get a pre-session briefing for any car/track combination. "
        "Powered by AI with live web search for community knowledge."
    )

    col1, col2 = st.columns(2)
    with col1:
        car = st.text_input("Car", placeholder="e.g., Mazda MX-5 Cup")
    with col2:
        track = st.text_input("Track", placeholder="e.g., Laguna Seca")

    col3, col4 = st.columns(2)
    with col3:
        track_config = st.text_input(
            "Configuration (optional)",
            placeholder="e.g., Full Course",
        )
    with col4:
        irating = st.number_input(
            "Your iRating (optional)",
            min_value=0,
            max_value=10000,
            value=0,
            step=100,
        )

    if st.button("Generate Report", type="primary"):
        if not car or not track:
            st.error("Please enter both car and track.")
            return

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            st.error(
                "ANTHROPIC_API_KEY not set. "
                "Add it to your .env file or set the environment variable."
            )
            return

        synthesizer = Synthesizer(api_key=api_key)

        with st.spinner("Researching and generating scouting report..."):
            try:
                report = synthesizer.generate_scouting_report(
                    car_name=car,
                    track_name=track,
                    track_config=track_config or None,
                    irating=irating if irating > 0 else None,
                )
            except Exception as e:
                st.error(f"Failed to generate report: {e}")
                return

        st.markdown("---")
        st.markdown(report.report_text)

        if report.citations:
            with st.expander("Sources"):
                for cite in report.citations:
                    st.markdown(f"- [{cite.title}]({cite.url})")

        with st.expander("Report Metadata"):
            st.markdown(
                f"- **Model**: {report.model_used}\n"
                f"- **Input tokens**: {report.input_tokens:,}\n"
                f"- **Output tokens**: {report.output_tokens:,}"
            )
