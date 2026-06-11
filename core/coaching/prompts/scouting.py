"""Prompt templates for scouting report generation."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.coaching.scouting import PaceContext

SCOUTING_SYSTEM_PROMPT = """\
You are an experienced iRacing coach preparing a pre-session briefing for a \
sim racer. You give concise, opinionated, actionable advice. You prioritize \
the 2-3 things that matter most, not everything that's measurable.

Your tone is that of a knowledgeable friend who races — confident but not \
condescending. You speak in concrete, specific terms: "brake at the 3 marker" \
not "brake earlier". You understand iRacing-specific behavior: tire model, \
track surfaces, car handling characteristics.

Format your response in markdown with clear section headers."""

SCOUTING_USER_TEMPLATE = """\
Prepare a scouting report for the following car/track combination:

Car: {car_name}
Track: {track_name}{track_config_line}
Driver iRating: {irating}

Generate a pre-session briefing with these sections:

1. **Track Overview** — Overall character (momentum vs point-and-shoot), \
what it rewards, what it punishes. Surface notes, elevation changes, \
tire wear behavior for this car.

2. **Key Corners (3-5 most important)** — For each: corner name/number, \
what makes it tricky, the common mistake, one concrete thing to focus on.

3. **Car-Specific Notes** — How this car behaves at this track. \
Known handling tendencies. Setup considerations if relevant.

4. **Pace Context** — What constitutes a competitive lap time at this \
car/track combo for drivers around {irating} iRating. What separates \
a good lap from a great lap.

Search the web for current community knowledge, track guides, and \
recent discussions about this combination. Prioritize recent sources \
(2024-2026).

Keep the total report under 800 words. This is a quick-glance briefing, \
not an essay."""


def build_scouting_prompt(
    car_name: str,
    track_name: str,
    track_config: str | None = None,
    irating: int | None = None,
    pace_context: "PaceContext | None" = None,
) -> str:
    """Build the user message for a scouting report request.

    When pace_context is provided with matching races, appends the driver's
    own race history as structured data for the Pace Context section.
    """
    track_config_line = f" ({track_config})" if track_config else ""
    irating_str = str(irating) if irating else "unknown"

    prompt = SCOUTING_USER_TEMPLATE.format(
        car_name=car_name,
        track_name=track_name,
        track_config_line=track_config_line,
        irating=irating_str,
    )

    if pace_context and pace_context.race_count > 0:
        prompt += _format_pace_context(pace_context)

    return prompt


def _format_pace_context(pace_context: "PaceContext") -> str:
    """Format pace context data for injection into the scouting prompt."""
    import json

    lines = [
        "\n\n--- DRIVER'S OWN RACE HISTORY ---",
        f"The driver has {pace_context.race_count} recent race(s) at this track.",
    ]

    if pace_context.driver_best_lap:
        mins = int(pace_context.driver_best_lap // 60)
        secs = pace_context.driver_best_lap % 60
        lines.append(f"Personal best race lap: {mins}:{secs:06.3f}")

    if pace_context.driver_best_qual:
        mins = int(pace_context.driver_best_qual // 60)
        secs = pace_context.driver_best_qual % 60
        lines.append(f"Personal best qualifying lap: {mins}:{secs:06.3f}")

    if pace_context.avg_sof:
        lines.append(f"Average strength of field: {pace_context.avg_sof:.0f}")

    lines.append("\nRecent results:")
    lines.append(json.dumps(pace_context.matching_races, indent=2))
    lines.append(
        "\nUse this data to ground the Pace Context section. "
        "Compare the driver's actual pace to what's competitive at their "
        "iRating level. Be specific about where they stand and what lap "
        "time targets to aim for."
    )

    return "\n".join(lines)
