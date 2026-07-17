"""Race-session persistence gate for approach cues + exit verdicts.

Pure — no pyirsdk, no I/O. In a Race session (mode 'persistent', the
default) a corner is only cued once its primary fault has persisted
RACE_STREAK_MIN consecutive laps: one scrappy corner while dicing stays
silent; a repeatable deficit gets flagged. Practice/qualifying behavior
is unchanged. Session type MUST come from SessionInfo's per-session
SessionType — WeekendInfo.EventType reads "Race" for practice sessions
on a race server (the pre-race-chunk lesson, 2026-07-15).
"""

from core.coaching.debrief import RegionDiagnosis
from core.live.nudges import FaultKind, fault_kinds_from_diagnosis

RACE_STREAK_MIN = 2
RACE_CUE_MODES = ("full", "persistent", "off")


def current_session_type(session_info: "dict | None", session_num: int) -> str:
    """SessionType string for the current SessionNum, or '' when unknown."""
    if not isinstance(session_info, dict):
        return ""
    for s in session_info.get("Sessions", []) or []:
        if isinstance(s, dict) and s.get("SessionNum") == session_num:
            return str(s.get("SessionType", "") or "")
    return ""


class FaultStreakTracker:
    """Consecutive-lap streaks per (corner label, primary FaultKind)."""

    def __init__(self) -> None:
        self._streaks: dict[tuple[str, FaultKind], int] = {}

    def update(self, lap_faults: "set[tuple[str, FaultKind]]") -> None:
        """Feed one completed lap's (label, primary fault) pairs."""
        self._streaks = {
            key: self._streaks.get(key, 0) + 1 for key in lap_faults
        }

    def streak(self, label: str, kind: FaultKind) -> int:
        return self._streaks.get((label, kind), 0)


def gate_diagnoses(
    diagnoses: list[RegionDiagnosis],
    *,
    mode: str,
    is_race: bool,
    tracker: FaultStreakTracker,
) -> list[RegionDiagnosis]:
    """The diagnoses allowed to cue this lap. Non-race sessions and mode
    'full' pass everything; 'off' silences races; 'persistent' requires
    the primary fault to have persisted RACE_STREAK_MIN laps."""
    if not is_race or mode == "full":
        return list(diagnoses)
    if mode == "off":
        return []
    allowed = []
    for d in diagnoses:
        kinds = fault_kinds_from_diagnosis(d)
        if kinds and tracker.streak(d.label, kinds[0]) >= RACE_STREAK_MIN:
            allowed.append(d)
    return allowed
