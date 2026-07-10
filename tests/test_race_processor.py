"""Tests for the watcher's race-capture processor."""

from core.watcher.race_processor import (
    RaceReport,
    classify_ibt,
    decide_capture,
)


def test_classify_race():
    assert classify_ibt({"EventType": "Race", "SubSessionID": 12345}) == "race"


def test_classify_practice_is_lap():
    assert classify_ibt({"EventType": "Practice", "SubSessionID": 12345}) == "lap"


def test_classify_race_without_subsession_is_lap():
    assert classify_ibt({"EventType": "Race", "SubSessionID": 0}) == "lap"


def test_classify_missing_fields_is_lap():
    assert classify_ibt({}) == "lap"


def test_decide_full_when_results_ready():
    assert decide_capture(results_ready=True, have_creds=True, file_age_s=1.0) == "full"


def test_decide_defer_when_young_with_creds():
    assert decide_capture(results_ready=False, have_creds=True,
                          file_age_s=10.0, grace_s=300.0) == "defer"


def test_decide_partial_when_old():
    assert decide_capture(results_ready=False, have_creds=True,
                          file_age_s=600.0, grace_s=300.0) == "partial"


def test_decide_partial_when_no_creds():
    assert decide_capture(results_ready=False, have_creds=False,
                          file_age_s=1.0) == "partial"


def test_race_report_defaults():
    r = RaceReport(path="x")
    assert not r.captured and not r.partial and not r.deferred and r.error is None
