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
    page_icon="\U0001f3ce\ufe0f",
    layout="wide",
)

st.title("Race Engineer")
st.markdown("Your personal iRacing coaching system.")

page = st.sidebar.selectbox(
    "Navigate",
    ["Scouting Report", "Lap Coaching"],
)

if page == "Scouting Report":
    from app.pages.scouting import render_scouting_page

    render_scouting_page()
elif page == "Lap Coaching":
    from app.pages.coaching import render_coaching_page

    render_coaching_page()
