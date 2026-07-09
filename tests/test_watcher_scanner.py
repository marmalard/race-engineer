"""Tests for the pure watcher discovery/promotion logic."""

from pathlib import Path

from core.watcher.scanner import (
    IbtCandidate,
    find_new_ibts,
    is_plausible_lap,
    should_promote,
)

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


# --- is_plausible_lap -------------------------------------------------


def test_plausible_normal_lap_passes():
    # Spa (6929m) in ~2:45 -> avg ~42 m/s, comfortably real.
    assert is_plausible_lap(lap_time_s=165.0, track_length_m=6929.3)


def test_bogus_okayama_style_lap_fails():
    # The real back-fill bug: 3654.7m "lap" in 11.26s -> avg ~324 m/s.
    assert not is_plausible_lap(lap_time_s=11.26, track_length_m=3654.7)


def test_bogus_virginia_style_lap_fails():
    # 5216.9m "lap" in 30.66s -> avg ~170 m/s.
    assert not is_plausible_lap(lap_time_s=30.66, track_length_m=5216.9)


def test_boundary_exactly_at_max_avg_speed_passes():
    # avg == max_avg_speed is allowed; a hair faster is not.
    length = 4400.0
    at_limit = length / 85.0  # 51.76s -> avg exactly 85 m/s
    assert is_plausible_lap(lap_time_s=at_limit, track_length_m=length)
    assert not is_plausible_lap(lap_time_s=at_limit - 1.0, track_length_m=length)


def test_short_spa_lap_needs_at_least_52s():
    # A 4.4 km lap under ~52s is impossible.
    assert not is_plausible_lap(lap_time_s=45.0, track_length_m=4400.0)
    assert is_plausible_lap(lap_time_s=60.0, track_length_m=4400.0)


def test_nonpositive_lap_time_fails_closed():
    assert not is_plausible_lap(lap_time_s=0.0, track_length_m=4400.0)
    assert not is_plausible_lap(lap_time_s=-5.0, track_length_m=4400.0)


def test_unknown_track_length_passes_open():
    # Without a length we cannot judge; do not reject a real lap.
    assert is_plausible_lap(lap_time_s=90.0, track_length_m=0.0)


# --- covers_full_lap --------------------------------------------------

from core.watcher.scanner import covers_full_lap  # noqa: E402


def test_covers_full_lap_passes_for_complete_lap():
    # Spa GP (6929m) — distance grid ends at ~6928m, well above 98% floor.
    assert covers_full_lap(distance_covered_m=6928.0, track_length_m=6929.0)


def test_covers_full_lap_rejects_stop_short():
    # The actual bad Spa 525 lap: 92.8% of ~7004m -> distance[-1] ~6499m.
    assert not covers_full_lap(distance_covered_m=6499.0, track_length_m=7004.0)


def test_covers_full_lap_boundary_at_exactly_98_pct():
    # At exactly 98% the gate should pass; one metre below should fail.
    track = 10_000.0
    exactly = track * 0.98          # 9800.0
    just_under = exactly - 1.0      # 9799.0
    assert covers_full_lap(distance_covered_m=exactly, track_length_m=track)
    assert not covers_full_lap(distance_covered_m=just_under, track_length_m=track)


def test_covers_full_lap_unknown_length_passes_open():
    # If track length is unknown (<= 0) we cannot judge; do not reject.
    assert covers_full_lap(distance_covered_m=100.0, track_length_m=0.0)
    assert covers_full_lap(distance_covered_m=100.0, track_length_m=-1.0)
