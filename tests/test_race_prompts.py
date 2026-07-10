"""Prompt-builder tests: profile injection + tone-contract amendment."""

from core.coaching.prompts.race_debrief import (
    RACE_DEBRIEF_SYSTEM_PROMPT,
    build_race_chat_system,
    build_race_debrief_prompt,
)
from tests.test_profile_racecraft import _narr


def test_debrief_prompt_without_block_unchanged():
    p = build_race_debrief_prompt(_narr())
    assert "DRIVER PROFILE" not in p
    assert "--- RACE DATA (JSON) ---" in p


def test_debrief_prompt_with_block_inserts_before_race_data():
    block = "--- DRIVER PROFILE ---\n{}\n--- END DRIVER PROFILE ---"
    p = build_race_debrief_prompt(_narr(), profile_block=block)
    assert block in p
    assert p.index(block) < p.index("--- RACE DATA (JSON) ---")


def test_chat_system_with_block():
    p = build_race_chat_system(_narr(), "debrief text",
                               profile_block="--- DRIVER PROFILE X ---")
    assert "--- DRIVER PROFILE X ---" in p


def test_chat_system_without_block_unchanged():
    p = build_race_chat_system(_narr(), "debrief text")
    assert "DRIVER PROFILE" not in p


def test_tone_contract_permits_profile_as_cited_source():
    assert "driver-profile block" in RACE_DEBRIEF_SYSTEM_PROMPT
    assert "cross-race" in RACE_DEBRIEF_SYSTEM_PROMPT
