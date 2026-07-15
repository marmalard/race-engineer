"""Start page pure helpers (A1). Rendering is display-only (untested
by repo convention); the state-aware pick logic is pure and tested."""

from core.race.race_store import StoredRaceMeta

from app.pages.start import pick_undebriefed


def _meta(subsession_id: int, track: str = "Okayama") -> StoredRaceMeta:
    return StoredRaceMeta(
        subsession_id=subsession_id, cust_id=1, driver_name="X",
        track_name=track, car="MX-5", series_name="S",
        session_date="2026-07-14 19:00:00", sof=1300,
        start_position=8, finish_position=5, incidents=2,
        irating_delta=12, created_at="2026-07-14 21:00:00",
    )


class TestPickUndebriefed:
    def test_empty_list_returns_none(self):
        assert pick_undebriefed([], lambda s, c: False) is None

    def test_first_meta_without_debrief_wins(self):
        # list_races is newest-first (created_at DESC) — position 0 is
        # the latest capture.
        metas = [_meta(3), _meta(2), _meta(1)]
        picked = pick_undebriefed(metas, lambda s, c: s == 3)
        assert picked is not None and picked.subsession_id == 2

    def test_all_debriefed_returns_none(self):
        metas = [_meta(2), _meta(1)]
        assert pick_undebriefed(metas, lambda s, c: True) is None

    def test_store_errors_do_not_propagate(self):
        def boom(_s, _c):
            raise RuntimeError("db locked")

        assert pick_undebriefed([_meta(1)], boom) is None
