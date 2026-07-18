"""Attribute the gap to the car ahead to specific corners.

Fed per tick with the player's LapDist and the current gap to the car
directly ahead (RaceState.current_gap_ahead). Samples the gap when the
player crosses each corner span's start and end; the delta across the
span is that corner's contribution this lap. After MIN_LAPS consecutive
laps on the SAME target, if one corner carries a dominant share of the
total loss, take_call() returns one line -- once per target per session.

Self-gating honesty rules: target change or a lap with no samples resets
accumulation; totals below the noise floor never call; the corner name
comes from the same track-db spans the prompt scheduler uses.
"""

MIN_LAPS = 2
DOMINANCE = 0.5          # corner must carry >= 50% of total loss
MIN_LOSS_PER_LAP_S = 0.15  # and >= this much time per lap


class CornerLossTracker:
    def __init__(self, spans: list[tuple[float, float, str]]) -> None:
        self._spans = sorted(spans or [], key=lambda s: s[0])
        self._target: int | None = None
        self._lap: int | None = None
        self._prev_dist: float | None = None
        self._entry_gap: dict[str, float] = {}
        self._lap_losses: dict[str, float] = {}      # this lap
        self._acc: dict[str, list[float]] = {}       # per-corner, per-lap
        self._laps_accumulated = 0
        self._called_targets: set[int] = set()

    def feed(self, lap_dist_m: float, gap_ahead_s: float,
             ahead_idx: int, lap: int) -> None:
        if not self._spans:
            return
        if ahead_idx != self._target:
            self._reset_target(ahead_idx)
        if lap != self._lap:
            self._close_lap()
            self._lap = lap
        prev = self._prev_dist if self._prev_dist is not None else lap_dist_m
        self._prev_dist = lap_dist_m
        for start_m, end_m, name in self._spans:
            if prev < start_m <= lap_dist_m:
                self._entry_gap[name] = gap_ahead_s
            if prev < end_m <= lap_dist_m and name in self._entry_gap:
                self._lap_losses[name] = gap_ahead_s - self._entry_gap.pop(name)

    def take_call(self, target_name: str) -> str | None:
        """One line when a dominant corner emerges; None otherwise.
        target_name is accepted for future phrasing use; the line itself
        stays name-free ('him') because the threat/attack calls already
        named the car."""
        if (self._target is None or self._target in self._called_targets
                or self._laps_accumulated < MIN_LAPS):
            return None
        per_corner = {
            name: sum(losses) / len(losses)
            for name, losses in self._acc.items()
            if len(losses) >= MIN_LAPS
        }
        if not per_corner:
            return None
        total = sum(v for v in per_corner.values() if v > 0)
        if total <= 0:
            return None
        name, loss = max(per_corner.items(), key=lambda kv: kv[1])
        if loss < MIN_LOSS_PER_LAP_S or loss / total < DOMINANCE:
            return None
        self._called_targets.add(self._target)
        return f"You're losing him mainly in {name}."

    def _close_lap(self) -> None:
        if self._lap_losses:
            for name, loss in self._lap_losses.items():
                self._acc.setdefault(name, []).append(loss)
            self._laps_accumulated += 1
        self._lap_losses = {}
        self._entry_gap = {}
        self._prev_dist = None

    def _reset_target(self, new_target: int) -> None:
        self._target = new_target
        self._entry_gap = {}
        self._lap_losses = {}
        self._acc = {}
        self._laps_accumulated = 0
        self._lap = None
