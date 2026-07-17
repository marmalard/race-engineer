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


# ---------------------------------------------------------------------------
# Task 9: Race debrief AI layer
# ---------------------------------------------------------------------------

from tests.test_race_models import _minimal_narrative  # noqa: E402

from core.coaching.prompts.race_debrief import (  # noqa: E402
    RACE_DEBRIEF_SYSTEM_PROMPT,
    build_race_chat_system,
    build_race_debrief_prompt,
)


def test_race_debrief_system_prompt_carries_tone_contract():
    text = RACE_DEBRIEF_SYSTEM_PROMPT.lower()
    assert "engineer" in text
    assert "never" in text          # never scold / never invent
    assert "2" in RACE_DEBRIEF_SYSTEM_PROMPT or "two" in text  # takeaway cap


def test_build_race_debrief_prompt_embeds_narrative_json():
    prompt = build_race_debrief_prompt(_minimal_narrative())
    assert "86748877" in prompt
    assert "Knickerbrook" in prompt
    assert "Anthony Moorman" in prompt


def test_build_race_chat_system_includes_debrief_and_grounding():
    system = build_race_chat_system(_minimal_narrative(), "You raced well.")
    assert "You raced well." in system
    assert "Knickerbrook" in system
    assert "don't have that" in system.lower() or "not in the data" in system.lower()


class _FakeMessages:
    def __init__(self, reply_text: str):
        self.reply_text = reply_text
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)

        class _Block:
            type = "text"
            text = self.reply_text

        class _Usage:
            input_tokens = 10
            output_tokens = 20

        class _Response:
            content = [_Block()]
            usage = _Usage()
            model = kwargs["model"]

        return _Response()


def _synthesizer_with_fake(reply_text: str):
    from core.coaching.synthesizer import Synthesizer

    synth = Synthesizer(api_key="fake-key")
    fake = _FakeMessages(reply_text)
    synth.client.messages = fake
    return synth, fake


def test_generate_race_debrief_returns_report():
    synth, fake = _synthesizer_with_fake("Solid recovery drive.")
    report = synth.generate_race_debrief(_minimal_narrative())
    assert report.report_text == "Solid recovery drive."
    assert report.track == "Oulton Park Circuit"
    # No web search tools on the debrief path — facts come from the narrative
    assert "tools" not in fake.calls[0]


def test_race_chat_reply_threads_history_and_caps_it():
    synth, fake = _synthesizer_with_fake("About lap 9...")
    history = [{"role": "user", "content": f"q{i}"} for i in range(30)]
    history += [{"role": "assistant", "content": "a"}, {"role": "user", "content": "final"}]
    reply = synth.race_chat_reply(_minimal_narrative(), "Debrief.", history)
    assert reply == "About lap 9..."
    sent = fake.calls[0]["messages"]
    assert len(sent) <= 20            # capped
    assert sent[-1]["content"] == "final"


def test_race_chat_reply_first_message_is_always_user():
    """Capped history must never start with an assistant turn.

    With 15 exchanges (30 msgs) + 1 final user message = 31 total,
    slicing the last 20 starts at index 11 which is an assistant turn.
    The Anthropic Messages API rejects a first message with role 'assistant'.
    """
    synth, fake = _synthesizer_with_fake("Reply.")
    history: list[dict] = []
    for i in range(15):
        history.append({"role": "user", "content": f"q{i}"})
        history.append({"role": "assistant", "content": f"a{i}"})
    history.append({"role": "user", "content": "final"})
    # 31 messages total; last-20 slice starts at index 11 (assistant a5)
    assert len(history) == 31

    synth.race_chat_reply(_minimal_narrative(), "Debrief.", history)
    sent = fake.calls[0]["messages"]

    assert sent[0]["role"] == "user", (
        f"First sent message must be 'user', got '{sent[0]['role']}'"
    )
    assert len(sent) <= 20
    assert sent[-1]["content"] == "final"


# ---------------------------------------------------------------------------
# Task 9 (week plan): week-plan prompts + synthesizer methods
# ---------------------------------------------------------------------------

from core.coaching.prompts.week_plan import (  # noqa: E402
    WEEKPLAN_SYSTEM_PROMPT,
    build_week_plan_chat_system,
    build_week_plan_prompt,
)


