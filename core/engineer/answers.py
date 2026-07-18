"""PTT answer orchestration: fast path -> Claude -> offline line.

The fast path (intents) is deterministic and instant. Open questions go
to a Haiku-class call grounded in the race-state JSON with a hard
timeout; ANY failure -- no key, timeout, network -- degrades to the
offline line. The coach must keep answering gaps with the wifi down.
"""

import json
import logging
import os

from core.coaching.prompts.engineer import ENGINEER_SYSTEM_PROMPT
from core.engineer.intents import match_intent

logger = logging.getLogger(__name__)

OFFLINE_LINE = "Can't reach the pit wall — stand by."
ENGINEER_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_TIMEOUT_S = 4.0
MAX_TOKENS = 150


def answer_question(transcript: str, snapshot: dict,
                    ask=None) -> tuple[str, str]:
    """-> (spoken text, source) where source in {fast, claude, offline}."""
    if not (transcript or "").strip():
        return "Say again?", "fast"
    fast = match_intent(transcript, snapshot)
    if fast is not None:
        return fast, "fast"
    if ask is None:
        return OFFLINE_LINE, "offline"
    try:
        return ask(transcript, json.dumps(snapshot)), "claude"
    except Exception:
        logger.warning("Claude PTT path failed; offline line", exc_info=True)
        return OFFLINE_LINE, "offline"


def make_claude_ask():
    """Build the ask callable, or None when no API key is configured.
    Deferred anthropic import so the suite never touches it."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    import anthropic
    # max_retries=0: SDK retries would stretch the worst case to ~3x the
    # timeout. On the radio a 12s-late answer is worse than the offline
    # line -- the driver can just press again.
    client = anthropic.Anthropic(api_key=key, timeout=CLAUDE_TIMEOUT_S,
                                 max_retries=0)

    def ask(transcript: str, state_json: str) -> str:
        response = client.messages.create(
            model=ENGINEER_MODEL,
            max_tokens=MAX_TOKENS,
            system=ENGINEER_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": (f"RACE STATE:\n{state_json}\n\n"
                            f"DRIVER ASKS: {transcript}"),
            }],
        )
        return "".join(
            block.text for block in response.content
            if getattr(block, "type", "") == "text"
        ).strip() or OFFLINE_LINE

    return ask
