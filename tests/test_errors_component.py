"""Error taxonomy (A5) -- consumer sentences for known failure classes.

Exact-string tests (nudges precedent): the copy IS the product.
"""

import struct
from pathlib import Path

from app.components.errors import (
    API_DOWN,
    GENERIC,
    NO_AI_KEY,
    NOT_A_RACE,
    NOT_TELEMETRY,
    explain,
)
from core.race.ingest import RaceIngestError


class TestConstants:
    def test_not_telemetry_exact(self):
        assert NOT_TELEMETRY == (
            "This file doesn't look like an iRacing telemetry (.ibt) "
            "file. Telemetry lands in Documents\\iRacing\\telemetry "
            "after a session with recording on (Alt+L in the car)."
        )

    def test_not_a_race_exact(self):
        assert NOT_A_RACE == (
            "This is a practice or qualifying session — the Debrief "
            "page wants an official race. The Lap Coaching page handles "
            "practice telemetry."
        )

    def test_no_ai_key_exact(self):
        assert NO_AI_KEY == (
            "The AI debrief isn't configured on this host — the race "
            "story above is complete without it."
        )

    def test_api_down_exact(self):
        assert API_DOWN == (
            "iRacing's data service didn't answer for this race — "
            "showing what your telemetry alone supports. Re-open this "
            "race later to fill in official results."
        )

    def test_generic_exact(self):
        assert GENERIC == (
            "Something went wrong analyzing this file. The technical "
            "details are below if the host wants to dig in."
        )


class TestExplain:
    def test_non_race_ingest_error_maps_to_not_a_race(self):
        # Message shape from core/race/ingest.py::load_race_ibt
        exc = RaceIngestError(
            "This IBT is not an official race session "
            "(EventType='Practice', SubSessionID=0)."
        )
        assert explain(exc) == NOT_A_RACE

    def test_other_ingest_errors_pass_through(self):
        exc = RaceIngestError("No race simsession in results payload")
        assert explain(exc) == "No race simsession in results payload"

    def test_parse_failures_map_to_not_telemetry(self):
        for exc in [
            ValueError("File too small for header: 12 bytes"),
            TypeError("Expected Path or bytes, got int"),
            struct.error("unpack_from requires a buffer"),
            EOFError(),
        ]:
            assert explain(exc) == NOT_TELEMETRY, type(exc).__name__

    def test_unknown_exceptions_map_to_generic(self):
        assert explain(RuntimeError("boom")) == GENERIC

    def test_coupling_substring_still_in_ingest_source(self):
        # explain() keys NOT_A_RACE off prose raised in load_race_ibt.
        # If ingest rewords that message, this pin fails loudly instead
        # of the dispatch silently falling through to str(exc).
        src = Path("core/race/ingest.py").read_text(encoding="utf-8")
        assert "not an official race" in src
