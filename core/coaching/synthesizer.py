"""AI synthesis layer using Claude API.

Handles scouting report generation (with web search) and coaching
narrative synthesis (from structured analysis data).
"""

from dataclasses import dataclass, field

import anthropic

from core.coaching.prompts.scouting import SCOUTING_SYSTEM_PROMPT, build_scouting_prompt


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
    ) -> ScoutingReport:
        """Generate a scouting report using Claude with web search.

        Uses the web_search tool to find current community knowledge
        about the car/track combination.
        """
        user_message = build_scouting_prompt(
            car_name=car_name,
            track_name=track_name,
            track_config=track_config,
            irating=irating,
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
