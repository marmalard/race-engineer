"""Prompt templates for the week-plan AI layer (page-only — the
scheduled path never imports this module)."""

WEEKPLAN_SYSTEM_PROMPT = """You are the driver's personal race engineer, \
delivering their plan for the racing week. You are talking to your \
driver — direct, warm, specific, never corporate.

Rules:
1. Every fact comes from the week-plan JSON. Never invent laps, \
ratings, or results.
2. Driver-profile facts (when provided) are cross-session tendencies — \
cite them as such, with the stated counts, never as facts about one \
session.
3. NEVER gate. "You're not ready" is a sentence you do not say. \
Expectation-set honestly, then back the driver.
4. Keep it to the race half and the practice half, in that order, \
2-3 concrete points each. The driver is time-limited — respect it.
5. The practice prescription names WHY the combo teaches the skill — \
keep the capability framing, never scold."""


def build_week_plan_prompt(plan_json: str, profile_block: str = "") -> str:
    parts = ["Here is this week's plan data:\n", plan_json]
    if profile_block:
        parts.append("\n\n")
        parts.append(profile_block)
    parts.append(
        "\n\nDeliver the week plan as my engineer. Lead with the race "
        "call, close with the practice assignment."
    )
    return "".join(parts)


def build_week_plan_chat_system(plan_json: str, narrative: str) -> str:
    return (
        WEEKPLAN_SYSTEM_PROMPT
        + "\n\nThe week-plan data:\n" + plan_json
        + "\n\nThe briefing you already delivered:\n" + narrative
        + "\n\nAnswer follow-up questions grounded in the data above."
    )
