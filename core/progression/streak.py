"""PURE race-week streak math. iRacing weeks flip on Tuesday."""

from datetime import date, datetime, timedelta

from core.progression.models import StreakSummary


def iracing_week_start(d: date) -> date:
    """Most recent Tuesday on or before d (Tuesday = weekday 1)."""
    return d - timedelta(days=(d.weekday() - 1) % 7)


def parse_race_date(session_date: str, created_at: str) -> date | None:
    """Race date from the API start_time; capture time as fallback.

    Partial captures store an empty session_date — created_at (always set)
    keeps them in the streak. Unparseable rows return None and count only
    toward the total.
    """
    for raw in (session_date, created_at):
        if not raw:
            continue
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            continue
    return None


def build_streak(races: list[tuple[str, str]], today: date) -> StreakSummary:
    """races = (session_date, created_at) per captured race.

    streak_weeks counts consecutive weeks with >= 1 race backward from the
    current week; an empty current week never breaks the streak (it is
    still in progress) — counting starts from the previous week instead.
    """
    dated = [parse_race_date(sd, ca) for sd, ca in races]
    weeks = {iracing_week_start(d) for d in dated if d is not None}

    current = iracing_week_start(today)
    races_this_week = sum(
        1 for d in dated if d is not None and iracing_week_start(d) == current
    )

    cursor = current if current in weeks else current - timedelta(days=7)
    streak = 0
    while cursor in weeks:
        streak += 1
        cursor -= timedelta(days=7)

    return StreakSummary(
        races_this_week=races_this_week,
        streak_weeks=streak,
        total_races=len(races),
    )
