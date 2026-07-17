"""Prescription seed table — the week plan's future input contract."""

import dataclasses

import pytest

from core.live.nudges import FaultKind
from core.profile.prescriptions import PRESCRIPTIONS, Prescription
from core.profile.render import FAULT_LABELS


class TestPrescriptions:
    def test_seeded_with_six_to_ten_rows(self):
        assert 6 <= len(PRESCRIPTIONS) <= 10

    def test_every_fault_is_a_real_fault_kind(self):
        valid = {k.value for k in FaultKind}
        for p in PRESCRIPTIONS:
            assert p.fault in valid, p

    def test_rows_are_complete(self):
        for p in PRESCRIPTIONS:
            assert p.combo and p.skill_line and p.transfer_line

    def test_rows_are_frozen(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            PRESCRIPTIONS[0].fault = "braking"

    def test_capability_framed_never_scolding(self):
        for p in PRESCRIPTIONS:
            text = (p.skill_line + " " + p.transfer_line).lower()
            assert "you're bad" not in text
            assert "you are bad" not in text


    def test_skill_lines_compose_after_it(self):
        """The week-plan render composes 'it {skill_line}.' — every
        line must open with a third-person verb. Extend the set
        deliberately when authoring new rows."""
        verbs = {"teaches", "forces", "rewards", "demands", "builds"}
        for p in PRESCRIPTIONS:
            assert p.skill_line.split()[0] in verbs, p.combo


class TestFaultLabels:
    def test_public_labels_cover_every_fault_kind(self):
        assert set(FAULT_LABELS) == {k.value for k in FaultKind}
