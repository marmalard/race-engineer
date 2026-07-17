"""Curated combo prescriptions (spec §8) — a knowledge layer, not data mining.

Each row names a combo that TEACHES a fault-ladder skill and what that
skill transfers to (v3 transfer principle: hard cars teach skills that
transfer DOWN). Capability-framed, never scolding — tone is part of the
contract. Grows by hand. No consumer in this phase: the week-plan build
reads it later; this file is its input contract.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Prescription:
    fault: str            # FaultKind.value it teaches
    combo: str            # human name, e.g. "Porsche 992 Cup at Spa"
    skill_line: str       # what practicing this combo builds
    transfer_line: str    # where the skill pays off elsewhere


PRESCRIPTIONS: tuple[Prescription, ...] = (
    Prescription(
        fault="release",
        combo="Porsche 992 Cup at Spa",
        skill_line=(
            "teaches trail-brake bite — the car rotates on release into "
            "Les Combes and the Bus Stop, so your left foot learns to steer"
        ),
        transfer_line=(
            "sharper release control transfers to every heavy-braking "
            "corner in every car you drive"
        ),
    ),
    Prescription(
        fault="throttle",
        combo="Porsche 992 Cup at Spa",
        skill_line=(
            "forces throttle discipline through Eau Rouge and Pouhon — "
            "early throttle here is a spin, not a tenth"
        ),
        transfer_line="unlocks every high-speed commitment corner",
    ),
    Prescription(
        fault="braking",
        combo="BMW M2 at Spa",
        skill_line=(
            "rewards patient brake points — the M2 telegraphs its weight "
            "transfer, so you can feel the limit build instead of guessing"
        ),
        transfer_line=(
            "calibrated brake points carry up to faster machinery where "
            "the window is smaller"
        ),
    ),
    Prescription(
        fault="release",
        combo="BMW M2 at Bathurst",
        skill_line=(
            "teaches weight management across the Mountain — release "
            "timing is what sets the car through Skyline and the Dipper"
        ),
        transfer_line=(
            "elevation-change composure transfers to any track that "
            "moves under you"
        ),
    ),
    Prescription(
        fault="lift",
        combo="Formula 4 at Road America",
        skill_line=(
            "a momentum car on a flowing track — carrying apex speed "
            "through the Carousel IS the lap time"
        ),
        transfer_line=(
            "apex-speed trust built here shows up in every momentum "
            "corner, tin-tops included"
        ),
    ),
    Prescription(
        fault="exit_speed",
        combo="Formula 4 at Road America",
        skill_line=(
            "long straights amplify every exit — the stopwatch teaches "
            "exit-first priority by itself"
        ),
        transfer_line=(
            "exit-first thinking pays on every straight-after-corner on "
            "the calendar"
        ),
    ),
    Prescription(
        fault="braking",
        combo="Porsche 992 Cup at Bathurst",
        skill_line=(
            "the Chase demands absolute brake-point precision — there is "
            "no runoff to hide a long one"
        ),
        transfer_line=(
            "precision under commitment transfers down to every car with "
            "more margin"
        ),
    ),
    Prescription(
        fault="throttle",
        combo="BMW M2 at Road America",
        skill_line=(
            "teaches progressive throttle out of Canada Corner and Turn 5 "
            "— patience converts directly to drive off the corner"
        ),
        transfer_line="throttle patience is the cheapest lap time in any RWD car",
    ),
)
