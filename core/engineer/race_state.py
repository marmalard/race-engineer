"""Rolling race-state summarizer over the live CarIdx arrays.

PURE state machine in the LapBoundaryTracker mold: no pyirsdk, no I/O.
live_coach feeds one sample dict per tick; feed() returns True on the
player's lap boundary. Trend math runs only on lap boundaries -- per-tick
work is an array read. snapshot() is the compact race-state dict that
grounds BOTH the PTT fast path and the Claude path (one representation,
two consumers).

Gap convention: CarIdxF2Time is race-time behind the leader, so
gap_ahead_s = my_f2 - ahead_f2 (positive) and gap_behind_s =
behind_f2 - my_f2 (positive). Trend is gap[-1] - gap[-2] per lap:
NEGATIVE trend on `behind` means he is closing; POSITIVE trend on
`ahead` means you are losing ground.

Not available live (accepted): opponent pedals/tires/fuel. Opponent
behavior is inferred from gaps and lap times -- what real engineers do.
"""

import re
from dataclasses import dataclass

# The extra channels live_coach reads for the engineer. CarIdx values are
# EXPECTED to be lists here -- the scalar churn guard must not apply.
ENGINEER_CHANNELS = [
    "SessionTime",
    "CarIdxLap",
    "CarIdxPosition",
    "CarIdxLapDistPct",
    "CarIdxF2Time",
    "CarIdxOnPitRoad",
    "SessionLapsRemain",
    "SessionTimeRemain",
]

# iRacing SessionLapsRemain sentinel for unlimited/timed sessions.
_UNLIMITED = 32767

_CARIDX_KEYS = ("CarIdxLap", "CarIdxPosition", "CarIdxF2Time",
                "CarIdxOnPitRoad", "CarIdxLapDistPct")


def speech_name(user_name: str) -> str:
    """iRacing display name -> spoken surname: 'Anthony Moorman2' -> 'Moorman'.

    Known limit: multi-word surnames ('De Silva') and suffixes ('Jr') collapse
    to the last word.
    """
    cleaned = re.sub(r"\d+$", "", (user_name or "").strip())
    parts = cleaned.split()
    return parts[-1] if parts else "the other car"


@dataclass(frozen=True)
class LapGaps:
    lap: int
    position: int
    ahead_idx: int | None
    gap_ahead_s: float | None
    behind_idx: int | None
    gap_behind_s: float | None


