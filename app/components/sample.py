"""Sample debrief assets (A3) -- see the product before uploading.

The narrative is synthetic (fictional drivers, hand-authored times,
sentinel subsession/cust ids of 0) and frozen in app/assets/; a
round-trip test pins RaceNarrative.from_dict against it so model
evolution can't silently break the sample button.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.race.models import RaceNarrative

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
SAMPLE_NARRATIVE_PATH = _ASSETS / "sample_narrative.json"
SAMPLE_DEBRIEF_PATH = _ASSETS / "sample_debrief.md"


def load_sample_narrative() -> RaceNarrative:
    """The frozen synthetic race, as a full RaceNarrative."""
    data = json.loads(SAMPLE_NARRATIVE_PATH.read_text(encoding="utf-8"))
    return RaceNarrative.from_dict(data)


def load_sample_debrief_text() -> str:
    """The canned example AI debrief (static markdown, no API call)."""
    return SAMPLE_DEBRIEF_PATH.read_text(encoding="utf-8")
