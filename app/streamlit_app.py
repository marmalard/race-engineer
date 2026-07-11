"""Race Engineer — Main Streamlit entry point."""

import sys
from pathlib import Path

# Ensure the project root is on sys.path so absolute imports work.
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from dotenv import load_dotenv

load_dotenv()

import streamlit as st

st.set_page_config(
    page_title="Race Engineer",
    page_icon="\U0001f3c1",
    layout="wide",
)

from app.components.theme import apply_theme, brand_sidebar  # noqa: E402

apply_theme()
brand_sidebar()

# Label → dispatch key; emoji live only in the labels so changing them
# can never break the routing below.
PAGES = {
    "\U0001f3c1 Race Debrief": "race_debrief",
    "\U0001f464 Driver Profile": "driver_profile",
    "\U0001f4d6 Guide": "guide",
    "\U0001f52d Scouting Report": "scouting",
    "⏱️ Lap Coaching": "coaching",
    "\U0001f39b Toolbox": "toolbox",
}

choice = st.sidebar.radio("Navigate", list(PAGES), label_visibility="collapsed")
page = PAGES[choice]

st.sidebar.divider()
st.sidebar.radio("Units", ["Metric", "Imperial"], key="unit_system")

if page == "race_debrief":
    from app.pages.race_debrief import render_race_debrief_page

    render_race_debrief_page()
elif page == "guide":
    from app.pages.guide import render_guide_page

    render_guide_page()
elif page == "scouting":
    from app.pages.scouting import render_scouting_page

    render_scouting_page()
elif page == "coaching":
    from app.pages.coaching import render_coaching_page

    render_coaching_page()
elif page == "driver_profile":
    from app.pages.driver_profile import render_driver_profile_page

    render_driver_profile_page()
elif page == "toolbox":
    from app.pages.toolbox import render_toolbox_page

    render_toolbox_page()
