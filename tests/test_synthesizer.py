"""Tests for the AI synthesis layer.

Uses mocks for the Claude API — no real API calls.
"""

from unittest.mock import MagicMock, patch
import pytest

from core.coaching.synthesizer import Synthesizer, ScoutingReport, Citation


def _make_text_block(text: str, citations=None):
    """Create a mock text block matching the Anthropic SDK structure."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    block.citations = citations or []
    return block


def _make_tool_use_block():
    """Create a mock tool use block (web search)."""
    block = MagicMock()
    block.type = "tool_use"
    return block


def _make_web_citation(url: str, title: str, cited_text: str = ""):
    """Create a mock web search citation."""
    cite = MagicMock()
    cite.type = "web_search_result_location"
    cite.url = url
    cite.title = title
    cite.cited_text = cited_text
    return cite


class TestExtractText:
    def test_extracts_text_blocks_only(self):
        """Should extract text from text blocks and skip tool_use blocks."""
        synth = Synthesizer.__new__(Synthesizer)

        response = MagicMock()
        response.content = [
            _make_tool_use_block(),
            _make_text_block("First paragraph."),
            _make_tool_use_block(),
            _make_text_block("Second paragraph."),
        ]

        result = synth._extract_text(response)
        assert result == "First paragraph.\n\nSecond paragraph."

    def test_empty_response(self):
        """Should handle a response with no content blocks."""
        synth = Synthesizer.__new__(Synthesizer)

        response = MagicMock()
        response.content = []

        result = synth._extract_text(response)
        assert result == ""

    def test_single_text_block(self):
        """Should return just the text for a single block."""
        synth = Synthesizer.__new__(Synthesizer)

        response = MagicMock()
        response.content = [_make_text_block("Only block.")]

        result = synth._extract_text(response)
        assert result == "Only block."


class TestExtractCitations:
    def test_extracts_web_citations(self):
        """Should extract URL, title, and cited_text from web search citations."""
        synth = Synthesizer.__new__(Synthesizer)

        citations = [
            _make_web_citation("https://example.com/setup", "Setup Guide", "brake bias 56%"),
        ]
        text_block = _make_text_block("Use brake bias 56%.", citations=citations)

        response = MagicMock()
        response.content = [text_block]

        result = synth._extract_citations(response)
        assert len(result) == 1
        assert result[0].url == "https://example.com/setup"
        assert result[0].title == "Setup Guide"
        assert result[0].cited_text == "brake bias 56%"

    def test_deduplicates_by_url(self):
        """Same URL appearing in multiple blocks should only appear once."""
        synth = Synthesizer.__new__(Synthesizer)

        cite = _make_web_citation("https://example.com/same", "Same Page")
        block1 = _make_text_block("Text 1.", citations=[cite])
        block2 = _make_text_block("Text 2.", citations=[cite])

        response = MagicMock()
        response.content = [block1, block2]

        result = synth._extract_citations(response)
        assert len(result) == 1

    def test_skips_non_web_citations(self):
        """Should only extract web_search_result_location citations."""
        synth = Synthesizer.__new__(Synthesizer)

        other_cite = MagicMock()
        other_cite.type = "char_location"
        other_cite.url = "https://example.com"

        text_block = _make_text_block("Text.", citations=[other_cite])

        response = MagicMock()
        response.content = [text_block]

        result = synth._extract_citations(response)
        assert len(result) == 0

    def test_no_citations_attribute(self):
        """Should handle blocks without citations attribute gracefully."""
        synth = Synthesizer.__new__(Synthesizer)

        block = MagicMock()
        block.type = "text"
        block.text = "Plain text"
        # hasattr(block, 'citations') is True for MagicMock
        block.citations = None

        response = MagicMock()
        response.content = [block]

        result = synth._extract_citations(response)
        assert len(result) == 0


class TestGenerateScoutingReport:
    def test_calls_claude_api_with_correct_params(self):
        """Should call the Claude API with web_search tool configured."""
        with patch("core.coaching.synthesizer.anthropic.Anthropic") as MockAnthropic:
            mock_client = MagicMock()
            MockAnthropic.return_value = mock_client

            # Set up the mock response
            mock_response = MagicMock()
            mock_response.content = [_make_text_block("Scouting report text.")]
            mock_response.model = "claude-sonnet-4-5-20250929"
            mock_response.usage.input_tokens = 100
            mock_response.usage.output_tokens = 200
            mock_client.messages.create.return_value = mock_response

            synth = Synthesizer(api_key="test-key")
            report = synth.generate_scouting_report(
                car_name="BMW M2 CS Racing",
                track_name="Spa-Francorchamps",
                track_config="Grand Prix",
                irating=1500,
            )

            # Verify the API was called
            mock_client.messages.create.assert_called_once()
            call_kwargs = mock_client.messages.create.call_args.kwargs

            # Should use web_search tool
            assert any(t.get("type") == "web_search_20250305" for t in call_kwargs["tools"])

            # Verify the report
            assert report.car == "BMW M2 CS Racing"
            assert report.track == "Spa-Francorchamps"
            assert report.report_text == "Scouting report text."
            assert report.input_tokens == 100
            assert report.output_tokens == 200

    def test_report_includes_citations(self):
        """Scouting report should include extracted citations."""
        with patch("core.coaching.synthesizer.anthropic.Anthropic") as MockAnthropic:
            mock_client = MagicMock()
            MockAnthropic.return_value = mock_client

            cite = _make_web_citation("https://forum.com/spa", "Spa Setup Tips")
            text_block = _make_text_block("Brake at 100m marker.", citations=[cite])

            mock_response = MagicMock()
            mock_response.content = [text_block]
            mock_response.model = "claude-sonnet-4-5-20250929"
            mock_response.usage.input_tokens = 50
            mock_response.usage.output_tokens = 100
            mock_client.messages.create.return_value = mock_response

            synth = Synthesizer(api_key="test-key")
            report = synth.generate_scouting_report("BMW", "Spa")

            assert len(report.citations) == 1
            assert report.citations[0].url == "https://forum.com/spa"
