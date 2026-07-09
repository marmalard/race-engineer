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


# --- Fix 2: full-field lap data on small grids ----------------------------------

def _make_stub_meta(player_cust_id: int) -> dict:
    return {
        "subsession_id": 12345,
        "player_cust_id": player_cust_id,
        "player_car_idx": 0,
        "driver_name": "Test Driver",
        "track_id": 1,
        "track_name": "Test",
        "track_config": "",
        "track_directory": "test",
        "track_length_m": 4000.0,
        "car_name": "Car",
        "series_name": "",
        "session_date": "",
        "sof": 1400,
        "roster": [],
    }


def _results_payload(ordered_cust_ids: list[int]) -> dict:
    """Fake results payload with drivers in finish order (1-based after parse)."""
    return {
        "series_name": "",
        "start_time": "",
        "session_results": [
            {
                "simsession_number": 0,
                "simsession_type_name": "Race",
                "results": [
                    {
                        "cust_id": cid,
                        "display_name": f"D{cid}",
                        "finish_position": i,  # 0-based; parse_results adds 1
                        "starting_position": i,
                        "laps_complete": 10,
                        "incidents": 0,
                        "oldi_rating": 1400,
                        "newi_rating": 1400,
                        "best_lap_time": 1000000,
                    }
                    for i, cid in enumerate(ordered_cust_ids)
                ],
            }
        ],
    }


def test_ingest_small_field_fetches_all_drivers(tmp_path, monkeypatch):
    """Field <= FULL_FIELD_MAX: lap data must be requested for every classified driver."""
    from core.race.ingest import FULL_FIELD_MAX, ingest_race

    player_cust_id = 1226848
    field_ids = [player_cust_id] + list(range(1, 11))  # player + 10 others = 11
    assert len(field_ids) <= FULL_FIELD_MAX, "Test precondition: field must be small"

    stub_ibt = SimpleNamespace(telemetry=pd.DataFrame({"Speed": [0.0]}))
    monkeypatch.setattr(
        "core.race.ingest.load_race_ibt",
        lambda _: (stub_ibt, _make_stub_meta(player_cust_id)),
    )

    fetched: list[int] = []

    class TrackingAPI:
        def get_subsession_results(self, _):
            return _results_payload(field_ids)

        def get_lap_chart_data(self, *_):
            return []

        def get_lap_data(self, _sub, _sim, cust_id):
            fetched.append(cust_id)
            return []  # no lap rows needed for this assertion

    ingest_race(b"fake", TrackingAPI(), cache_dir=tmp_path)
    assert set(fetched) == set(field_ids), (
        f"Expected all {len(field_ids)} driver IDs to be fetched, "
        f"got {sorted(set(fetched))}"
    )


def test_ingest_large_field_fetches_bounded_set(tmp_path, monkeypatch):
    """Field > FULL_FIELD_MAX: only player + key rivals get lap data (API-call bound)."""
    from core.race.ingest import FULL_FIELD_MAX, ingest_race

    player_cust_id = 1226848
    n_others = FULL_FIELD_MAX + 4  # 20 others → total 21 > 16
    other_ids = list(range(1, n_others + 1))
    # Player finishes 10th (0-based index 9); adjacent finishers are index 8 and 10
    player_pos_idx = 9
    ordered = other_ids[:player_pos_idx] + [player_cust_id] + other_ids[player_pos_idx:]
    assert len(ordered) > FULL_FIELD_MAX, "Test precondition: field must be large"

    stub_ibt = SimpleNamespace(telemetry=pd.DataFrame({"Speed": [0.0]}))
    monkeypatch.setattr(
        "core.race.ingest.load_race_ibt",
        lambda _: (stub_ibt, _make_stub_meta(player_cust_id)),
    )

    fetched: list[int] = []

    class TrackingAPI:
        def get_subsession_results(self, _):
            return _results_payload(ordered)

        def get_lap_chart_data(self, *_):
            return []

        def get_lap_data(self, _sub, _sim, cust_id):
            fetched.append(cust_id)
            return []

    ingest_race(b"fake", TrackingAPI(), cache_dir=tmp_path)

    fetched_set = set(fetched)
    assert player_cust_id in fetched_set, "Player must always be in the fetched set"
    assert len(fetched_set) <= 5, (  # player + max 4 rivals per select_key_rivals cap
        f"Expected at most 5 drivers fetched on a large field, got {sorted(fetched_set)}"
    )
    assert fetched_set < set(ordered), (
        "Fetched set must be a strict subset of the full field on large grids"
    )


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
