"""SQLite store for weekly implied-iR snapshots (data/progression.db).

The field curve is week-scoped and the briefing cache is expendable --
snapshots make the implied-iR trend line durable. save_week is
DELETE+INSERT keyed by week_start (the region_diagnoses idempotency
pattern): recomputing a week overwrites it.
"""

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from core.progression.models import ComboImplied

DEFAULT_DB_PATH = Path("data/progression.db")


class ImpliedIRStore:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS implied_ir_history (
                    week_start TEXT NOT NULL,
                    track_id TEXT NOT NULL,
                    track_name TEXT NOT NULL,
                    car TEXT NOT NULL,
                    series_name TEXT NOT NULL,
                    lap_s REAL NOT NULL,
                    implied_lo INTEGER NOT NULL,
                    implied_hi INTEGER NOT NULL,
                    weight REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (week_start, track_id, car)
                )
                """
            )

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def save_week(self, week_start: str, rows: list[ComboImplied]) -> None:
        """Replace the snapshot rows for one race week (empty list clears)."""
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM implied_ir_history WHERE week_start = ?", (week_start,)
            )
            conn.executemany(
                """
                INSERT INTO implied_ir_history (
                    week_start, track_id, track_name, car, series_name,
                    lap_s, implied_lo, implied_hi, weight, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (week_start, r.track_id, r.track_name, r.car, r.series_name,
                     r.lap_s, r.implied_lo, r.implied_hi, r.weight, now)
                    for r in rows
                ],
            )

    def get_week(self, week_start: str) -> list[ComboImplied]:
        """Return all combo rows for a given week, ordered by weight desc."""
        with self._conn() as conn:
            cur = conn.execute(
                """
                SELECT track_id, track_name, car, series_name, lap_s,
                       implied_lo, implied_hi, weight
                FROM implied_ir_history WHERE week_start = ?
                ORDER BY weight DESC, track_name, car
                """,
                (week_start,),
            )
            return [self._row(r) for r in cur.fetchall()]

    def history(self) -> list[tuple[str, list[ComboImplied]]]:
        """All snapshots grouped per week, week-ascending (trend-line input)."""
        with self._conn() as conn:
            cur = conn.execute(
                """
                SELECT week_start, track_id, track_name, car, series_name,
                       lap_s, implied_lo, implied_hi, weight
                FROM implied_ir_history
                ORDER BY week_start, weight DESC, track_name, car
                """
            )
            grouped: dict[str, list[ComboImplied]] = {}
            for r in cur.fetchall():
                grouped.setdefault(r["week_start"], []).append(self._row(r))
        return sorted(grouped.items())

    def latest_week(self) -> tuple[str, list[ComboImplied]] | None:
        """Return the most recent week's snapshot, or None if empty."""
        hist = self.history()
        return hist[-1] if hist else None

    @staticmethod
    def _row(r: sqlite3.Row) -> ComboImplied:
        return ComboImplied(
            track_id=r["track_id"],
            track_name=r["track_name"],
            car=r["car"],
            series_name=r["series_name"],
            lap_s=r["lap_s"],
            implied_lo=r["implied_lo"],
            implied_hi=r["implied_hi"],
            weight=r["weight"],
        )
