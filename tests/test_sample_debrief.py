"""Sample debrief (A3) -- frozen synthetic narrative, round-trip pinned.

If RaceNarrative's model evolves, this test breaks loudly instead of
the Start page's sample button breaking silently.
"""

from app.components.sample import (
    load_sample_debrief_text,
    load_sample_narrative,
)
from core.race.models import RaceNarrative


class TestSampleNarrative:
    def test_loads_and_round_trips(self):
        narrative = load_sample_narrative()
        rebuilt = RaceNarrative.from_dict(narrative.to_dict())
        assert rebuilt == narrative

    def test_is_clearly_synthetic(self):
        n = load_sample_narrative()
        # Sentinel ids: can never collide with a real captured race.
        assert n.header.subsession_id == 0
        assert n.header.cust_id == 0

    def test_has_the_shapes_the_page_renders(self):
        n = load_sample_narrative()
        assert len(n.position_timeline) >= 10
        assert n.lap1 is not None
        assert len(n.gaps) == 2
        assert len(n.incidents) == 1
        assert n.pace is not None
        # Pace honesty (2026-07-15): both views present in the sample.
        assert n.pace.pace_rank is not None
        assert n.pace.all_lap_rank is not None
        assert n.attribution is not None
        assert n.attribution.summary_lines

    def test_narrative_markdown_renders(self):
        from core.race.render import render_narrative_markdown

        md = render_narrative_markdown(load_sample_narrative())
        assert len(md) > 200


class TestSampleDebriefText:
    def test_loads_nonempty_markdown(self):
        text = load_sample_debrief_text()
        assert len(text) > 300
        assert "Sam" in text  # addresses the fictional driver
