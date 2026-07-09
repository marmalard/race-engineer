"""Pit Wall theme — the app's single source of visual truth.

Dark carbon, telemetry-green accent, monospace numerals. Display-only:
pages call apply_theme() (idempotent per rerun), section_header() for
labeled sections, and chart_layout() for consistent Plotly styling.

Fonts load from Google Fonts when online; every family carries a full
system fallback stack (Segoe UI / Consolas), so offline use just
degrades to the fallbacks — never to broken layout.
"""

from __future__ import annotations

import streamlit as st

# --- Palette (mirrors .streamlit/config.toml [theme]) --------------------

ACCENT = "#00d17a"        # telemetry green — the one loud thing
ACCENT_DIM = "#00a862"
BG = "#0e1116"            # carbon
PANEL = "#161b24"
PANEL_DEEP = "#10151d"    # chart wells
BORDER = "#232b38"
GRID = "#1c2330"
TEXT = "#e6e9ee"
TEXT_MUTED = "#8b94a3"
WARN = "#ffb454"
LOSS = "#ff5d5d"

# Rival trace colors — cool and muted so the green player trace leads
RIVAL_COLORS = ["#4f8dff", "#b48cff", "#41c7ff", "#ff9f43"]

FONT_DISPLAY = "'Chakra Petch', 'Segoe UI', system-ui, sans-serif"
FONT_BODY = "'IBM Plex Sans', 'Segoe UI', system-ui, sans-serif"
FONT_MONO = "'IBM Plex Mono', Consolas, 'Courier New', monospace"

_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

/* --- Atmosphere ------------------------------------------------------ */
.stApp {{
    background:
        radial-gradient(1200px 500px at 85% -10%, rgba(0, 209, 122, 0.05), transparent 60%),
        radial-gradient(900px 400px at -10% 110%, rgba(79, 141, 255, 0.04), transparent 55%),
        {BG};
    font-family: {FONT_BODY};
}}

/* --- Typography ------------------------------------------------------ */
h1, h2, h3 {{
    font-family: {FONT_DISPLAY} !important;
    letter-spacing: 0.045em;
}}
h1 {{ text-transform: uppercase; }}
code, pre, kbd {{ font-family: {FONT_MONO}; }}

/* --- Sidebar --------------------------------------------------------- */
[data-testid="stSidebar"] {{
    background: #0b0e13;
    border-right: 1px solid {BORDER};
}}
.re-brand {{
    font-family: {FONT_DISPLAY};
    font-size: 1.25rem;
    font-weight: 700;
    letter-spacing: 0.18em;
    color: {TEXT};
    border-bottom: 2px solid {ACCENT};
    padding-bottom: 0.55rem;
    margin-bottom: 0.35rem;
}}
.re-tagline {{
    font-size: 0.72rem;
    color: {TEXT_MUTED};
    letter-spacing: 0.06em;
    margin-bottom: 1.2rem;
}}

/* --- Metric cards ---------------------------------------------------- */
[data-testid="stMetric"] {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 0.75rem 0.9rem;
}}
[data-testid="stMetricLabel"] {{
    color: {TEXT_MUTED};
    text-transform: uppercase;
    letter-spacing: 0.1em;
    font-size: 0.7rem;
}}
[data-testid="stMetricValue"] {{
    font-family: {FONT_MONO};
    font-weight: 600;
}}
[data-testid="stMetricDelta"] {{
    font-family: {FONT_MONO};
    font-size: 0.8rem;
}}

/* --- Section labels + header strip ----------------------------------- */
.re-section {{
    display: flex;
    align-items: center;
    gap: 0.7rem;
    font-family: {FONT_DISPLAY};
    font-size: 0.82rem;
    font-weight: 600;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: {ACCENT};
    margin: 1.6rem 0 0.7rem 0;
}}
.re-section::after {{
    content: "";
    flex: 1;
    height: 1px;
    background: linear-gradient(90deg, {BORDER}, transparent);
}}
.re-headerstrip {{
    font-family: {FONT_MONO};
    font-size: 0.82rem;
    color: {TEXT_MUTED};
    letter-spacing: 0.05em;
    background: {PANEL};
    border: 1px solid {BORDER};
    border-left: 3px solid {ACCENT};
    border-radius: 0 8px 8px 0;
    padding: 0.55rem 0.9rem;
    margin-bottom: 1rem;
}}
.re-headerstrip b {{ color: {TEXT}; }}

/* --- Buttons ---------------------------------------------------------- */
.stButton > button, .stDownloadButton > button {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    font-family: {FONT_DISPLAY};
    letter-spacing: 0.06em;
    transition: border-color 120ms ease, color 120ms ease;
}}
.stButton > button:hover, .stDownloadButton > button:hover {{
    border-color: {ACCENT};
    color: {ACCENT};
}}

/* --- Chat -------------------------------------------------------------- */
[data-testid="stChatMessage"] {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}

/* --- Bordered containers (st.container(border=True)) ------------------- */
[data-testid="stVerticalBlockBorderWrapper"] {{
    border-color: {BORDER} !important;
    border-radius: 8px;
    background: {PANEL};
}}

/* --- Tabs --------------------------------------------------------------- */
.stTabs [data-baseweb="tab"] {{
    font-family: {FONT_DISPLAY};
    letter-spacing: 0.08em;
    text-transform: uppercase;
    font-size: 0.8rem;
}}
</style>
"""


def apply_theme() -> None:
    """Inject the shared Pit Wall CSS. Call once per page run."""
    st.markdown(_CSS, unsafe_allow_html=True)


def brand_sidebar() -> None:
    """Render the wordmark + tagline at the top of the sidebar."""
    st.sidebar.markdown(
        '<div class="re-brand">RACE ENGINEER</div>'
        '<div class="re-tagline">Never start blind. Never race alone.</div>',
        unsafe_allow_html=True,
    )


def section_header(title: str) -> None:
    """Small-caps green section label with a fading rule."""
    st.markdown(f'<div class="re-section">{title}</div>', unsafe_allow_html=True)


def header_strip(parts: list[str]) -> None:
    """Monospace context strip, e.g. track / car / series / SoF."""
    joined = " · ".join(p for p in parts if p)
    st.markdown(
        f'<div class="re-headerstrip">{joined}</div>', unsafe_allow_html=True
    )


def chart_layout(**overrides) -> dict:
    """Consistent Plotly layout for Pit Wall charts.

    Pure dict (no Streamlit) so it is unit-testable; pass the result to
    fig.update_layout(**chart_layout(...)). Keyword overrides win.
    """
    layout: dict = {
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": PANEL_DEEP,
        "font": {"family": FONT_MONO, "color": TEXT_MUTED, "size": 12},
        "margin": {"l": 10, "r": 10, "t": 36, "b": 10},
        "height": 300,
        "xaxis": {"gridcolor": GRID, "zerolinecolor": BORDER},
        "yaxis": {"gridcolor": GRID, "zerolinecolor": BORDER},
        "legend": {"bgcolor": "rgba(0,0,0,0)"},
        "hoverlabel": {"bgcolor": PANEL, "bordercolor": BORDER},
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(layout.get(key), dict):
            layout[key] = {**layout[key], **value}
        else:
            layout[key] = value
    return layout
