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


def test_render_without_header_block():
    """include_header=False drops the H1 + summary lines (the app page
    shows that data in its own header strip) but keeps every section."""
    md = render_narrative_markdown(_minimal_narrative(), include_header=False)
    assert "# Race Debrief" not in md
    assert "SoF" not in md.split("##")[0]  # no summary before first section
    assert "## Lap 1" in md and "## Incidents" in md and "## Pace" in md
    # Default is unchanged
    assert "# Race Debrief" in render_narrative_markdown(_minimal_narrative())
