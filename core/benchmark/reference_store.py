"""SQLite store of reference laps, one per car/track combo per source.

The reference lap is the data spine of the redesign: the briefing
decomposes it, the debrief diffs against it. Sources: 'g61' (imported
Garage 61 lap, preferred) or 'personal_best' (promoted from the
driver's own sessions, fallback).
"""

import contextlib
import io
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from core.telemetry.normalizer import NormalizedLap

ARRAY_FIELDS = [
    "distance", "speed", "throttle", "brake", "steering",
    "gear", "rpm", "lat", "lon", "elapsed_time",
]


@dataclass
class ReferenceLapMeta:
    """Metadata for a stored reference lap (no arrays)."""

    ref_id: int
    track_id: str
    car: str
    source: str  # 'g61' | 'personal_best'
    lap_time: float
    driver_name: str | None
    imported_at: str


@dataclass
class ReferenceLap:
    """A reference lap with full telemetry arrays and metadata."""

    meta: ReferenceLapMeta
    lap: NormalizedLap

    @property
    def source(self) -> str:
        """Source of the reference lap: 'g61' or 'personal_best'."""
        return self.meta.source


class ReferenceStore:
    """CRUD for reference laps stored in SQLite.

    One row per (track_id, car, source) tuple. Calling save() on an
    existing combo upserts (overwrites) the stored lap. get() returns
    the best available reference for a combo, preferring 'g61' over
    'personal_best'.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create the reference_laps table if it does not exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.closing(self._conn()) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reference_laps (
                    ref_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    track_id    TEXT NOT NULL,
                    car         TEXT NOT NULL,
                    source      TEXT NOT NULL,
                    lap_time    REAL NOT NULL,
                    track_length REAL NOT NULL,
                    driver_name TEXT,
                    imported_at TEXT NOT NULL,
                    channels    BLOB NOT NULL,
                    UNIQUE(track_id, car, source)
                )
            """)
            conn.commit()

    def save(
        self,
        track_id: str,
        car: str,
        lap: NormalizedLap,
        source: str,
        driver_name: str | None = None,
    ) -> None:
        """Upsert a reference lap for the given car/track/source combo.

        Args:
            track_id: iRacing numeric track ID as a string (e.g. "523").
            car: Car name matching the session (e.g. "BMW M2 CS Racing").
            lap: Fully normalized lap to store.
            source: 'g61' or 'personal_best'.
            driver_name: Optional driver attribution label.
        """
        buf = io.BytesIO()
        np.savez_compressed(buf, **{f: getattr(lap, f) for f in ARRAY_FIELDS})
        blob = buf.getvalue()
        imported_at = datetime.now(timezone.utc).isoformat()

        with contextlib.closing(self._conn()) as conn:
            conn.execute(
                """
                INSERT INTO reference_laps
                    (track_id, car, source, lap_time, track_length,
                     driver_name, imported_at, channels)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(track_id, car, source) DO UPDATE SET
                    lap_time    = excluded.lap_time,
                    track_length= excluded.track_length,
                    driver_name = excluded.driver_name,
                    imported_at = excluded.imported_at,
                    channels    = excluded.channels
                """,
                (
                    track_id, car, source, lap.lap_time, lap.track_length,
                    driver_name, imported_at, blob,
                ),
            )
            conn.commit()

    def get(self, track_id: str, car: str) -> ReferenceLap | None:
        """Return the best available reference lap for a car/track combo.

        Preference order: 'g61' first, then 'personal_best'. Returns
        None when no reference exists for the combo.
        """
        with contextlib.closing(self._conn()) as conn:
            row = conn.execute(
                """
                SELECT * FROM reference_laps
                WHERE track_id = ? AND car = ?
                ORDER BY CASE source WHEN 'g61' THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (track_id, car),
            ).fetchone()

        if row is None:
            return None
        return ReferenceLap(meta=self._meta(row), lap=self._lap(row))

    def list_all(self) -> list[ReferenceLapMeta]:
        """Return metadata for every stored reference lap (no arrays).

        Sorted by track_id, then car for stable ordering.
        """
        with contextlib.closing(self._conn()) as conn:
            rows = conn.execute(
                "SELECT * FROM reference_laps ORDER BY track_id, car"
            ).fetchall()
        return [self._meta(r) for r in rows]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _meta(row: sqlite3.Row) -> ReferenceLapMeta:
        return ReferenceLapMeta(
            ref_id=row["ref_id"],
            track_id=row["track_id"],
            car=row["car"],
            source=row["source"],
            lap_time=row["lap_time"],
            driver_name=row["driver_name"],
            imported_at=row["imported_at"],
        )

    @staticmethod
    def _lap(row: sqlite3.Row) -> NormalizedLap:
        arrays = np.load(io.BytesIO(bytes(row["channels"])))
        return NormalizedLap(
            lap_number=0,
            lap_time=row["lap_time"],
            track_length=row["track_length"],
            is_valid=True,
            **{f: arrays[f] for f in ARRAY_FIELDS},
        )
