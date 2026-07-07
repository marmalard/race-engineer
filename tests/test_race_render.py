"""Tests for the deterministic narrative -> markdown renderer."""

from tests.test_race_models import _minimal_narrative

from core.race.render import render_narrative_markdown


def test_render_contains_all_sections():
    md = render_narrative_markdown(_minimal_narrative())
    assert "Oulton Park" in md
    assert "P8" in md and "P6" in md          # start -> finish
    assert "Knickerbrook" in md               # incident corner
    assert "1420" in md and "1445" in md      # iRating old/new
    assert "Pace deserved" in md or "pace ranked" in md.lower()


def test_render_handles_partial_narrative():
    narrative = _minimal_narrative()
    narrative.pace = None
    narrative.attribution = None
    narrative.lap1 = None
    narrative.gaps = []
    md = render_narrative_markdown(narrative)
    assert "Oulton Park" in md
    assert "not available" in md.lower()      # honest about missing data


def test_render_never_contains_placeholder_text():
    md = render_narrative_markdown(_minimal_narrative())
    assert "TODO" not in md and "None" not in md
