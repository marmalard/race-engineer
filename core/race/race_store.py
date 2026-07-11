"""SQLite persistence for race narratives, debriefs, and chat.

data/races.db — deliberately separate from tracks.db (watcher-owned
sessions history) and reference_laps.db. Keyed by (subsession_id,
cust_id): two testers can race in the same subsession.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from core.race.models import RaceNarrative

DEFAULT_DB_PATH = Path("data/races.db")


@dataclass
class StoredRaceMeta:
    """Scalar race metadata for list views (no narrative payload)."""

    subsession_id: int
    cust_id: int
    driver_name: str
    track_name: str
    car: str
    series_name: str
    session_date: str
    sof: int
    start_position: int
    finish_position: int
    incidents: int
    irating_delta: int
    created_at: str


class RaceStore:
    """CRUD for persisted race debriefs."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS races (
                    subsession_id INTEGER NOT NULL,
                    cust_id INTEGER NOT NULL,
                    driver_name TEXT,
                    track_id INTEGER,
                    track_name TEXT,
                    car TEXT,
                    series_name TEXT,
                    session_date TEXT,
                    sof INTEGER,
                    field_size INTEGER,
                    start_position INTEGER,
                    finish_position INTEGER,
                    incidents INTEGER,
                    irating_old INTEGER,
                    irating_new INTEGER,
                    ibt_file_path TEXT,
                    narrative_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (subsession_id, cust_id)
                );
                CREATE TABLE IF NOT EXISTS debriefs (
                    subsession_id INTEGER NOT NULL,
                    cust_id INTEGER NOT NULL,
                    debrief_text TEXT NOT NULL,
                    model TEXT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (subsession_id, cust_id)
                );
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subsession_id INTEGER NOT NULL,
                    cust_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def save_race(
        self, narrative: RaceNarrative, ibt_file_path: str
    ) -> None:
        """Insert or replace a race narrative (chat is never touched)."""
        h = narrative.header
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO races (
                    subsession_id, cust_id, driver_name, track_id,
                    track_name, car, series_name, session_date, sof,
                    field_size, start_position, finish_position,
                    incidents, irating_old, irating_new, ibt_file_path,
                    narrative_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    h.subsession_id, h.cust_id, h.driver_name, h.track_id,
                    h.track_name, h.car_name, h.series_name, h.session_date,
                    h.sof, h.field_size, h.start_position,
                    h.finish_position, h.incidents, h.irating_old,
                    h.irating_new, ibt_file_path,
                    json.dumps(narrative.to_dict()), self._now(),
                ),
            )

    def get_race(
        self, subsession_id: int, cust_id: int
    ) -> RaceNarrative | None:
        """Return the stored narrative for a (subsession, driver) pair."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT narrative_json FROM races "
                "WHERE subsession_id = ? AND cust_id = ?",
                (subsession_id, cust_id),
            ).fetchone()
        if row is None:
            return None
        return RaceNarrative.from_dict(json.loads(row["narrative_json"]))

    def get_narratives(self, cust_id: int) -> list[RaceNarrative]:
        """All stored narratives for one driver, newest first.

        Dozens of rows at most for a personal store — loading them all is
        the profile engine's intended access pattern (derive on demand).
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT narrative_json FROM races "
                "WHERE cust_id = ? "
                "ORDER BY created_at DESC, subsession_id DESC",
                (cust_id,),
            ).fetchall()
        return [
            RaceNarrative.from_dict(json.loads(r["narrative_json"]))
            for r in rows
        ]

    def list_races(self) -> list[StoredRaceMeta]:
        """Scalar metadata for all stored races, newest first."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT subsession_id, cust_id, driver_name, track_name,
                       car, series_name, session_date, sof,
                       start_position, finish_position, incidents,
                       irating_old, irating_new, created_at
                FROM races ORDER BY created_at DESC
                """
            ).fetchall()
        return [
            StoredRaceMeta(
                subsession_id=r["subsession_id"],
                cust_id=r["cust_id"],
                driver_name=r["driver_name"] or "",
                track_name=r["track_name"] or "",
                car=r["car"] or "",
                series_name=r["series_name"] or "",
                session_date=r["session_date"] or "",
                sof=r["sof"] or 0,
                start_position=r["start_position"] or 0,
                finish_position=r["finish_position"] or 0,
                incidents=r["incidents"] or 0,
                irating_delta=(r["irating_new"] or 0) - (r["irating_old"] or 0),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def save_debrief(
        self, subsession_id: int, cust_id: int, text: str, model: str
    ) -> None:
        """Insert or replace the AI debrief text for a race."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO debriefs (
                    subsession_id, cust_id, debrief_text, model, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (subsession_id, cust_id, text, model, self._now()),
            )

    def get_debrief(self, subsession_id: int, cust_id: int) -> str | None:
        """Return stored AI debrief text, or None if none saved yet."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT debrief_text FROM debriefs "
                "WHERE subsession_id = ? AND cust_id = ?",
                (subsession_id, cust_id),
            ).fetchone()
        return row["debrief_text"] if row else None

    def append_chat_message(
        self, subsession_id: int, cust_id: int, role: str, content: str
    ) -> None:
        """Append one message to the follow-up chat transcript."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO chat_messages (
                    subsession_id, cust_id, role, content, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (subsession_id, cust_id, role, content, self._now()),
            )

    def get_chat(self, subsession_id: int, cust_id: int) -> list[dict]:
        """Chat transcript in insertion order as role/content dicts."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT role, content FROM chat_messages "
                "WHERE subsession_id = ? AND cust_id = ? ORDER BY id",
                (subsession_id, cust_id),
            ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in rows]
