"""Prompt builders are pure - test content assembly, not the API."""

from core.coaching.prompts.briefing import (
    BRIEFING_SYSTEM_PROMPT,
    build_briefing_chat_system,
    build_briefing_prompt,
)


def test_system_prompt_carries_tone_contract():
    assert "never" in BRIEFING_SYSTEM_PROMPT.lower()
    assert "not to race" in BRIEFING_SYSTEM_PROMPT.lower()


def test_build_briefing_prompt_embeds_json_and_profile():
    prompt = build_briefing_prompt('{"series_name": "M2 Cup"}', "PROFILE_BLOCK")
    assert '{"series_name": "M2 Cup"}' in prompt
    assert "PROFILE_BLOCK" in prompt


def test_build_briefing_prompt_without_profile():
    prompt = build_briefing_prompt('{"a": 1}', "")
    assert "PROFILE" not in prompt


def test_chat_system_grounds_in_briefing_and_narrative():
    sys = build_briefing_chat_system('{"a": 1}', "The narrative text")
    assert '{"a": 1}' in sys
    assert "The narrative text" in sys
