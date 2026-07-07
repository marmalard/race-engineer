"""Tests for race ingestion: parsing, caching, simsession selection.

Integration tests against the real Oulton fixture live at the bottom
and skip when fixtures are absent (recorded by
scripts/record_race_fixture.py — see Task 11).
"""

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from core.race.ingest import (
    RaceIngestError,
    _cached_fetch,
    ingest_race,
    parse_lap_chart_rows,
    parse_lap_data_rows,
    parse_results,
    select_race_simsession,
)


# --- select_race_simsession -------------------------------------------------

def test_select_race_simsession_prefers_number_zero():
    sessions = [
        {"simsession_number": -2, "simsession_type_name": "Open Practice"},
        {"simsession_number": -1, "simsession_type_name": "Lone Qualifying"},
        {"simsession_number": 0, "simsession_type_name": "Race"},
    ]
    assert select_race_simsession(sessions)["simsession_number"] == 0


def test_select_race_simsession_falls_back_to_name():
    sessions = [
        {"simsession_number": -1, "simsession_type_name": "Lone Qualifying"},
        {"simsession_number": 1, "simsession_type_name": "Feature Race"},
    ]
    assert select_race_simsession(sessions)["simsession_number"] == 1


def test_select_race_simsession_raises_without_race():
    with pytest.raises(RaceIngestError):
        select_race_simsession(
            [{"simsession_number": -2, "simsession_type_name": "Open Practice"}]
        )


# --- parse_results ------------------------------------------------------------

def test_parse_results_extracts_rows_and_lap_times():
    raw = {
        "session_results": [
            {
                "simsession_number": 0,
                "simsession_type_name": "Race",
                "results": [
                    {
                        "cust_id": 1226848,
                        "display_name": "Anthony Moorman",
                        "finish_position": 6,     # zero-based in the API
                        "starting_position": 7,
                        "laps_complete": 14,
                        "incidents": 5,
                        "oldi_rating": 1420,
                        "newi_rating": 1445,
                        "best_lap_time": 1129000,  # 1/10000s
                    }
                ],
            }
        ]
    }
    rows = parse_results(raw)
    assert len(rows) == 1
    r = rows[0]
    assert r.cust_id == 1226848
    assert r.finish_position == 7      # converted to 1-based
    assert r.starting_position == 8    # converted to 1-based
    assert r.best_lap_time == pytest.approx(112.9)


def test_parse_results_handles_invalid_best_lap():
    raw = {
        "session_results": [
            {
                "simsession_number": 0,
                "simsession_type_name": "Race",
                "results": [
                    {
                        "cust_id": 1,
                        "display_name": "X",
                        "finish_position": 0,
                        "starting_position": 0,
                        "laps_complete": 2,
                        "incidents": 0,
                        "oldi_rating": 1000,
                        "newi_rating": 990,
                        "best_lap_time": -1,
                    }
                ],
            }
        ]
    }
    assert parse_results(raw)[0].best_lap_time == -1.0


# --- parse_lap_chart_rows / parse_lap_data_rows --------------------------------

def test_parse_lap_chart_rows():
    raw = [
        {"cust_id": 1, "lap_number": 0, "lap_position": 3},  # lap 0 dropped
        {"cust_id": 1, "lap_number": 1, "lap_position": 4},
        {"group_id": 2, "lap_number": 1, "lap_position": 5},  # cust via group
    ]
    rows = parse_lap_chart_rows(raw)
    assert [(r.cust_id, r.lap_number, r.position) for r in rows] == [
        (1, 1, 4),
        (2, 1, 5),
    ]


def test_parse_lap_data_rows():
    raw = [
        {
            "cust_id": 1,
            "lap_number": 1,
            "lap_time": 1130000,
            "lap_events": ["off track"],
            "incident": True,
        },
        {"cust_id": 1, "lap_number": 2, "lap_time": -1, "lap_events": []},
    ]
    laps = parse_lap_data_rows(raw, cust_id=1)
    assert laps[0].lap_time == pytest.approx(113.0)
    assert laps[0].incident is True
    assert laps[0].lap_events == ["off track"]
    assert laps[1].lap_time == -1.0


# --- _cached_fetch ---------------------------------------------------------------

