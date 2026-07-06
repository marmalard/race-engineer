"""Tests for race ingestion: parsing, caching, simsession selection.

Integration tests against the real Oulton fixture live at the bottom
and skip when fixtures are absent (recorded by
scripts/record_race_fixture.py — see Task 11).
"""

import json
from pathlib import Path

import pytest

from core.race.ingest import (
    RaceIngestError,
    _cached_fetch,
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
