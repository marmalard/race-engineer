"""Lap Coaching page — post-session telemetry analysis and coaching."""

import streamlit as st


def render_coaching_page() -> None:
    """Render the lap coaching page."""
    st.header("Lap Coaching")
    st.markdown(
        "Upload a telemetry file from your iRacing session to get "
        "prioritized coaching on where you're leaving the most time."
    )

    uploaded_file = st.file_uploader(
        "Upload IBT File",
        type=["ibt"],
        help="iRacing telemetry files are located in your Documents/iRacing/telemetry folder",
    )

    if uploaded_file is not None:
        st.info(
            "Telemetry analysis pipeline is under development. "
            "Check back soon for full lap coaching."
        )

        # Placeholder for the full pipeline:
        # 1. Parse IBT file
        # 2. Normalize laps to distance-based
        # 3. Detect corners
        # 4. Compare laps (best vs others)
        # 5. Calculate theoretical best
        # 6. Analyze consistency
        # 7. Generate coaching narrative
        st.markdown(
            "**Coming soon:**\n"
            "- Session summary (best lap, theoretical best, consistency score)\n"
            "- Priority corners with time deltas\n"
            "- Speed trace comparison plots\n"
            "- AI-generated coaching tips"
        )
    else:
        st.markdown(
            "**How it works:**\n\n"
            "1. Drive a practice session in iRacing\n"
            "2. Upload the .ibt telemetry file here\n"
            "3. Get coaching on the 2-3 corners where you're leaving the most time\n\n"
            "The system compares your laps against your own best performance "
            "to find where you're inconsistent or leaving time on the table."
        )
