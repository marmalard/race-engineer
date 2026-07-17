"""Single source of truth for the app's pages and nav structure (A0).

NAV_SPEC is pure data (coupling-tested in tests/test_navigation.py);
build_pages() turns it into st.Page objects for st.navigation, and
page_for() gives pages a target for st.switch_page / st.page_link
without importing streamlit_app (no circular imports).
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass


@dataclass(frozen=True)
class PageSpec:
    title: str
    icon: str
    url_path: str
    module: str
    func: str
    default: bool = False


NAV_SPEC: list[tuple[str, list[PageSpec]]] = [
    (
        "Race",
        [
            PageSpec("Start", "\U0001f3c1", "start",
                     "app.pages.start", "render_start_page", default=True),
            PageSpec("Week Plan", "\U0001f4c5", "week-plan",
                     "app.pages.week_plan", "render_week_plan_page"),
            PageSpec("Race Debrief", "\U0001f399", "debrief",
                     "app.pages.race_debrief", "render_race_debrief_page"),
            PageSpec("Race Briefing", "\U0001f4cb", "briefing",
                     "app.pages.briefing", "render_briefing_page"),
            PageSpec("Driver Profile", "\U0001f464", "profile",
                     "app.pages.driver_profile", "render_driver_profile_page"),
        ],
    ),
    (
        "Practice",
        [
            PageSpec("Progression", "\U0001f4c8", "progression",
                     "app.pages.progression", "render_progression_page"),
            PageSpec("Lap Coaching", "⏱️", "coaching",
                     "app.pages.coaching", "render_coaching_page"),
            PageSpec("Scouting Report", "\U0001f52d", "scouting",
                     "app.pages.scouting", "render_scouting_page"),
        ],
    ),
    (
        "Help",
        [
            PageSpec("Guide", "\U0001f4d6", "guide",
                     "app.pages.guide", "render_guide_page"),
        ],
    ),
    (
        "Host",
        [
            PageSpec("Toolbox", "\U0001f39b", "toolbox",
                     "app.pages.toolbox", "render_toolbox_page"),
            PageSpec("Settings & Keys", "\U0001f511", "setup",
                     "app.pages.setup", "render_setup_page"),
        ],
    ),
]


def _page(spec: PageSpec):
    import streamlit as st

    render = getattr(importlib.import_module(spec.module), spec.func)
    return st.Page(
        render,
        title=spec.title,
        icon=spec.icon,
        url_path=spec.url_path,
        default=spec.default,
    )


def build_pages() -> dict[str, list]:
    """NAV_SPEC -> {section: [st.Page, ...]} for st.navigation."""
    return {
        section: [_page(spec) for spec in specs]
        for section, specs in NAV_SPEC
    }


def page_for(url_path: str):
    """A st.Page for st.switch_page / st.page_link, by url path."""
    for _, specs in NAV_SPEC:
        for spec in specs:
            if spec.url_path == url_path:
                return _page(spec)
    raise KeyError(url_path)
