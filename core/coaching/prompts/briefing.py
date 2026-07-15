"""Prompt templates for the AI race-briefing narrative + chat."""

BRIEFING_SYSTEM_PROMPT = """\
You are a personal race engineer delivering a pre-race briefing to your \
driver. You are opinionated, specific, and on their side. Rules:
1. Ground every claim in the briefing JSON. Never invent pace numbers, \
SoF figures, or field facts.
2. NEVER tell the driver not to race, and never imply they are not \
ready. Under-curve pace is framed as expectation-setting plus a clear \
practice target - racing is always worth it.
3. Confidence comes from evidence: cite their preparation (sessions, \
laps, trend) back to them.
4. Include a short decision matrix - two or three pre-made in-race \
decisions (start goes badly, early contact ahead, fading pace late).
5. Keep it under 300 words. Radio discipline: an engineer who mostly \
shuts up is a feature.
6. Driver-profile facts (when provided) are cross-race tendencies - \
cite them as such, never as facts about this race."""


def build_briefing_prompt(briefing_json: str, profile_block: str = "") -> str:
    """User message for the one-shot briefing generation.

    Args:
        briefing_json: The JSON-serialised BriefingData dict.
        profile_block: Optional pre-formatted driver-profile block (from
            ``profile_prompt_block``). Inserted before the close tag when
            provided so the model can cite cross-race tendencies.
    """
    parts = [
        "Deliver the pre-race briefing for this data:",
        "",
        "--- BRIEFING DATA (JSON) ---",
        briefing_json,
    ]
    if profile_block:
        parts += ["", "--- DRIVER PROFILE (cross-race tendencies) ---",
                  profile_block]
    return "\n".join(parts)


def build_briefing_chat_system(briefing_json: str, narrative: str) -> str:
    """System prompt for follow-up chat, grounded in the briefing data.

    Args:
        briefing_json: The JSON-serialised BriefingData dict.
        narrative: The already-delivered AI briefing narrative text.
    """
    return (
        BRIEFING_SYSTEM_PROMPT
        + "\n\nYou already delivered this briefing:\n\n"
        + narrative
        + "\n\nThe underlying data:\n\n"
        + briefing_json
        + "\n\nAnswer follow-up questions grounded in that data only."
    )
