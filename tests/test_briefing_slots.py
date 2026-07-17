"""Pure slot computation + usual-window inference."""

from datetime import datetime, timezone

from core.benchmark.iracing_api import RaceTimeDescriptor
from core.briefing.slots import infer_window, upcoming_slots

NOW = datetime(2026, 7, 15, 22, 30, tzinfo=timezone.utc)


class TestUpcomingSlots:
    def test_repeating_every_two_hours(self):
        d = RaceTimeDescriptor(
            repeating=True,
            first_session_time="00:15",
            repeat_minutes=120,
            day_offset=[0, 1, 2, 3, 4, 5, 6],
        )
        slots = upcoming_slots([d], NOW, count=3)
        assert [s.isoformat() for s in slots] == [
            "2026-07-16T00:15:00+00:00",
            "2026-07-16T02:15:00+00:00",
            "2026-07-16T04:15:00+00:00",
        ]

    def test_explicit_session_times_filters_past(self):
        d = RaceTimeDescriptor(
            repeating=False,
            first_session_time=None,
            repeat_minutes=None,
            session_times=[
                "2026-07-15T20:00:00Z",  # past
                "2026-07-16T01:00:00Z",
                "2026-07-16T05:00:00Z",
            ],
        )
        slots = upcoming_slots([d], NOW, count=4)
        assert len(slots) == 2
        assert slots[0].isoformat() == "2026-07-16T01:00:00+00:00"

    def test_malformed_descriptor_yields_no_slots(self):
        d = RaceTimeDescriptor(
            repeating=True,
            first_session_time=None,  # broken
            repeat_minutes=None,
        )
        assert upcoming_slots([d], NOW, count=3) == []


class TestInferWindow:
    def test_median_hour_pm_window(self):
        # watcher format: "YYYY-MM-DD HH-MM-SS"; user practices ~21:00
        dates = [
            "2026-07-01 20-45-00",
            "2026-07-03 21-10-00",
            "2026-07-08 21-30-00",
            "2026-07-10 22-05-00",
        ]
        window = infer_window(dates)
        assert window == (19, 23)  # median 21 +/- 2

    def test_too_few_sessions_returns_none(self):
        assert infer_window(["2026-07-01 20-45-00"]) is None

    def test_garbage_dates_skipped(self):
        dates = ["not-a-date"] * 3 + [
            "2026-07-01 20-00-00",
            "2026-07-02 20-30-00",
            "2026-07-03 21-00-00",
        ]
        assert infer_window(dates) == (18, 22)


class TestSlotFitsWindow:
    def test_inside_window(self):
        from datetime import datetime, timezone
        from core.briefing.slots import slot_fits_window
        # Use a UTC datetime and compute expected local hour the same way
        # the function does, so the test is timezone-agnostic.
        dt = datetime(2026, 7, 21, 2, 15, tzinfo=timezone.utc)
        local_hour = dt.astimezone().hour
        assert slot_fits_window(dt, (local_hour, local_hour)) is True
        assert slot_fits_window(dt, ((local_hour + 2) % 24,
                                     (local_hour + 3) % 24)) is False

    def test_none_window_never_fits(self):
        from datetime import datetime, timezone
        from core.briefing.slots import slot_fits_window
        dt = datetime(2026, 7, 21, 2, 15, tzinfo=timezone.utc)
        assert slot_fits_window(dt, None) is False
