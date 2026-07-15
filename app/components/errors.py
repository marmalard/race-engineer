"""Consumer-facing failure sentences (A5 error taxonomy).

One place turns known failure classes into a plain sentence a guest can
act on; unknown failures get GENERIC and the page shows the traceback in
a collapsed host expander. Message constants are exact-string tested
(nudges precedent) -- edit copy here, not in pages.

Note: upload-too-large is enforced client-side by Streamlit itself
(.streamlit/config.toml maxUploadSize 400) -- it never reaches Python,
so it has no constant here.
"""

from __future__ import annotations

import struct

from core.race.ingest import RaceIngestError

NOT_TELEMETRY = (
    "This file doesn't look like an iRacing telemetry (.ibt) file. "
    "Telemetry lands in Documents\\iRacing\\telemetry after a session "
    "with recording on (Alt+L in the car)."
)
NOT_A_RACE = (
    "This is a practice or qualifying session — the Debrief page wants "
    "an official race. The Lap Coaching page handles practice telemetry."
)
NO_AI_KEY = (
    "The AI debrief isn't configured on this host — the race story "
    "above is complete without it."
)
API_DOWN = (
    "iRacing's data service didn't answer for this race — showing what "
    "your telemetry alone supports. Re-open this race later to fill in "
    "official results."
)
GENERIC = (
    "Something went wrong analyzing this file. The technical details "
    "are below if the host wants to dig in."
)

# Failure classes the IBT parse layer raises on corrupt/wrong files
# (core/telemetry/ibt_parser.py raises ValueError/TypeError; struct and
# EOF errors surface from truncated binaries).
_PARSE_ERRORS = (ValueError, TypeError, struct.error, EOFError)


def explain(exc: Exception) -> str:
    """Map a failure to its consumer sentence; GENERIC when unknown."""
    if isinstance(exc, RaceIngestError):
        if "not an official race" in str(exc):
            return NOT_A_RACE
        return str(exc)  # ingest messages are already user-facing
    if isinstance(exc, _PARSE_ERRORS):
        return NOT_TELEMETRY
    return GENERIC
