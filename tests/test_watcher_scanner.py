"""Tests for the pure watcher discovery/promotion logic."""

from pathlib import Path

from core.watcher.scanner import IbtCandidate, find_new_ibts, should_promote

NOW = 1_000_000.0


def _c(name: str, age_s: float) -> IbtCandidate:
    return IbtCandidate(path=Path(f"C:/tel/{name}"), mtime=NOW - age_s)


def test_fresh_file_excluded_by_stability_window():
    out = find_new_ibts([_c("a.ibt", 30.0)], processed=set(), now=NOW)
    assert out == []


def test_old_file_included():
    out = find_new_ibts([_c("a.ibt", 120.0)], processed=set(), now=NOW)
    assert [c.path.name for c in out] == ["a.ibt"]


def test_stability_boundary_is_min_age():
    exactly = find_new_ibts([_c("a.ibt", 90.0)], processed=set(), now=NOW)
    just_under = find_new_ibts([_c("a.ibt", 89.9)], processed=set(), now=NOW)
    assert [c.path.name for c in exactly] == ["a.ibt"]  # >= min_age is stable
    assert just_under == []


def test_processed_paths_deduped():
    cand = _c("a.ibt", 120.0)
    out = find_new_ibts([cand], processed={str(cand.path)}, now=NOW)
    assert out == []


def test_results_ordered_oldest_first():
    out = find_new_ibts(
        [_c("new.ibt", 100.0), _c("old.ibt", 5000.0)], processed=set(), now=NOW
    )
    assert [c.path.name for c in out] == ["old.ibt", "new.ibt"]


def test_should_promote_when_no_existing_pb():
    assert should_promote(best_lap_time=100.0, existing_pb_time=None)


def test_should_promote_when_faster():
    assert should_promote(best_lap_time=99.9, existing_pb_time=100.0)


def test_no_promote_when_slower_or_equal():
    assert not should_promote(best_lap_time=100.1, existing_pb_time=100.0)
    assert not should_promote(best_lap_time=100.0, existing_pb_time=100.0)
