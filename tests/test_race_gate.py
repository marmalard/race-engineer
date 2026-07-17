"""Race persistence gate: session-type detection + fault streaks."""

from core.live.nudges import FaultKind
from core.live.race_gate import (
    RACE_STREAK_MIN,
    FaultStreakTracker,
    current_session_type,
    gate_diagnoses,
)
from tests.test_nudges import _diag


SESSION_INFO = {"Sessions": [
    {"SessionNum": 0, "SessionType": "Practice"},
    {"SessionNum": 1, "SessionType": "Lone Qualify"},
    {"SessionNum": 2, "SessionType": "Race"},
]}


class TestCurrentSessionType:
    def test_finds_session_by_num(self):
        assert current_session_type(SESSION_INFO, 2) == "Race"
        assert current_session_type(SESSION_INFO, 0) == "Practice"

    def test_unknown_num_or_malformed_info_is_empty(self):
        assert current_session_type(SESSION_INFO, 9) == ""
        assert current_session_type({}, 0) == ""
        assert current_session_type(None, 0) == ""


class TestFaultStreakTracker:
    def test_streak_builds_over_consecutive_laps(self):
        t = FaultStreakTracker()
        t.update({("Eau Rouge", FaultKind.BRAKING)})
        assert t.streak("Eau Rouge", FaultKind.BRAKING) == 1
        t.update({("Eau Rouge", FaultKind.BRAKING)})
        assert t.streak("Eau Rouge", FaultKind.BRAKING) == 2

    def test_missing_lap_resets_streak(self):
        t = FaultStreakTracker()
        t.update({("Eau Rouge", FaultKind.BRAKING)})
        t.update(set())  # clean lap at Eau Rouge
        assert t.streak("Eau Rouge", FaultKind.BRAKING) == 0

    def test_fault_kind_change_is_a_new_streak(self):
        t = FaultStreakTracker()
        t.update({("Eau Rouge", FaultKind.BRAKING)})
        t.update({("Eau Rouge", FaultKind.LIFT)})
        assert t.streak("Eau Rouge", FaultKind.BRAKING) == 0
        assert t.streak("Eau Rouge", FaultKind.LIFT) == 1


class TestGateDiagnoses:
    def _tracker_with_streak(self, n):
        t = FaultStreakTracker()
        for _ in range(n):
            # _diag() default label is "Eau Rouge"; braking=-15.0 → BRAKING primary
            t.update({("Eau Rouge", FaultKind.BRAKING)})
        return t

    def test_practice_passes_everything_through(self):
        diags = [_diag(braking=-15.0)]
        out = gate_diagnoses(diags, mode="persistent", is_race=False,
                             tracker=FaultStreakTracker())
        assert out == diags

    def test_race_persistent_needs_streak(self):
        diags = [_diag(braking=-15.0)]
        below = self._tracker_with_streak(RACE_STREAK_MIN - 1)
        at = self._tracker_with_streak(RACE_STREAK_MIN)
        assert gate_diagnoses(diags, mode="persistent", is_race=True,
                              tracker=below) == []
        assert gate_diagnoses(diags, mode="persistent", is_race=True,
                              tracker=at) == diags

    def test_race_off_silences_and_full_passes(self):
        diags = [_diag(braking=-15.0)]
        t = self._tracker_with_streak(5)
        assert gate_diagnoses(diags, mode="off", is_race=True, tracker=t) == []
        assert gate_diagnoses(diags, mode="full", is_race=True,
                              tracker=FaultStreakTracker()) == diags
