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
   MUST come from the race data JSON you are given. Never invent or
   extrapolate facts. If the data doesn't contain something, don't
   claim it.
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


def build_race_debrief_prompt(narrative: RaceNarrative) -> str:
    """User message for the one-shot debrief generation."""
    h = narrative.header
    return (
        f"Debrief this race for {h.driver_name} "
        f"({h.car_name}, {h.series_name}).\n\n"
        "--- RACE DATA (JSON) ---\n"
        f"{json.dumps(narrative.to_dict(), indent=2)}\n"
        "--- END RACE DATA ---\n\n"
        "Write the debrief."
    )


def build_race_chat_system(
    narrative: RaceNarrative, debrief_text: str
) -> str:
    """System prompt for follow-up chat, grounded in the same data."""
    return (
        RACE_DEBRIEF_SYSTEM_PROMPT
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