class TestWeekPlanPrompts:
    def test_system_prompt_never_gates(self):
        low = WEEKPLAN_SYSTEM_PROMPT.lower()
        # The rule is stated: prompt tells the model the sentence is banned
        assert "never" in low and "not ready" in low

    def test_chat_system_grounds_in_plan_and_narrative(self):
        out = build_week_plan_chat_system('{"week_start": "x"}', "narr")
        assert '{"week_start": "x"}' in out and "narr" in out

    def test_build_week_plan_prompt_contains_plan_json(self):
        prompt = build_week_plan_prompt('{"week_start": "2026-07-21"}')
        assert '{"week_start": "2026-07-21"}' in prompt

    def test_build_week_plan_prompt_threads_profile_block(self):
        prompt = build_week_plan_prompt('{}', profile_block="Your tendency: brake late.")
        assert "Your tendency: brake late." in prompt

    def test_build_week_plan_prompt_no_profile_block_still_valid(self):
        prompt = build_week_plan_prompt('{"week_start": "2026-07-21"}', profile_block="")
        # No profile block — the empty-profile branch should not inject any placeholder
        assert "profile_block" not in prompt


class TestWeekPlanNarrative:
    def test_generate_week_plan_narrative_uses_weekplan_system_prompt(self):
        synth, fake = _synthesizer_with_fake("Here is your week.")
        result = synth.generate_week_plan_narrative('{"week_start": "2026-07-21"}')
        assert result == "Here is your week."
        call = fake.calls[0]
        # 1) system must be WEEKPLAN_SYSTEM_PROMPT exactly
        assert call["system"] == WEEKPLAN_SYSTEM_PROMPT

    def test_generate_week_plan_narrative_embeds_plan_json_in_user_message(self):
        synth, fake = _synthesizer_with_fake("Ready.")
        plan_json = '{"week_start": "2026-07-21", "curve_filled": false}'
        synth.generate_week_plan_narrative(plan_json)
        call = fake.calls[0]
        # 2) the user message must contain the plan JSON
        user_content = call["messages"][0]["content"]
        assert plan_json in user_content

    def test_generate_week_plan_narrative_threads_profile_block(self):
        synth, fake = _synthesizer_with_fake("Narrative.")
        synth.generate_week_plan_narrative(
            '{"week_start": "x"}',
            profile_block="4 races — incidents are high.",
        )
        call = fake.calls[0]
        # 3) profile_block threaded through when provided
        user_content = call["messages"][0]["content"]
        assert "4 races — incidents are high." in user_content

    def test_generate_week_plan_narrative_max_tokens_800(self):
        synth, fake = _synthesizer_with_fake("Ok.")
        synth.generate_week_plan_narrative('{}')
        assert fake.calls[0]["max_tokens"] == 800

    def test_generate_week_plan_narrative_no_tools(self):
        synth, fake = _synthesizer_with_fake("Ok.")
        synth.generate_week_plan_narrative('{}')
        assert "tools" not in fake.calls[0]


class TestWeekPlanChat:
    def test_week_plan_chat_threads_history_and_caps_it(self):
        synth, fake = _synthesizer_with_fake("About the race...")
        history = [{"role": "user", "content": f"q{i}"} for i in range(30)]
        history += [{"role": "assistant", "content": "a"},
                    {"role": "user", "content": "final"}]
        reply = synth.week_plan_chat('{}', "Narrative.", history)
        assert reply == "About the race..."
        sent = fake.calls[0]["messages"]
        assert len(sent) <= 20
        assert sent[-1]["content"] == "final"

    def test_week_plan_chat_first_message_is_always_user(self):
        """Capped history must never start with an assistant turn."""
        synth, fake = _synthesizer_with_fake("Reply.")
        history: list[dict] = []
        for i in range(15):
            history.append({"role": "user", "content": f"q{i}"})
            history.append({"role": "assistant", "content": f"a{i}"})
        history.append({"role": "user", "content": "final"})
        assert len(history) == 31

        synth.week_plan_chat('{}', "Narrative.", history)
        sent = fake.calls[0]["messages"]

        assert sent[0]["role"] == "user", (
            f"First sent message must be 'user', got '{sent[0]['role']}'"
        )
        assert len(sent) <= 20
        assert sent[-1]["content"] == "final"

    def test_week_plan_chat_max_tokens_600(self):
        synth, fake = _synthesizer_with_fake("Ok.")
        synth.week_plan_chat('{}', "Narrative.", [{"role": "user", "content": "hi"}])
        assert fake.calls[0]["max_tokens"] == 600

    def test_week_plan_chat_system_contains_plan_and_narrative(self):
        synth, fake = _synthesizer_with_fake("Ok.")
        plan_json = '{"week_start": "2026-07-21"}'
        narrative = "Your race is PCup at Spa."
        synth.week_plan_chat(plan_json, narrative,
                             [{"role": "user", "content": "q"}])
        system = fake.calls[0]["system"]
        assert plan_json in system
        assert narrative in system
