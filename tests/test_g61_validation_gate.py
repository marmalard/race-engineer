"""THE VALIDATION GATE: our numbers must reconcile with Garage 61.

G61 is the community gold standard for iRacing lap data. If our
pipeline disagrees with what G61 displays for the same lap, our
pipeline is wrong. This is a permanent fixture test, not a one-off.

Fixtures required (user-supplied, gitignored):
- tests/fixtures/g61/paired_session.ibt  — a real session's IBT file
- tests/fixtures/g61/paired_lap.csv      — G61 CSV export of a lap FROM
  THAT SAME SESSION (the driver's own lap, so both sources describe
  the identical physical lap)
- G61_DISPLAYED_LAP_TIME below — the lap time G61's UI shows for that lap
"""

from pathlib import Path

import numpy as np
import pytest

from core.benchmark.g61_import import import_g61_csv
from core.coaching.debrief import build_debrief
from core.telemetry.alignment import find_distance_offset
from core.telemetry.ibt_parser import IBTParser
from core.telemetry.normalizer import Normalizer

FIXTURES = Path(__file__).parent / "fixtures" / "g61"
IBT_FILE = FIXTURES / "paired_session.ibt"
CSV_FILE = FIXTURES / "paired_lap.csv"

# Values reported by the Garage 61 UI for the exported lap — fill in
# when fixtures are supplied; they make the gate meaningful.
G61_DISPLAYED_LAP_TIME = None  # e.g. 148.123 (seconds)

pytestmark = pytest.mark.skipif(
    not (IBT_FILE.exists() and CSV_FILE.exists()),
    reason="paired IBT + G61 fixtures not available",
)


@pytest.fixture(scope="module")
def ibt_best_lap():
    """Parse the paired IBT, normalize all laps, return the fastest valid one."""
    parser = IBTParser()
    ibt = parser.parse(IBT_FILE)
    track_length_m = ibt.session.track_length_km * 1000

    lap_dfs = parser.get_laps(ibt)
    # Build lap numbers from the Lap channel in each DataFrame
    lap_numbers = [int(df["Lap"].iloc[0]) for df in lap_dfs]

    normalizer = Normalizer(distance_interval=1.0)
    laps = normalizer.normalize_session(lap_dfs, lap_numbers, track_length_m)

    valid = [l for l in laps if l.is_valid]
    assert valid, "no valid laps in paired_session.ibt"
    return min(valid, key=lambda l: l.lap_time)


@pytest.fixture(scope="module")
def g61_lap(ibt_best_lap):
    """Load the G61 CSV export, resampled to the same distance grid."""
    with open(CSV_FILE) as f:
        return import_g61_csv(f, track_length_m=ibt_best_lap.track_length)


def test_g61_lap_time_matches_displayed(g61_lap):
    """G61 CSV elapsed time must match what the G61 UI displayed for this lap."""
    if G61_DISPLAYED_LAP_TIME is None:
        pytest.skip("G61 displayed lap time not recorded yet")
    assert g61_lap.lap_time == pytest.approx(G61_DISPLAYED_LAP_TIME, abs=0.2)


def test_same_lap_from_both_sources_agrees(ibt_best_lap, g61_lap):
    """The exported G61 lap IS one of our IBT laps: deltas must be ~zero."""
    # Lap times agree (same physical lap, same start/finish crossing)
    assert g61_lap.lap_time == pytest.approx(ibt_best_lap.lap_time, abs=0.3)

    # Alignment offset is small (a few meters, not tens)
    offset = find_distance_offset(ibt_best_lap.speed, g61_lap.speed)
    assert abs(offset) < 30

    # Full debrief of the lap against its own G61 export: total delta ~0
    result = build_debrief(ibt_best_lap, g61_lap, corners=[])
    assert abs(result.total_time_delta) < 0.3

    # Speed traces agree closely after alignment (m/s)
    n = min(len(ibt_best_lap.speed), len(g61_lap.speed))
    rms = float(np.sqrt(np.mean(
        (ibt_best_lap.speed[:n] - np.roll(g61_lap.speed[:n], -offset)) ** 2
    )))
    assert rms < 2.0, f"speed traces diverge, RMS={rms:.2f} m/s"


def test_no_phantom_loss_regions_for_same_lap(ibt_best_lap, g61_lap):
    """Comparing a lap to itself must not invent coaching priorities."""
    result = build_debrief(ibt_best_lap, g61_lap, corners=[])
    big_regions = [d for d in result.diagnoses if d.region.time_lost > 0.15]
    assert big_regions == [], (
        f"phantom losses comparing lap to itself: "
        f"{[(d.label, d.region.time_lost) for d in big_regions]}"
    )
