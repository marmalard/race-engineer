"""SQLite-backed track and corner database."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from core.track.models import (
    Corner,
    CornerType,
    Track,
    TrackCharacter,
    TrackType,
)

if TYPE_CHECKING:  # duck-typed at runtime — keeps track_db below core.coaching
    from core.coaching.debrief import RegionDiagnosis


@dataclass
class SessionRow:
    """One sessions-table row for profile/history reads (no laps payload)."""

    session_id: str
    track_id: str
    track_name: str
    car: str
    session_type: str
    session_date: str
    best_lap_time: float | None
    lap_count: int
    ibt_file_path: str = ""


@dataclass
class LapRow:
    """One laps-table row."""

    lap_number: int
    lap_time: float
    is_valid: bool


@dataclass
class DiagnosisContext:
    """What was compared, recorded alongside every region row."""

    driver_lap_number: int
    driver_lap_time: float
    reference_source: str        # 'personal_best' | 'g61'
    reference_lap_time: float
    total_time_delta_s: float


@dataclass
class DiagnosisRow:
    """One region_diagnoses row joined with its session context."""

    session_id: str
    track_id: str
    track_name: str
    car: str
    session_type: str
    session_date: str
    region_rank: int
    label: str
    distance_start_m: float
    distance_end_m: float
    time_lost_s: float
    braking_delta_m: float | None
    min_speed_delta_ms: float
    throttle_delta_m: float | None
    brake_release_delta_m: float | None
    exit_speed_delta_ms: float
    driver_min_speed_ms: float
    reference_min_speed_ms: float
    driver_lap_number: int
    driver_lap_time: float
    reference_source: str
    reference_lap_time: float
    total_time_delta_s: float


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

                CREATE TABLE IF NOT EXISTS region_diagnoses (
                    diagnosis_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(session_id),
                    region_rank INTEGER NOT NULL,
                    label TEXT NOT NULL,
                    distance_start_m REAL NOT NULL,
                    distance_end_m REAL NOT NULL,
                    time_lost_s REAL NOT NULL,
                    braking_delta_m REAL,
                    min_speed_delta_ms REAL NOT NULL,
                    throttle_delta_m REAL,
                    brake_release_delta_m REAL,
                    exit_speed_delta_ms REAL NOT NULL,
                    driver_min_speed_ms REAL NOT NULL,
                    reference_min_speed_ms REAL NOT NULL,
                    driver_lap_number INTEGER NOT NULL,
                    driver_lap_time REAL NOT NULL,
                    reference_source TEXT NOT NULL,
                    reference_lap_time REAL NOT NULL,
                    total_time_delta_s REAL NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_region_diagnoses_session
                    ON region_diagnoses(session_id);
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

    # --- Session history (populated by the telemetry watcher) ---

    def record_session(
        self,
        session_id: str,
        track_id: str,
        car: str,
        session_type: str,
        session_date: str,
        best_lap_time: float | None,
        lap_count: int,
        ibt_file_path: str,
    ) -> None:
        """Insert or replace one session-history row (idempotent per id).

        Creates a stub track row if the track doesn't exist yet so that
        the foreign-key constraint is satisfied even when called before
        _load_corners has run (e.g. in tests or on first-ever scan).
        """
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO tracks (track_id, name) VALUES (?, ?)",
                (track_id, track_id),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO sessions
                    (session_id, track_id, car, session_type, session_date,
                     best_lap_time, lap_count, ibt_file_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, track_id, car, session_type, session_date,
                 best_lap_time, lap_count, ibt_file_path),
            )
            conn.commit()
        finally:
            conn.close()

    def record_laps(
        self, session_id: str, laps: list[tuple[int, float, bool]]
    ) -> None:
        """Replace the lap rows for a session (idempotent on rerun).

        Args:
            laps: (lap_number, lap_time, is_valid) tuples.
        """
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM laps WHERE session_id = ?", (session_id,))
            conn.executemany(
                "INSERT INTO laps (session_id, lap_number, lap_time, is_valid)"
                " VALUES (?, ?, ?, ?)",
                [(session_id, n, t, v) for n, t, v in laps],
            )
            conn.commit()
        finally:
            conn.close()

    def processed_ibt_paths(self) -> set[str]:
        """Every ibt_file_path already recorded — the watcher's dedupe set."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT ibt_file_path FROM sessions"
                " WHERE ibt_file_path IS NOT NULL"
            ).fetchall()
        finally:
            conn.close()
        return {r[0] for r in rows}

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

    def list_session_history(self) -> list[SessionRow]:
        """All recorded sessions, oldest first, with the track name joined."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT s.session_id, s.track_id,
                       COALESCE(t.name, s.track_id) AS track_name,
                       s.car, s.session_type, s.session_date,
                       s.best_lap_time, s.lap_count, s.ibt_file_path
                FROM sessions s
                LEFT JOIN tracks t ON t.track_id = s.track_id
                ORDER BY s.session_date
                """
            ).fetchall()
            return [
                SessionRow(
                    session_id=r["session_id"],
                    track_id=r["track_id"] or "",
                    track_name=r["track_name"] or "",
                    car=r["car"] or "",
                    session_type=r["session_type"] or "",
                    session_date=str(r["session_date"] or ""),
                    best_lap_time=r["best_lap_time"],
                    lap_count=r["lap_count"] or 0,
                    ibt_file_path=r["ibt_file_path"] or "",
                )
                for r in rows
            ]
        finally:
            conn.close()

    def get_session_laps(self, session_id: str) -> list[LapRow]:
        """Lap rows for one session, in lap order. Empty when unknown."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT lap_number, lap_time, is_valid FROM laps "
                "WHERE session_id = ? ORDER BY lap_number",
                (session_id,),
            ).fetchall()
            return [
                LapRow(lap_number=r["lap_number"], lap_time=r["lap_time"], is_valid=bool(r["is_valid"]))
                for r in rows
            ]
        finally:
            conn.close()

    def record_region_diagnoses(
        self,
        session_id: str,
        context: "DiagnosisContext",
        diagnoses: "list[RegionDiagnosis]",
    ) -> None:
        """Replace the diagnosis rows for a session (idempotent on rerun).

        Takes RegionDiagnosis objects duck-typed (attribute access only) —
        no runtime import of core.coaching. Empty list clears the rows.
        """
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        try:
            conn.execute(
                "DELETE FROM region_diagnoses WHERE session_id = ?",
                (session_id,),
            )
            conn.executemany(
                """
                INSERT INTO region_diagnoses (
                    session_id, region_rank, label,
                    distance_start_m, distance_end_m, time_lost_s,
                    braking_delta_m, min_speed_delta_ms, throttle_delta_m,
                    brake_release_delta_m, exit_speed_delta_ms,
                    driver_min_speed_ms, reference_min_speed_ms,
                    driver_lap_number, driver_lap_time,
                    reference_source, reference_lap_time,
                    total_time_delta_s, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        session_id, rank, d.label,
                        d.region.distance_start, d.region.distance_end,
                        d.region.time_lost,
                        d.braking_delta_m, d.min_speed_delta_ms,
                        d.throttle_delta_m, d.brake_release_delta_m,
                        d.exit_speed_delta_ms,
                        d.driver_min_speed_ms, d.reference_min_speed_ms,
                        context.driver_lap_number, context.driver_lap_time,
                        context.reference_source, context.reference_lap_time,
                        context.total_time_delta_s, now,
                    )
                    for rank, d in enumerate(diagnoses, start=1)
                ],
            )
            conn.commit()
        finally:
            conn.close()

    def list_region_diagnoses(self) -> list["DiagnosisRow"]:
        """All diagnosis rows joined with session context, ordered by
        session_date then region_rank."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT d.*, s.track_id AS s_track_id,
                       COALESCE(t.name, s.track_id) AS track_name,
                       s.car, s.session_type, s.session_date
                FROM region_diagnoses d
                JOIN sessions s ON s.session_id = d.session_id
                LEFT JOIN tracks t ON t.track_id = s.track_id
                ORDER BY s.session_date, d.region_rank
                """
            ).fetchall()
            return [
                DiagnosisRow(
                    session_id=r["session_id"],
                    track_id=r["s_track_id"] or "",
                    track_name=r["track_name"] or "",
                    car=r["car"] or "",
                    session_type=r["session_type"] or "",
                    session_date=r["session_date"] or "",
                    region_rank=r["region_rank"],
                    label=r["label"],
                    distance_start_m=r["distance_start_m"],
                    distance_end_m=r["distance_end_m"],
                    time_lost_s=r["time_lost_s"],
                    braking_delta_m=r["braking_delta_m"],
                    min_speed_delta_ms=r["min_speed_delta_ms"],
                    throttle_delta_m=r["throttle_delta_m"],
                    brake_release_delta_m=r["brake_release_delta_m"],
                    exit_speed_delta_ms=r["exit_speed_delta_ms"],
                    driver_min_speed_ms=r["driver_min_speed_ms"],
                    reference_min_speed_ms=r["reference_min_speed_ms"],
                    driver_lap_number=r["driver_lap_number"],
                    driver_lap_time=r["driver_lap_time"],
                    reference_source=r["reference_source"],
                    reference_lap_time=r["reference_lap_time"],
                    total_time_delta_s=r["total_time_delta_s"],
                )
                for r in rows
            ]
        finally:
            conn.close()
