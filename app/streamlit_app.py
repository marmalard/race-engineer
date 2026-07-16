"""Race Engineer — Main Streamlit entry point (st.navigation shell)."""

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

from app.components.prefs import load_unit_system, save_unit_system  # noqa: E402
from app.components.theme import apply_theme, brand_sidebar  # noqa: E402
from app.navigation import build_pages, page_for  # noqa: E402
from core.config.env_setup import is_complete  # noqa: E402

apply_theme()

# First run (B2 spec 4): until the required keys exist, the Setup page
# is the only page -- no nav, no units control.
if not is_complete():
    pg = st.navigation([page_for("setup")], position="sidebar")
    brand_sidebar()
    pg.run()
else:
    # st.navigation renders its own grouped nav at the top of the sidebar;
    # the brand block and units toggle follow below it.
    pg = st.navigation(build_pages(), position="sidebar")

    brand_sidebar()

    # Units survive reloads: seed a fresh session from the host pref file,
    # save on change (deselecting reads as Metric everywhere).
    if "unit_system" not in st.session_state:
        st.session_state["unit_system"] = load_unit_system()

    def _save_units() -> None:
        save_unit_system(st.session_state.get("unit_system") or "Metric")

    st.sidebar.segmented_control(
        "Units", ["Metric", "Imperial"], key="unit_system",
        on_change=_save_units,
    )

    pg.run()
