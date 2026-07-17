"""Dataclasses for the progression layer (Strava layer, v3 §5)."""

from dataclasses import dataclass

IMPLIED_IR_MAX_SERIES = 3  # bound the weekly harvest cost (30 fetches/series)


@dataclass
class StreakSummary:
    """Official-race volume — the product's leading metric as the user's own stat."""

    races_this_week: int = 0
    streak_weeks: int = 0
    total_races: int = 0


@dataclass
class ComboImplied:
    """One combo's placement on this week's field curve."""

    track_id: str
    track_name: str
    car: str
    series_name: str        # the series whose curve was used (honesty label)
    lap_s: float            # the practice PB placed on the curve
    implied_lo: int
    implied_hi: int
    weight: float           # representative-lap count (more practice = more signal)


@dataclass
class DriverImpliedIR:
    """Weighted roll-up of per-combo bands. ALWAYS a band, never a point."""

    lo: int
    hi: int
    combo_count: int
