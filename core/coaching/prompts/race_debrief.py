"""Prompts for race debrief synthesis and conversational follow-up.

The tone contract lives here as hard system-prompt rules. The narrative
JSON is the ONLY source of facts — the model is told so explicitly.
"""

from __future__ import annotations

import json

from core.race.models import RaceNarrative

RACE_DEBRIEF_SYSTEM_PROMPT = """\
You are the driver's personal race engineer, debriefing them after an
iRacing official race. You work FOR the driver. Rules, in priority order:

1. Engineer, not judge. Never scold, never moralize, never flatter
   dishonestly. You are on the driver's side and you tell the truth.
2. Every factual claim (positions, gaps, lap times, incidents, iRating)
   MUST come from the race data JSON you are given, or from the
   driver-profile block when one is provided. Profile facts are
   cross-race tendencies — cite them as such, using the race count the
   profile block itself states (e.g. "across your last N races"), never
   as facts about this race. Never invent or extrapolate facts. If the
   data doesn't contain something, don't claim it.
3. Reframe bad races as intelligence gained. A wrecked race gets the
   most USEFUL debrief, not the most painful one. What did this race
   teach that the next one can use?
4. Be opinionated and prioritized. End with at most 2-3 concrete,
   forward-looking takeaways ("next restart, hold the inside into T1"),
   never generic advice ("be more careful").

Voice: direct, calm, specific — a professional engineer on the radio
after the checkered flag. Write in second person. Keep it under 500
words. Use plain paragraphs and a short takeaway list at the end.
"""


def build_race_debrief_prompt(
    narrative: RaceNarrative, profile_block: str = ""
) -> str:
    """User message for the one-shot debrief generation.

    Args:
        narrative: The deterministic race narrative.
        profile_block: Optional pre-formatted driver-profile block (from
            ``render_profile_block``). Inserted before the race JSON when
            provided so the model can cite cross-race tendencies.
    """
    h = narrative.header
    profile_part = f"{profile_block}\n\n" if profile_block else ""
    return (
        f"Debrief this race for {h.driver_name} "
        f"({h.car_name}, {h.series_name}).\n\n"
        + profile_part
        + "--- RACE DATA (JSON) ---\n"
        f"{json.dumps(narrative.to_dict(), indent=2)}\n"
        "--- END RACE DATA ---\n\n"
        "Write the debrief."
    )


def build_race_chat_system(
    narrative: RaceNarrative, debrief_text: str, profile_block: str = ""
) -> str:
    """System prompt for follow-up chat, grounded in the same data.

    Args:
        narrative: The deterministic race narrative.
        debrief_text: The already-delivered debrief text.
        profile_block: Optional pre-formatted driver-profile block. When
            provided it is appended after the tone contract so the model
            can answer cross-race questions from profile data.
    """
    profile_part = (
        "\n\nThe driver's cross-race profile:\n" + profile_block
        if profile_block else ""
    )
    return (
        RACE_DEBRIEF_SYSTEM_PROMPT
        + profile_part
        + "\n\nYou already delivered this debrief:\n---\n"
        + debrief_text
        + "\n---\n\nThe complete race data JSON:\n"
        + json.dumps(narrative.to_dict())
        + "\n\nAnswer the driver's follow-up questions from this data "
        "only. If a question cannot be answered from it, say plainly "
        "that you don't have that data from this session — never guess. "
        "Keep answers short and conversational; this is radio chatter, "
        "not a report."
    )
