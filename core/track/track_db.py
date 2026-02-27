"""SQLite-backed track and corner database."""

import sqlite3
from pathlib import Path

from core.track.models import (
    Corner,
    CornerType,
    Track,
    TrackCharacter,
    TrackType,
)


class TrackDB:
    """SQLite-backed track and corner database."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        conn = self._get_conn()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tracks (
                    track_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    config TEXT,
                    length_meters REAL,
                    track_type TEXT,
                    character TEXT,
                    notes TEXT
                );

                CREATE TABLE IF NOT EXISTS corners (
                    corner_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    track_id TEXT REFERENCES tracks(track_id),
                    corner_number INTEGER,
                    name TEXT,
                    distance_start_meters REAL,
                    distance_end_meters REAL,
                    corner_type TEXT,
                    notes TEXT
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    track_id TEXT REFERENCES tracks(track_id),
                    car TEXT,
                    session_type TEXT,
                    session_date TIMESTAMP,
                    best_lap_time REAL,
                    theoretical_best REAL,
                    lap_count INTEGER,
                    ibt_file_path TEXT,
                    notes TEXT
                );

                CREATE TABLE IF NOT EXISTS laps (
                    lap_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT REFERENCES sessions(session_id),
                    lap_number INTEGER,
                    lap_time REAL,
                    is_valid BOOLEAN,
                    sector_times TEXT
                );
                """
            )
            conn.commit()
        finally:
            conn.close()

    # --- Track CRUD ---

    def upsert_track(self, track: Track) -> None:
        """Insert or update a track."""
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO tracks (track_id, name, config, length_meters, track_type, character, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(track_id) DO UPDATE SET
                    name=excluded.name,
                    config=excluded.config,
                    length_meters=excluded.length_meters,
                    track_type=excluded.track_type,
                    character=excluded.character,
                    notes=excluded.notes
                """,
                (
                    track.track_id,
                    track.name,
                    track.config,
                    track.length_meters,
                    track.track_type.value if track.track_type else None,
                    track.character.value if track.character else None,
                    track.notes,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_track(self, track_id: str) -> Track | None:
        """Get a track by ID, including its corners."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM tracks WHERE track_id = ?", (track_id,)
            ).fetchone()
            if row is None:
                return None

            corners = self.get_corners(track_id)
            return Track(
                track_id=row["track_id"],
                name=row["name"],
                config=row["config"],
                length_meters=row["length_meters"],
                track_type=TrackType(row["track_type"]) if row["track_type"] else TrackType.ROAD,
                character=TrackCharacter(row["character"]) if row["character"] else None,
                notes=row["notes"],
                corners=corners,
            )
        finally:
            conn.close()

    def list_tracks(self) -> list[Track]:
        """List all tracks (without corners for efficiency)."""
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT * FROM tracks ORDER BY name").fetchall()
            return [
                Track(
                    track_id=r["track_id"],
                    name=r["name"],
                    config=r["config"],
                    length_meters=r["length_meters"],
                    track_type=TrackType(r["track_type"]) if r["track_type"] else TrackType.ROAD,
                    character=TrackCharacter(r["character"]) if r["character"] else None,
                    notes=r["notes"],
                )
                for r in rows
            ]
        finally:
            conn.close()

    # --- Corner CRUD ---

    def upsert_corners(self, track_id: str, corners: list[Corner]) -> None:
        """Replace all corners for a track."""
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM corners WHERE track_id = ?", (track_id,))
            for c in corners:
                conn.execute(
                    """
                    INSERT INTO corners (track_id, corner_number, name,
                                         distance_start_meters, distance_end_meters,
                                         corner_type, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        track_id,
                        c.corner_number,
                        c.name,
                        c.distance_start_meters,
                        c.distance_end_meters,
                        c.corner_type.value if c.corner_type else None,
                        c.notes,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def get_corners(self, track_id: str) -> list[Corner]:
        """Get all corners for a track, ordered by corner number."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM corners WHERE track_id = ? ORDER BY corner_number",
                (track_id,),
            ).fetchall()
            return [
                Corner(
                    corner_id=r["corner_id"],
                    track_id=r["track_id"],
                    corner_number=r["corner_number"],
                    name=r["name"],
                    distance_start_meters=r["distance_start_meters"],
                    distance_end_meters=r["distance_end_meters"],
                    corner_type=CornerType(r["corner_type"]) if r["corner_type"] else None,
                    notes=r["notes"],
                )
                for r in rows
            ]
        finally:
            conn.close()

    def populate_from_detection(
        self,
        track_id: str,
        segments: list,
    ) -> None:
        """Seed corner entries from automated corner detection.

        Only creates entries if no corners exist for this track yet.
        Accepts a list of CornerSegment objects from the corner detector.
        """
        existing = self.get_corners(track_id)
        if existing:
            return

        corners = [
            Corner(
                corner_id=None,
                track_id=track_id,
                corner_number=seg.corner_number,
                name=None,
                distance_start_meters=seg.distance_start,
                distance_end_meters=seg.distance_end,
                corner_type=None,
                notes=None,
            )
            for seg in segments
        ]
        self.upsert_corners(track_id, corners)