class RaceState:
    def __init__(self, player_idx: int) -> None:
        self.player_idx = player_idx
        self._roster: dict[int, dict] = {}
        self._prev_player_lap: int | None = None
        self._player_lap_start: float | None = None
        self.player_lap_times: list[float] = []
        self.lap_gaps: list[LapGaps] = []
        self._positions: list[int] = []
        self._f2: list[float] = []
        self._laps: list[int] = []
        self._pcts: list[float] = []
        self._laps_remaining: int | None = None
        self._time_remaining: float | None = None

    def set_roster(self, drivers: list[dict]) -> None:
        """DriverInfo Drivers rows, keyed by CarIdx."""
        self._roster = {
            int(d.get("CarIdx", -1)): d for d in drivers or []
        }

    def feed(self, sample: dict) -> bool:
        """One tick. Returns True on the player's lap boundary."""
        if any(not isinstance(sample.get(k), list) for k in _CARIDX_KEYS):
            return False
        laps = sample["CarIdxLap"]
        if self.player_idx >= len(laps):
            return False
        self._laps = [int(v or 0) for v in laps]
        self._positions = [int(v or 0) for v in sample["CarIdxPosition"]]
        self._f2 = [float(v or 0.0) for v in sample["CarIdxF2Time"]]
        self._pcts = [
            float(v) if isinstance(v, (int, float)) else -1.0
            for v in sample["CarIdxLapDistPct"]
        ]
        raw_remain = sample.get("SessionLapsRemain")
        self._laps_remaining = (
            int(raw_remain) if isinstance(raw_remain, (int, float))
            and 0 <= int(raw_remain) < _UNLIMITED else None
        )
        raw_time = sample.get("SessionTimeRemain")
        self._time_remaining = (
            float(raw_time) if isinstance(raw_time, (int, float))
            and raw_time >= 0 else None
        )
        st = float(sample.get("SessionTime") or 0.0)

        my_lap = self._laps[self.player_idx]
        boundary = (self._prev_player_lap is not None
                    and my_lap == self._prev_player_lap + 1)
        if boundary:
            if self._player_lap_start is not None:
                self.player_lap_times.append(st - self._player_lap_start)
            self._player_lap_start = st
            self._record_lap_gaps(my_lap)
        elif self._prev_player_lap != my_lap:
            # multi-lap jump or reset: restart the clock, never record a fused lap time
            self._player_lap_start = st
        self._prev_player_lap = my_lap
        return boundary

    def _idx_at_position(self, pos: int) -> int | None:
        if pos < 1:
            return None
        for idx, p in enumerate(self._positions):
            if p == pos and idx != self.player_idx:
                return idx
        return None

    def _same_racing_lap(self, a: int, b: int) -> bool:
        """True when cars a and b are within one lap of total race
        progress. F2Time is measured in each car's own lap frame, so a
        gap is only physically meaningful inside that window -- a lapped
        car's F2 difference is a wrong number, and silence beats a wrong
        number. Total progress (lap + pct) also keeps the boundary-tick
        case honest: at the player's line crossing, the car two seconds
        behind is momentarily still on the previous lap NUMBER but is
        within 1.0 laps of progress."""
        pa, pb = self._pcts[a], self._pcts[b]
        if pa < 0 or pb < 0:
            return False
        return abs((self._laps[a] + pa) - (self._laps[b] + pb)) < 1.0

    def _record_lap_gaps(self, lap: int) -> None:
        my_pos = self._positions[self.player_idx]
        my_f2 = self._f2[self.player_idx]
        ahead = self._idx_at_position(my_pos - 1)
        behind = self._idx_at_position(my_pos + 1)
        gap_ahead = None
        if ahead is not None and self._same_racing_lap(self.player_idx, ahead):
            gap_ahead = my_f2 - self._f2[ahead]
        gap_behind = None
        if behind is not None and self._same_racing_lap(self.player_idx, behind):
            gap_behind = self._f2[behind] - my_f2
        self.lap_gaps.append(LapGaps(
            lap=lap,
            position=my_pos,
            ahead_idx=ahead,
            gap_ahead_s=gap_ahead,
            behind_idx=behind,
            gap_behind_s=gap_behind,
        ))

    def current_gap_ahead(self) -> tuple[int, float] | None:
        """Per-tick (ahead_idx, gap_s) for the corner-loss tracker."""
        if not self._positions or self.player_idx >= len(self._positions):
            return None
        ahead = self._idx_at_position(self._positions[self.player_idx] - 1)
        if ahead is None:
            return None
        if not self._same_racing_lap(self.player_idx, ahead):
            return None
        return ahead, self._f2[self.player_idx] - self._f2[ahead]

    def name_of(self, idx: int | None) -> str:
        if idx is None:
            return "the other car"
        return speech_name(str(self._roster.get(idx, {}).get("UserName", "")))

    def _neighbor(self, which: str) -> dict | None:
        recs = [g for g in self.lap_gaps
                if getattr(g, f"{which}_idx") is not None
                and getattr(g, f"gap_{which}_s") is not None]
        if not recs:
            return None
        last = recs[-1]
        idx = getattr(last, f"{which}_idx")
        gap = getattr(last, f"gap_{which}_s")
        trend = None
        if (len(recs) >= 2 and getattr(recs[-2], f"{which}_idx") == idx
                and recs[-2].lap == last.lap - 1):
            trend = gap - getattr(recs[-2], f"gap_{which}_s")
        driver = self._roster.get(idx, {})
        return {
            "name": self.name_of(idx),
            "irating": driver.get("IRating"),
            "gap_s": round(gap, 2),
            "trend_s_per_lap": round(trend, 2) if trend is not None else None,
        }

    def snapshot(self) -> dict:
        """Compact race-state dict -- the grounding payload."""
        last = self.lap_gaps[-1] if self.lap_gaps else None
        return {
            "position": last.position if last else None,
            "field_size": sum(1 for p in self._positions if p > 0),  # classified cars, not cars currently on track
            "lap": self._laps[self.player_idx] if self._laps else None,
            "laps_remaining": self._laps_remaining,
            "time_remaining_s": self._time_remaining,
            "last_lap_s": (round(self.player_lap_times[-1], 2)
                           if self.player_lap_times else None),
            "best_lap_s": (round(min(self.player_lap_times), 2)
                           if self.player_lap_times else None),
            "ahead": self._neighbor("ahead"),
            "behind": self._neighbor("behind"),
        }
