"""Pure helpers on the Race Debrief page (rendering stays untested by
repo convention; the chunk-dedupe logic is pure and tested)."""

from app.pages.race_debrief import dedupe_race_chunks


def _chunk(sub: int, size: int, label: str) -> dict:
    return {"path": label, "label": label, "subsession_id": sub, "size": size}


class TestDedupeRaceChunks:
    def test_keeps_largest_chunk_per_subsession(self):
        # iRacing writes a new IBT per recording restart inside the race
        # server; the race is the largest chunk of its subsession group.
        races = [
            _chunk(1, 55_000_000, "race"),
            _chunk(1, 27_000_000, "quali"),
            _chunk(1, 2_000_000, "practice"),
            _chunk(2, 60_000_000, "other-race"),
        ]
        kept = dedupe_race_chunks(races)
        assert [r["label"] for r in kept] == ["race", "other-race"]

    def test_preserves_incoming_order(self):
        races = [
            _chunk(2, 10, "b-small"),
            _chunk(1, 99, "a-race"),
            _chunk(2, 50, "b-race"),
        ]
        kept = dedupe_race_chunks(races)
        assert [r["label"] for r in kept] == ["a-race", "b-race"]

    def test_empty_list(self):
        assert dedupe_race_chunks([]) == []
