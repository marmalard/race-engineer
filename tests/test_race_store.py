"""Tests for the race debrief SQLite store."""

import pytest

from core.race.race_store import RaceStore, StoredRaceMeta
from tests.test_race_models import _minimal_narrative


@pytest.fixture
def store(tmp_path):
    return RaceStore(tmp_path / "races.db")


def test_save_and_load_race_round_trip(store):
    narrative = _minimal_narrative()
    store.save_race(narrative, ibt_file_path="C:/tmp/race.ibt")
    loaded = store.get_race(86748877, 1226848)
    assert loaded is not None
    assert loaded == narrative


def test_get_race_missing_returns_none(store):
    assert store.get_race(1, 2) is None


def test_same_subsession_two_drivers_coexist(store):
    a = _minimal_narrative()
    b = _minimal_narrative()
    b.header.cust_id = 555
    b.header.driver_name = "Friend Tester"
    store.save_race(a, ibt_file_path="")
    store.save_race(b, ibt_file_path="")
    assert store.get_race(86748877, 1226848).header.driver_name == "Anthony Moorman"
    assert store.get_race(86748877, 555).header.driver_name == "Friend Tester"


def test_resave_upserts_and_preserves_chat(store):
    narrative = _minimal_narrative()
    store.save_race(narrative, ibt_file_path="")
    store.append_chat_message(86748877, 1226848, "user", "why P6?")
    store.save_race(narrative, ibt_file_path="")  # re-ingest
    chat = store.get_chat(86748877, 1226848)
    assert len(chat) == 1
    assert chat[0]["content"] == "why P6?"


def test_debrief_save_and_get(store):
    narrative = _minimal_narrative()
    store.save_race(narrative, ibt_file_path="")
    store.save_debrief(86748877, 1226848, "Good race.", model="claude-sonnet-4-5")
    assert store.get_debrief(86748877, 1226848) == "Good race."
    store.save_debrief(86748877, 1226848, "Updated.", model="claude-sonnet-4-5")
    assert store.get_debrief(86748877, 1226848) == "Updated."


def test_list_races_returns_meta_newest_first(store):
    a = _minimal_narrative()
    store.save_race(a, ibt_file_path="")
    races = store.list_races()
    assert len(races) == 1
    meta = races[0]
    assert isinstance(meta, StoredRaceMeta)
    assert meta.subsession_id == 86748877
    assert meta.driver_name == "Anthony Moorman"
    assert meta.finish_position == 6
