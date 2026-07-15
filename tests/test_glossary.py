"""Glossary component (A2) — two-tier vocabulary, single source of truth."""

import pytest

from app.components.glossary import TERMS, glossary_markdown, help_text


class TestTerms:
    def test_every_term_has_nonempty_help(self):
        for name, term in TERMS.items():
            assert term.help.strip(), name

    def test_tiers_are_only_1_or_2(self):
        assert set(t.tier for t in TERMS.values()) <= {1, 2}

    def test_spec_terms_present(self):
        # The A2 spec list, verbatim.
        for name in [
            "IBT", "iRating", "SR", "SoF", "split", "reference lap",
            "pace-deserved position", "clean lap", "representative lap",
            "Garage 61", "practice PB", "implied iRating", "prep ledger",
        ]:
            assert name in TERMS, name

    def test_platform_terms_are_tier_1(self):
        # Tier 1 = iRacing's own vocabulary (design-language rule 2).
        for name in ["iRating", "SR", "SoF", "split"]:
            assert TERMS[name].tier == 1, name


class TestHelpText:
    def test_returns_the_term_help(self):
        assert help_text("SoF") == TERMS["SoF"].help

    def test_unknown_term_raises(self):
        # A typo in a page should fail a test, not ship an empty tooltip.
        with pytest.raises(KeyError):
            help_text("not-a-term")


class TestGlossaryMarkdown:
    def test_every_term_renders(self):
        md = glossary_markdown()
        for name, term in TERMS.items():
            assert f"**{name}**" in md, name
            assert term.help in md, name

    def test_two_tier_headings(self):
        md = glossary_markdown()
        assert "**iRacing's words**" in md
        assert "**Our words**" in md
