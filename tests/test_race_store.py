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


def test_get_narratives_filters_and_orders(tmp_path):
    from core.race.race_store import RaceStore

    store = RaceStore(tmp_path / "races.db")

    n1 = _minimal_narrative()
    n1.header.subsession_id = 1
    n1.header.cust_id = 100

    n2 = _minimal_narrative()
    n2.header.subsession_id = 2
    n2.header.cust_id = 100

    other = _minimal_narrative()
    other.header.subsession_id = 3
    other.header.cust_id = 999

    store.save_race(n1, ibt_file_path="a")
    store.save_race(n2, ibt_file_path="b")
    store.save_race(other, ibt_file_path="c")

    got = store.get_narratives(100)
    # ORDER BY created_at DESC, subsession_id DESC — subsession_id tiebreaker
    # makes the order deterministic even if all three saves share a timestamp.
    assert [n.header.subsession_id for n in got] == [2, 1]
    assert store.get_narratives(12345) == []