def test_cached_fetch_writes_then_reads_cache(tmp_path):
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return {"value": 42}

    path = tmp_path / "sub" / "results.json"
    assert _cached_fetch(path, fetch) == {"value": 42}
    assert _cached_fetch(path, fetch) == {"value": 42}
    assert calls["n"] == 1  # second call served from disk
    assert json.loads(path.read_text())["value"] == 42


def test_cached_fetch_recovers_from_corrupt_cache(tmp_path):
    """A corrupt cache file must be treated as a miss: re-fetch and repair."""
    path = tmp_path / "results.json"
    path.write_text("not valid json{{{{", encoding="utf-8")

    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return {"repaired": True}

    result = _cached_fetch(path, fetch)
    assert result == {"repaired": True}
    assert calls["n"] == 1  # fetch was called despite the existing file
    assert json.loads(path.read_text(encoding="utf-8"))["repaired"] is True


# --- ingest_race degradation path -----------------------------------------------

def test_ingest_race_api_failure_degrades_gracefully(tmp_path, monkeypatch, caplog):
    """An API error should produce a partial RaceData (empty results/chart/laps)
    and log a WARNING — the page can still render from telemetry alone."""
    stub_telemetry = pd.DataFrame({"Speed": [0.0]})
    stub_ibt = SimpleNamespace(telemetry=stub_telemetry)
    stub_meta = {
        "subsession_id": 12345,
        "player_cust_id": 1226848,
        "player_car_idx": 0,
        "driver_name": "Anthony Moorman",
        "track_id": 525,
        "track_name": "Circuit de Spa-Francorchamps",
        "track_config": "Endurance",
        "track_directory": "spa 2024 combined",
        "track_length_m": 7004.0,
        "car_name": "BMW M2 Racing (G87)",
        "series_name": "",
        "session_date": "",
        "sof": 1500,
        "roster": [],
    }

    monkeypatch.setattr(
        "core.race.ingest.load_race_ibt",
        lambda _source: (stub_ibt, stub_meta),
    )

    class FailingAPI:
        def get_subsession_results(self, *args, **kwargs):
            raise RuntimeError("simulated network error")

    with caplog.at_level(logging.WARNING, logger="core.race.ingest"):
        race_data = ingest_race(
            source=b"fake_bytes",
            api=FailingAPI(),
            cache_dir=tmp_path,
        )

    assert race_data.results == []
    assert race_data.lap_chart == []
    assert race_data.driver_laps == {}
    assert any("Data API fetch failed" in r.message for r in caplog.records)


# --- Integration: real Oulton fixtures (skip when absent) -------------------

FIXTURE_DIR = Path("tests/fixtures/race")
FIXTURE_IBT = FIXTURE_DIR / "race.ibt"
FIXTURE_CACHE = FIXTURE_DIR / "cache"

needs_fixture = pytest.mark.skipif(
    not FIXTURE_IBT.exists() or not FIXTURE_CACHE.exists(),
    reason="race fixtures not recorded (scripts/record_race_fixture.py)",
)


@needs_fixture
def test_ingest_real_race_from_cache_no_network():
    """Full ingestion served entirely from recorded cache (api=None ok
    for telemetry, but cache satisfies the API layer via a stub that
    must never be called)."""
    from core.race.ingest import ingest_race

    class _ExplodingAPI:
        def __getattr__(self, name):
            raise AssertionError(f"network call attempted: {name}")

        def close(self):
            pass

    # Cache dir contains {subsession_id}/... — ingest resolves inside it
    data = ingest_race(
        FIXTURE_IBT, _ExplodingAPI(), cache_dir=FIXTURE_CACHE
    )
    assert data.results, "results should come from the recorded cache"
    assert data.player_cust_id > 0
    assert data.driver_laps.get(data.player_cust_id)


@needs_fixture
def test_real_narrative_is_coherent():
    from core.race.ingest import ingest_race
    from core.race.narrative import build_narrative

    class _NeverCalled:
        def __getattr__(self, name):
            raise AssertionError("network call attempted")

        def close(self):
            pass

    data = ingest_race(FIXTURE_IBT, _NeverCalled(), cache_dir=FIXTURE_CACHE)
    narrative = build_narrative(data, corners=[])
    h = narrative.header
    assert 1 <= h.finish_position <= h.field_size
    assert narrative.position_timeline
    assert narrative.pace is not None
    assert narrative.attribution is not None
    # Round-trip through persistence layer format
    from core.race.models import RaceNarrative

    assert RaceNarrative.from_dict(narrative.to_dict()) == narrative
