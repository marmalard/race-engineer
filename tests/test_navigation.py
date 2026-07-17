"""Nav registry coupling tests (A0).

NAV_SPEC is the single source of truth for the shell. These tests pin:
(a) the grouping the spec mandates, (b) URL-path uniqueness (pages are
linkable), (c) that every module/function actually exists — a renamed
render function must fail HERE, not at app startup (the 2026-07-14
Toolbox flag-drift lesson applied to navigation).
"""

import importlib

from app.navigation import NAV_SPEC


class TestNavSpec:
    def test_groups_exact(self):
        assert [g for g, _ in NAV_SPEC] == ["Race", "Practice", "Help", "Host"]

    def test_race_group_pages_exact(self):
        race = dict(NAV_SPEC)["Race"]
        assert [p.title for p in race] == [
            "Start", "Week Plan", "Race Debrief", "Race Briefing",
            "Driver Profile",
        ]

    def test_practice_group_pages_exact(self):
        practice = dict(NAV_SPEC)["Practice"]
        assert [p.title for p in practice] == ["Progression", "Lap Coaching", "Scouting Report"]

    def test_url_paths_unique(self):
        paths = [p.url_path for _, specs in NAV_SPEC for p in specs]
        assert len(paths) == len(set(paths))

    def test_exactly_one_default_and_it_is_start(self):
        defaults = [
            p for _, specs in NAV_SPEC for p in specs if p.default
        ]
        assert len(defaults) == 1
        assert defaults[0].title == "Start"

    def test_every_render_function_exists(self):
        for _, specs in NAV_SPEC:
            for spec in specs:
                module = importlib.import_module(spec.module)
                func = getattr(module, spec.func)
                assert callable(func), f"{spec.module}.{spec.func}"

    def test_host_group_pages_exact(self):
        # Settings & Keys is the re-editable Setup page (B2 spec 4) —
        # it must stay reachable after first run so keys can rotate
        # without hand-editing .env.
        host = dict(NAV_SPEC)["Host"]
        assert [p.title for p in host] == ["Toolbox", "Settings & Keys"]
