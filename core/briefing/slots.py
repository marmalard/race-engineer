"""PURE race-slot computation and usual-window inference. No I/O.

Slot semantics: repeating descriptors anchor at first_session_time GMT and
repeat every repeat_minutes; explicit descriptors list ISO session_times.
day_offset is intentionally ignored for the daily-repeating common case
(offsets are relative to the week start; every-day series pass [0..6]) --
a wrong-day slot for an exotic schedule is an acceptable v1 degradation.
"""

from datetime import datetime, timedelta
from statistics import median

from core.benchmark.iracing_api import RaceTimeDescriptor

WINDOW_HALF_HOURS = 2
WINDOW_MIN_SESSIONS = 3


def upcoming_slots(
    descriptors: list[RaceTimeDescriptor],
    now_utc: datetime,
    count: int = 4,
) -> list[datetime]:
    """Next `count` race start times strictly after now_utc, UTC."""
    slots: list[datetime] = []
    for d in descriptors:
        if d.repeating and d.first_session_time and d.repeat_minutes:
            try:
                hh, mm = d.first_session_time.split(":")[:2]
                anchor = now_utc.replace(
                    hour=int(hh), minute=int(mm), second=0, microsecond=0
                )
            except (ValueError, AttributeError):
                continue
            step = timedelta(minutes=d.repeat_minutes)
            t = anchor - timedelta(days=1)  # start safely in the past
            while t <= now_utc:
                t += step
            for _ in range(count):
                slots.append(t)
                t += step
        else:
            for iso in d.session_times:
                try:
                    t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if t > now_utc:
                    slots.append(t)
    return sorted(set(slots))[:count]


def infer_window(session_dates: list[str]) -> tuple[int, int] | None:
    """Usual practice window (start_hour, end_hour) local, from watcher
    session_date strings ('YYYY-MM-DD HH-MM-SS'). None below 3 sessions."""
    hours: list[int] = []
    for s in session_dates:
        try:
            hours.append(int(s.split(" ")[1].split("-")[0]))
        except (IndexError, ValueError):
            continue
    if len(hours) < WINDOW_MIN_SESSIONS:
        return None
    mid = int(median(hours))
    return (max(0, mid - WINDOW_HALF_HOURS), min(23, mid + WINDOW_HALF_HOURS))
