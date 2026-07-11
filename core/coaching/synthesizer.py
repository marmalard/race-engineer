"""AI synthesis layer using Claude API.

Handles scouting report generation (with web search) and coaching
narrative synthesis (from structured analysis data).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import anthropic

if TYPE_CHECKING:
    from core.coaching.analyzer import CoachingAnalysis
    from core.coaching.scouting import PaceContext
    from core.race.models import RaceNarrative

from core.coaching.prompts.scouting import SCOUTING_SYSTEM_PROMPT, build_scouting_prompt
from core.coaching.prompts.coaching import COACHING_SYSTEM_PROMPT, build_coaching_prompt
from core.coaching.prompts.race_debrief import (
    RACE_DEBRIEF_SYSTEM_PROMPT,
    build_race_chat_system,
    build_race_debrief_prompt,
)


@dataclass
class Citation:
    """A citation from a web search result."""

    url: str
    title: str
    cited_text: str


@dataclass
class ScoutingReport:
    """Generated scouting report with metadata."""

    car: str
    track: str
    track_config: str | None
    report_text: str
    citations: list[Citation] = field(default_factory=list)
    model_used: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class CoachingReport:
    """Generated coaching report with metadata."""

    track: str
    car: str
    report_text: str
    model_used: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class RaceDebriefReport:
    """Generated race debrief with metadata."""

    subsession_id: int
    track: str
    car: str
    report_text: str
    model_used: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


class Synthesizer:
    """AI synthesis layer using Claude API."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-5-20250929",
    ):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def generate_scouting_report(
        self,
        car_name: str,
        track_name: str,
        track_config: str | None = None,
        irating: int | None = None,
        pace_context: PaceContext | None = None,
    ) -> ScoutingReport:
        """Generate a scouting report using Claude with web search.

        Uses the web_search tool to find current community knowledge
        about the car/track combination. When pace_context is provided,
        injects the driver's own race history into the prompt.
        """
        user_message = build_scouting_prompt(
            car_name=car_name,
            track_name=track_name,
            track_config=track_config,
            irating=irating,
            pace_context=pace_context,
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=SCOUTING_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            tools=[
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": 5,
                }
            ],
        )

        report_text = self._extract_text(response)
        citations = self._extract_citations(response)

        return ScoutingReport(
            car=car_name,
            track=track_name,
            track_config=track_config,
            report_text=report_text,
            citations=citations,
            model_used=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    def generate_coaching_narrative(
        self,
        analysis: "CoachingAnalysis",
    ) -> "CoachingReport":
        """Generate a coaching narrative from structured analysis data.

        Unlike scouting reports, this does NOT use web search — the coaching
        is based entirely on the deterministic telemetry analysis.
        """
        user_message = build_coaching_prompt(analysis)

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=COACHING_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        report_text = self._extract_text(response)

        return CoachingReport(
            track=analysis.track_name,
            car=analysis.car_name,
            report_text=report_text,
            model_used=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    MAX_CHAT_HISTORY = 20

    def generate_race_debrief(
        self, narrative: "RaceNarrative", profile_block: str = ""
    ) -> RaceDebriefReport:
        """Generate the race debrief from the deterministic narrative.

        No web search — every fact comes from the narrative JSON and the
        optional driver-profile block.

        Args:
            narrative: The deterministic race narrative.
            profile_block: Optional pre-formatted driver-profile block
                (from ``profile_prompt_block``). When provided, cross-race
                tendencies may be cited in the debrief.
        """
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1500,
            system=RACE_DEBRIEF_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": build_race_debrief_prompt(narrative, profile_block),
                }
            ],
        )
        return RaceDebriefReport(
            subsession_id=narrative.header.subsession_id,
            track=narrative.header.track_name,
            car=narrative.header.car_name,
            report_text=self._extract_text(response),
            model_used=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    def race_chat_reply(
        self,
        narrative: "RaceNarrative",
        debrief_text: str,
        history: list[dict],
        profile_block: str = "",
    ) -> str:
        """One follow-up chat turn, grounded in the narrative + debrief.

        history: [{"role": "user"|"assistant", "content": str}, ...],
        newest last. Only the last MAX_CHAT_HISTORY turns are sent.

        Guard: if the capped slice starts with an assistant turn (which the
        Anthropic Messages API rejects), the leading assistant message is
        dropped so the first sent message always has role 'user'.

        Args:
            narrative: The deterministic race narrative.
            debrief_text: The already-delivered debrief text.
            history: Conversation history, newest last.
            profile_block: Optional pre-formatted driver-profile block.
                When provided, the model can cite cross-race tendencies
                in its follow-up answers.
        """
        msgs = history[-self.MAX_CHAT_HISTORY:]
        if msgs and msgs[0]["role"] != "user":
            msgs = msgs[1:]
        response = self.client.messages.create(
            model=self.model,
            max_tokens=800,
            system=build_race_chat_system(narrative, debrief_text, profile_block),
            messages=msgs,
        )
        return self._extract_text(response)

    def _extract_text(self, response: anthropic.types.Message) -> str:
        """Extract the text content from a Claude response, skipping tool use blocks."""
        text_parts: list[str] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
        return "\n\n".join(text_parts)

    def _extract_citations(self, response: anthropic.types.Message) -> list[Citation]:
        """Extract citations from web search results in the response."""
        citations: list[Citation] = []
        seen_urls: set[str] = set()

        for block in response.content:
            if block.type != "text":
                continue
            if not hasattr(block, "citations") or not block.citations:
                continue
            for cite in block.citations:
                if cite.type != "web_search_result_location":
                    continue
                if cite.url in seen_urls:
                    continue
                seen_urls.add(cite.url)
                citations.append(
                    Citation(
                        url=cite.url,
                        title=cite.title,
                        cited_text=cite.cited_text if hasattr(cite, "cited_text") else "",
                    )
                )

        return citations
