# core/weekplan/store.py
"""SQLite store for week plans (data/progression.db, week_plans table).

Plans are document-shaped -> stored as JSON (the races.db narrative_json
precedent). save() preserves created_at on re-save: a refresh updates
the artifact, it does not re-create it (one toast per week depends on
this distinction living in the store)."""

from dataclasses import asdict, fields
import json
from pathlib import Path
import sqlite3

from core.weekplan.models import (
    PlanSlot, PracticeHalf, RaceHalf, SRCheck, WeekPlan,
)

DEFAULT_DB_PATH = Path("data/progression.db")

_PLAN_FIELDS = {f.name for f in fields(WeekPlan)}
_RACE_FIELDS = {f.name for f in fields(RaceHalf)}
_PRACTICE_FIELDS = {f.name for f in fields(PracticeHalf)}
_SR_FIELDS = {f.name for f in fields(SRCheck)}
_SLOT_FIELDS = {f.name for f in fields(PlanSlot)}


def _filtered(d: dict, allowed: set[str]) -> dict:
    return {k: v for k, v in d.items() if k in allowed}


def _plan_from_json(raw: str) -> WeekPlan:
    """Tolerant reload: unknown keys dropped, missing keys defaulted."""
    d = json.loads(raw)
    race = d.get("race")
    practice = d.get("practice")
    sr = d.get("sr")
    kwargs = _filtered(d, _PLAN_FIELDS - {"race", "practice", "sr"})
    plan = WeekPlan(**kwargs)
    if isinstance(race, dict):
        slots = [
            PlanSlot(**_filtered(s, _SLOT_FIELDS))
            for s in race.get("slots") or []
            if isinstance(s, dict)
        ]
        rkw = _filtered(race, _RACE_FIELDS - {"slots"})
        plan.race = RaceHalf(**rkw, slots=slots)
    if isinstance(practice, dict):
        plan.practice = PracticeHalf(
            **_filtered(practice, _PRACTICE_FIELDS))
    if isinstance(sr, dict):
        plan.sr = SRCheck(**_filtered(sr, _SR_FIELDS))
    return plan


class WeekPlanStore:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS week_plans (
                    week_start TEXT PRIMARY KEY,
                    plan_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def save(self, plan: WeekPlan) -> None:
        """INSERT OR REPLACE; an existing week keeps its created_at."""
        existing = self.get(plan.week_start)
        if existing is not None:
            plan.created_at = existing.created_at
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO week_plans
                    (week_start, plan_json, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (plan.week_start, json.dumps(asdict(plan)),
                 plan.created_at, plan.updated_at),
            )

    def get(self, week_start: str) -> WeekPlan | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT plan_json FROM week_plans WHERE week_start = ?",
                (week_start,),
            ).fetchone()
        return _plan_from_json(row["plan_json"]) if row else None

    def latest(self) -> WeekPlan | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT plan_json FROM week_plans "
                "ORDER BY week_start DESC LIMIT 1"
            ).fetchone()
        return _plan_from_json(row["plan_json"]) if row else None

    def history(self) -> list[WeekPlan]:
        """All plans, newest week first (the page's history expander)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT plan_json FROM week_plans "
                "ORDER BY week_start DESC"
            ).fetchall()
        return [_plan_from_json(r["plan_json"]) for r in rows]
