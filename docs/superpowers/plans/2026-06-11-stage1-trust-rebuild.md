# Stage 1: Trust Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace heuristic corner detection as the analysis foundation with reference-lap delta-trace loss regions, validated against Garage 61, with corner names from lovely-track-data and official track maps.

**Architecture:** A `ReferenceStore` holds one normalized reference lap per car/track combo (imported from Garage 61 CSV or promoted from the driver's own best). Debrief analysis aligns a driver lap to the reference via speed-trace cross-correlation, computes the cumulative time-delta trace, extracts loss regions (spans where delta grows), and annotates them with named corners from the track DB (seeded from lovely-track-data, 185 configs). Heuristic corner detection is no longer in the analysis path.

**Tech Stack:** Python 3.14, numpy/scipy/pandas, SQLite, pyirsdk (validation oracle), requests, Plotly, Streamlit (display only).

**Spec:** `docs/superpowers/specs/2026-06-11-reference-lap-redesign-design.md`

**Conventions for all tasks:**
- Test runner: `.venv/Scripts/python.exe -m pytest` (uv is not on PATH on this machine)
- Sign convention everywhere: `cum_delta = driver_elapsed - reference_elapsed`; **positive = driver is slower**
- `NormalizedLap` (in `core/telemetry/normalizer.py`) is the universal lap format; G61 imports produce it too
- All analysis in SI units (m/s, meters); conversion only at display time via `app/components/units.py`

**File structure created/modified by this plan:**

```
core/telemetry/alignment.py        # NEW: cross-correlation distance-offset correction
core/telemetry/loss_regions.py     # NEW: delta-trace loss region extraction
core/benchmark/g61_import.py       # NEW: Garage 61 CSV -> NormalizedLap
core/benchmark/reference_store.py  # NEW: SQLite store of reference laps per combo
core/track/lovely_seeder.py        # NEW: lovely-track-data corner seeding
core/track/segment_annotator.py    # NEW: label loss regions with corner names
core/track/track_assets.py         # NEW: official iRacing SVG map fetch + cache
core/coaching/debrief.py           # NEW: debrief orchestrator (replaces corner-detection path)
core/benchmark/iracing_api.py      # MODIFY: add get_track_assets()
app/components/track_map.py        # NEW: GPS outline plot colored by loss regions
app/pages/coaching.py              # MODIFY: reference import + debrief display
pyproject.toml                     # MODIFY: add pyirsdk to [dependency-groups] dev
tests/test_alignment.py            # NEW
tests/test_loss_regions.py         # NEW
tests/test_g61_import.py           # NEW
tests/test_reference_store.py      # NEW
tests/test_lovely_seeder.py        # NEW
tests/test_segment_annotator.py    # NEW
tests/test_track_assets.py         # NEW
tests/test_debrief.py              # NEW
tests/test_parser_cross_validation.py  # NEW: pyirsdk oracle
tests/test_g61_validation_gate.py  # NEW: real-data reconciliation (the trust contract)
```

---

### Task 1: pyirsdk cross-validation oracle for the IBT parser

Permanently de-risks the "IBT format varies" pitfall: assert our numpy-strided parser produces the same values as the reference implementation.

**Files:**
- Modify: `requirements.txt`
- Test: `tests/test_parser_cross_validation.py`

- [ ] **Step 1: Add pyirsdk to requirements and install**

Append to `requirements.txt`:

```
pyirsdk>=1.3.6
```

Run: `.venv/Scripts/python.exe -m pip install pyirsdk`
Expected: successful install (pure Python, only PyYAML dependency).

- [ ] **Step 2: Write the cross-validation test**

Create `tests/test_parser_cross_validation.py`:

```python
"""Cross-validate our IBT parser against pyirsdk's reference implementation.

pyirsdk is the canonical Python iRacing SDK. If our numpy-strided parser
and pyirsdk disagree on channel values, our parser is wrong.
"""

from pathlib import Path

import numpy as np
import pytest

from core.telemetry.ibt_parser import IBTParser

FIXTURE = Path(__file__).parent / "fixtures" / "sample.ibt"

# Channels our parser extracts that pyirsdk can also read
CHANNELS = ["Speed", "Throttle", "Brake", "LapDist", "Lap", "RPM", "Gear"]

pytestmark = pytest.mark.skipif(
    not FIXTURE.exists(), reason="sample.ibt fixture not available"
)


@pytest.fixture(scope="module")
def our_channels() -> dict[str, np.ndarray]:
    ibt = IBTParser().parse(FIXTURE)
    return {ch: ibt.telemetry[ch].to_numpy() for ch in CHANNELS}


@pytest.fixture(scope="module")
def pyirsdk_channels() -> dict[str, list]:
    irsdk = pytest.importorskip("irsdk")
    ibt = irsdk.IBT()
    ibt.open(str(FIXTURE))
    try:
        return {ch: ibt.get_all(ch) for ch in CHANNELS}
    finally:
        ibt.close()


@pytest.mark.parametrize("channel", CHANNELS)
def test_channel_matches_pyirsdk(channel, our_channels, pyirsdk_channels):
    ours = our_channels[channel]
    theirs = np.asarray(pyirsdk_channels[channel])
    assert len(ours) == len(theirs), (
        f"{channel}: sample count mismatch {len(ours)} vs {len(theirs)}"
    )
    np.testing.assert_allclose(
        ours.astype(np.float64),
        theirs.astype(np.float64),
        rtol=1e-6,
        atol=1e-6,
        err_msg=f"{channel} values diverge from pyirsdk",
    )
```

Note: if `ibt.telemetry` is not the actual attribute name on `IBTFile`, check `core/telemetry/ibt_parser.py:120` (the `IBTFile` dataclass) and use the DataFrame attribute it actually defines — do not change the parser, change the test.

- [ ] **Step 3: Run the test**

Run: `.venv/Scripts/python.exe -m pytest tests/test_parser_cross_validation.py -v`
Expected: 7 PASS (or 7 SKIP if no fixture on this machine). If any channel FAILS, **stop and investigate the parser** — that is the point of this task. Diagnose with `superpowers:systematic-debugging` before proceeding.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt tests/test_parser_cross_validation.py
git commit -m "test: cross-validate IBT parser against pyirsdk oracle"
```

---

### Task 2: Distance-offset alignment

G61's distance zero and iRacing's start/finish can disagree by meters; uncorrected, every braking-point delta is garbage. Cross-correlate speed traces, shift the reference.

**Files:**
- Create: `core/telemetry/alignment.py`
- Test: `tests/test_alignment.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_alignment.py`:

```python
"""Tests for distance-offset alignment between laps from different sources."""

import numpy as np
import pytest

from core.telemetry.alignment import find_distance_offset, shift_lap
from core.telemetry.normalizer import NormalizedLap


def _make_lap(speed: np.ndarray, track_length: float = 1000.0) -> NormalizedLap:
    n = len(speed)
    distance = np.arange(n, dtype=float)
    # elapsed time consistent with speed: dt = ds / v
    dt = 1.0 / np.maximum(speed, 1.0)
    return NormalizedLap(
        lap_number=1,
        lap_time=float(dt.sum()),
        track_length=track_length,
        distance=distance,
        speed=speed,
        throttle=np.ones(n),
        brake=np.zeros(n),
        steering=np.zeros(n),
        gear=np.full(n, 4),
        rpm=np.full(n, 5000.0),
        lat=np.zeros(n),
        lon=np.zeros(n),
        elapsed_time=np.cumsum(dt),
        is_valid=True,
    )


def _speed_profile(n: int = 1000) -> np.ndarray:
    """Synthetic lap: two 'corners' (speed dips) on a fast lap."""
    x = np.arange(n, dtype=float)
    speed = np.full(n, 60.0)
    speed -= 35.0 * np.exp(-((x - 250.0) ** 2) / (2 * 40.0**2))
    speed -= 25.0 * np.exp(-((x - 700.0) ** 2) / (2 * 30.0**2))
    return speed


def test_zero_offset_for_identical_laps():
    speed = _speed_profile()
    assert find_distance_offset(speed, speed) == 0


def test_recovers_known_shift():
    speed = _speed_profile()
    shifted = np.roll(speed, 12)  # comparison trace shifted 12m forward
    assert find_distance_offset(speed, shifted) == 12


def test_recovers_negative_shift():
    speed = _speed_profile()
    shifted = np.roll(speed, -8)
    assert find_distance_offset(speed, shifted) == -8


def test_offset_search_is_bounded():
    speed = _speed_profile()
    shifted = np.roll(speed, 300)  # beyond max_offset window
    offset = find_distance_offset(speed, shifted, max_offset_m=150)
    assert abs(offset) <= 150


def test_shift_lap_realigns_speed():
    lap = _make_lap(np.roll(_speed_profile(), 12))
    shifted = shift_lap(lap, -12)
    np.testing.assert_allclose(shifted.speed, _speed_profile())


def test_shift_lap_keeps_elapsed_time_monotonic():
    lap = _make_lap(_speed_profile())
    shifted = shift_lap(lap, 12)
    assert np.all(np.diff(shifted.elapsed_time) > 0)
    # total lap time preserved
    assert shifted.elapsed_time[-1] == pytest.approx(lap.elapsed_time[-1], abs=1e-6)


def test_shift_zero_is_identity():
    lap = _make_lap(_speed_profile())
    shifted = shift_lap(lap, 0)
    np.testing.assert_allclose(shifted.speed, lap.speed)
    np.testing.assert_allclose(shifted.elapsed_time, lap.elapsed_time)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_alignment.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.telemetry.alignment'`

- [ ] **Step 3: Implement**

Create `core/telemetry/alignment.py`:

```python
"""Distance-offset alignment between laps from different sources.

Garage 61 CSVs and iRacing IBT files can disagree on where distance
zero is by several meters. Cross-correlating the speed traces finds
the best-fit offset; shifting the lap circularly (a lap is a loop)
corrects it. Without this, braking-point deltas are systematically wrong.
"""

from dataclasses import replace

import numpy as np

from core.telemetry.normalizer import NormalizedLap


def find_distance_offset(
    reference_speed: np.ndarray,
    comparison_speed: np.ndarray,
    max_offset_m: float = 150.0,
    interval_m: float = 1.0,
) -> int:
    """Find the distance offset (in samples) that best aligns comparison to reference.

    Returns the lag such that np.roll(comparison, -lag) best matches reference.
    Positive lag means the comparison trace is shifted forward relative
    to the reference.
    """
    n = min(len(reference_speed), len(comparison_speed))
    ref = reference_speed[:n] - reference_speed[:n].mean()
    comp = comparison_speed[:n] - comparison_speed[:n].mean()

    max_lag = int(max_offset_m / interval_m)
    lags = np.arange(-max_lag, max_lag + 1)
    # Circular cross-correlation at each candidate lag (a lap is a loop)
    scores = np.array([np.dot(ref, np.roll(comp, -lag)) for lag in lags])
    return int(lags[int(np.argmax(scores))])


def shift_lap(lap: NormalizedLap, offset_samples: int) -> NormalizedLap:
    """Return a copy of the lap circularly shifted by offset_samples.

    elapsed_time is rebuilt from rolled per-sample time deltas so it
    stays monotonic (rolling a cumulative array directly would not be).
    """
    if offset_samples == 0:
        return lap

    def roll(arr: np.ndarray) -> np.ndarray:
        return np.roll(arr, offset_samples)

    dt = np.diff(lap.elapsed_time, prepend=lap.elapsed_time[0])
    dt[0] = lap.elapsed_time[0]
    rolled_dt = np.roll(dt, offset_samples)
    new_elapsed = np.cumsum(rolled_dt)

    return replace(
        lap,
        speed=roll(lap.speed),
        throttle=roll(lap.throttle),
        brake=roll(lap.brake),
        steering=roll(lap.steering),
        gear=roll(lap.gear),
        rpm=roll(lap.rpm),
        lat=roll(lap.lat),
        lon=roll(lap.lon),
        elapsed_time=new_elapsed,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_alignment.py -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add core/telemetry/alignment.py tests/test_alignment.py
git commit -m "feat: cross-correlation distance-offset alignment between laps"
```

---

### Task 3: Loss-region extraction from the delta trace

The new analysis primitive: contiguous spans where the cumulative time delta grows. Correct regardless of corner detection.

**Files:**
- Create: `core/telemetry/loss_regions.py`
- Test: `tests/test_loss_regions.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_loss_regions.py`:

```python
"""Tests for loss-region extraction from cumulative time-delta traces."""

import numpy as np

from core.telemetry.loss_regions import LossRegion, find_loss_regions


def _delta_with_losses(n: int = 2000) -> np.ndarray:
    """Synthetic cumulative delta: flat, then two distinct loss ramps."""
    delta = np.zeros(n)
    # Loss 1: 0.40s lost between 400m and 500m
    delta[400:500] += np.linspace(0, 0.40, 100)
    delta[500:] += 0.40
    # Loss 2: 0.15s lost between 1200m and 1260m
    delta[1200:1260] += np.linspace(0, 0.15, 60)
    delta[1260:] += 0.15
    return delta


def test_finds_both_loss_regions():
    distance = np.arange(2000, dtype=float)
    regions = find_loss_regions(_delta_with_losses(), distance)
    assert len(regions) == 2


def test_regions_sorted_by_time_lost_descending():
    distance = np.arange(2000, dtype=float)
    regions = find_loss_regions(_delta_with_losses(), distance)
    assert regions[0].time_lost >= regions[1].time_lost
    assert regions[0].time_lost == pytest.approx(0.40, abs=0.05)


def test_region_bounds_cover_the_ramp():
    distance = np.arange(2000, dtype=float)
    regions = find_loss_regions(_delta_with_losses(), distance)
    biggest = regions[0]
    assert biggest.distance_start <= 410
    assert biggest.distance_end >= 490


def test_no_regions_on_flat_delta():
    distance = np.arange(2000, dtype=float)
    assert find_loss_regions(np.zeros(2000), distance) == []


def test_gains_are_not_loss_regions():
    distance = np.arange(2000, dtype=float)
    delta = np.zeros(2000)
    delta[400:500] -= np.linspace(0, 0.5, 100)  # driver GAINS time
    delta[500:] -= 0.5
    assert find_loss_regions(delta, distance) == []


def test_tiny_losses_filtered():
    distance = np.arange(2000, dtype=float)
    delta = np.zeros(2000)
    delta[400:420] += np.linspace(0, 0.02, 20)  # below min_loss
    delta[420:] += 0.02
    assert find_loss_regions(delta, distance, min_loss_s=0.05) == []


def test_nearby_regions_merge():
    distance = np.arange(2000, dtype=float)
    delta = np.zeros(2000)
    # Two ramps separated by a 20m flat gap -> should merge (chicane case)
    delta[400:440] += np.linspace(0, 0.2, 40)
    delta[440:] += 0.2
    delta[460:500] += np.linspace(0, 0.2, 40)
    delta[500:] += 0.2
    regions = find_loss_regions(delta, distance, merge_gap_m=30.0)
    assert len(regions) == 1
    assert regions[0].time_lost == pytest.approx(0.4, abs=0.05)


import pytest  # noqa: E402  (used by approx above)
```

Move the `import pytest` to the top of the file with the other imports when writing it (shown at bottom here only to keep the diff narrative linear).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_loss_regions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.telemetry.loss_regions'`

- [ ] **Step 3: Implement**

Create `core/telemetry/loss_regions.py`:

```python
"""Loss-region extraction from cumulative time-delta traces.

The analysis primitive of the coaching debrief. Given the cumulative
time delta between a driver lap and a reference lap (positive = driver
slower), a loss region is a contiguous span of track where the delta
grows. Time lost per region is arithmetic on the trace — no corner
detection involved, so it cannot be wrong about *where* time was lost.
"""

from dataclasses import dataclass

import numpy as np
from scipy.signal import savgol_filter


@dataclass
class LossRegion:
    """A contiguous span of track where the driver loses time to the reference."""

    distance_start: float  # meters from start/finish
    distance_end: float
    time_lost: float  # seconds (always positive)


def find_loss_regions(
    cum_delta: np.ndarray,
    distance: np.ndarray,
    min_loss_s: float = 0.05,
    merge_gap_m: float = 30.0,
    smooth_window: int = 21,
    grow_threshold_s_per_m: float = 0.0005,
) -> list[LossRegion]:
    """Extract loss regions from a cumulative time-delta trace.

    Args:
        cum_delta: driver_elapsed - reference_elapsed at each distance point.
        distance: matching distance grid (uniform spacing assumed).
        min_loss_s: regions losing less than this are noise, dropped.
        merge_gap_m: adjacent regions closer than this merge (chicanes).
        smooth_window: Savitzky-Golay window for the gradient (odd).
        grow_threshold_s_per_m: minimum delta slope to count as "losing time".

    Returns:
        LossRegions sorted by time_lost descending.
    """
    n = min(len(cum_delta), len(distance))
    if n < smooth_window:
        return []
    delta = cum_delta[:n]
    dist = distance[:n]
    interval = float(dist[1] - dist[0]) if n > 1 else 1.0

    smoothed = savgol_filter(delta, smooth_window, 3)
    slope = np.gradient(smoothed, dist)
    losing = slope > grow_threshold_s_per_m

    # Contiguous True spans -> candidate regions
    edges = np.flatnonzero(np.diff(losing.astype(int)))
    starts = list(edges[losing[edges + 1]] + 1)
    ends = list(edges[~losing[edges + 1]] + 1)
    if losing[0]:
        starts.insert(0, 0)
    if losing[-1]:
        ends.append(n)

    spans = list(zip(starts, ends))

    # Merge spans separated by less than merge_gap_m
    merged: list[tuple[int, int]] = []
    gap_samples = int(merge_gap_m / interval)
    for start, end in spans:
        if merged and start - merged[-1][1] <= gap_samples:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))

    regions = []
    for start, end in merged:
        time_lost = float(delta[min(end, n - 1)] - delta[start])
        if time_lost >= min_loss_s:
            regions.append(
                LossRegion(
                    distance_start=float(dist[start]),
                    distance_end=float(dist[min(end, n - 1)]),
                    time_lost=time_lost,
                )
            )

    regions.sort(key=lambda r: r.time_lost, reverse=True)
    return regions
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_loss_regions.py -v`
Expected: 7 PASS. If `test_nearby_regions_merge` or bound assertions fail by small margins, tune `smooth_window`/`grow_threshold_s_per_m` defaults — the synthetic ramps are gentle; do NOT loosen the test bounds beyond ±10m.

- [ ] **Step 5: Commit**

```bash
git add core/telemetry/loss_regions.py tests/test_loss_regions.py
git commit -m "feat: loss-region extraction from cumulative delta trace"
```

---

### Task 4: Garage 61 CSV importer

**User checkpoint (before coding):** ask the user to export one lap CSV from Garage 61 (any combo they own, ideally Spa/BMW M2 CS to pair with `tests/fixtures/sample.ibt`) and save it to `tests/fixtures/g61/reference.csv`. Inspect its actual headers before finalizing `CHANNEL_ALIASES` — the alias table below is a starting point, not gospel.

**Files:**
- Create: `core/benchmark/g61_import.py`
- Test: `tests/test_g61_import.py`

- [ ] **Step 1: Obtain fixture and inspect headers**

Ask the user for the CSV (checkpoint above). Then run:

```powershell
.venv/Scripts/python.exe -c "import pandas as pd; df = pd.read_csv('tests/fixtures/g61/reference.csv', nrows=3); print(list(df.columns)); print(df.head(3))"
```

Record the exact column names. Update `CHANNEL_ALIASES` in Step 4 to include them. If the file has metadata rows before the header, note the row offset and add `skiprows=` handling.

- [ ] **Step 2: Write failing tests**

Create `tests/test_g61_import.py`:

```python
"""Tests for Garage 61 CSV import into NormalizedLap."""

from io import StringIO
from pathlib import Path

import numpy as np
import pytest

from core.benchmark.g61_import import G61ImportError, import_g61_csv
from core.telemetry.normalizer import NormalizedLap

FIXTURE = Path(__file__).parent / "fixtures" / "g61" / "reference.csv"

# Synthetic CSV in G61-like shape: 0.5m spacing, speed in km/h, pedals in %
def _synthetic_csv(n_rows: int = 4000, spacing: float = 0.5) -> StringIO:
    rows = ["Distance,Speed,Throttle,Brake,Gear,RPM,SteeringWheelAngle"]
    for i in range(n_rows):
        d = i * spacing
        speed_kmh = 200.0 - 100.0 * np.exp(-((d - 800) ** 2) / (2 * 60.0**2))
        brake = 80.0 if 700 <= d <= 780 else 0.0
        throttle = 0.0 if 700 <= d <= 850 else 100.0
        rows.append(f"{d},{speed_kmh},{throttle},{brake},4,6500,0.0")
    return StringIO("\n".join(rows))


def test_returns_normalized_lap_on_1m_grid():
    lap = import_g61_csv(_synthetic_csv(), track_length_m=2000.0)
    assert isinstance(lap, NormalizedLap)
    assert lap.distance[1] - lap.distance[0] == pytest.approx(1.0)
    assert lap.distance[-1] <= 2000.0


def test_speed_converted_to_ms():
    lap = import_g61_csv(_synthetic_csv(), track_length_m=2000.0)
    # 200 km/h = 55.6 m/s; if conversion is skipped values stay ~200
    assert lap.speed.max() == pytest.approx(200.0 / 3.6, abs=1.0)


def test_pedals_normalized_to_0_1():
    lap = import_g61_csv(_synthetic_csv(), track_length_m=2000.0)
    assert lap.brake.max() == pytest.approx(0.8, abs=0.05)
    assert lap.throttle.max() == pytest.approx(1.0, abs=0.05)


def test_elapsed_time_integrated_from_speed():
    lap = import_g61_csv(_synthetic_csv(), track_length_m=2000.0)
    assert np.all(np.diff(lap.elapsed_time) > 0)
    # Sanity: 2km at speeds between 100-200 km/h is ~40-70s
    assert 30.0 < lap.elapsed_time[-1] < 90.0
    assert lap.lap_time == pytest.approx(lap.elapsed_time[-1])


def test_unknown_columns_raise_with_found_headers():
    bad = StringIO("Foo,Bar\n1,2\n3,4")
    with pytest.raises(G61ImportError, match="Foo"):
        import_g61_csv(bad, track_length_m=2000.0)


@pytest.mark.skipif(not FIXTURE.exists(), reason="real G61 export not available")
def test_real_g61_export_imports():
    with open(FIXTURE) as f:
        lap = import_g61_csv(f, track_length_m=7004.0)  # Spa
    assert lap.is_valid
    assert 30.0 < lap.speed.max() < 100.0  # plausible m/s for a race car
    assert 100.0 < lap.lap_time < 200.0  # plausible Spa lap
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_g61_import.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.benchmark.g61_import'`

- [ ] **Step 4: Implement**

Create `core/benchmark/g61_import.py` (adjust `CHANNEL_ALIASES` per Step 1 findings):

```python
"""Import a Garage 61 lap CSV export into a NormalizedLap.

G61 exports vary in column naming, units (km/h vs m/s, percent vs 0-1
pedals), and sample spacing. This module maps columns by alias table,
detects units heuristically, and resamples onto the same 1m distance
grid the IBT pipeline uses — after this, comparison code cannot tell
where a lap came from.
"""

from typing import IO

import numpy as np
import pandas as pd

from core.telemetry.normalizer import NormalizedLap


class G61ImportError(Exception):
    """Raised when a CSV cannot be mapped to required channels."""


# Logical channel -> acceptable G61 column names (case-insensitive match).
# VERIFY against a real export before trusting; extend as needed.
CHANNEL_ALIASES: dict[str, list[str]] = {
    "distance": ["distance", "distance (m)", "lapdist", "lap distance", "dist"],
    "speed": ["speed", "speed (km/h)", "speed (m/s)", "speed kmh", "ground speed"],
    "throttle": ["throttle", "throttle (%)", "throttle pos", "rpedal"],
    "brake": ["brake", "brake (%)", "brake pos", "brake pressure"],
    "gear": ["gear"],
    "rpm": ["rpm", "engine rpm"],
    "steering": ["steeringwheelangle", "steering", "steering angle", "steer"],
    "time": ["time", "lap time", "currentlaptime", "elapsed time", "time (s)"],
    "lat": ["lat", "latitude", "gps lat"],
    "lon": ["lon", "long", "longitude", "gps lon"],
}

REQUIRED = ["distance", "speed"]


def _map_columns(df: pd.DataFrame) -> dict[str, str]:
    lower_cols = {c.lower().strip(): c for c in df.columns}
    mapping: dict[str, str] = {}
    for logical, aliases in CHANNEL_ALIASES.items():
        for alias in aliases:
            if alias in lower_cols:
                mapping[logical] = lower_cols[alias]
                break
    missing = [ch for ch in REQUIRED if ch not in mapping]
    if missing:
        raise G61ImportError(
            f"Could not find required channels {missing} in CSV. "
            f"Found columns: {list(df.columns)}. "
            f"Add the actual names to CHANNEL_ALIASES in g61_import.py."
        )
    return mapping


def import_g61_csv(
    source: IO | str,
    track_length_m: float,
    distance_interval: float = 1.0,
) -> NormalizedLap:
    """Parse a Garage 61 lap CSV and resample to the standard distance grid."""
    df = pd.read_csv(source)
    cols = _map_columns(df)

    raw_dist = df[cols["distance"]].to_numpy(dtype=float)
    raw_speed = df[cols["speed"]].to_numpy(dtype=float)

    # Unit detection: no car reaches 130 m/s; km/h values for race cars do exceed it
    if np.nanmax(raw_speed) > 130.0:
        raw_speed = raw_speed / 3.6

    def channel(name: str, default: float = 0.0) -> np.ndarray:
        if name in cols:
            return df[cols[name]].to_numpy(dtype=float)
        return np.full(len(df), default)

    raw_throttle = channel("throttle")
    raw_brake = channel("brake")
    # Pedal unit detection: percent scale -> 0-1
    if np.nanmax(raw_throttle) > 1.5:
        raw_throttle = raw_throttle / 100.0
    if np.nanmax(raw_brake) > 1.5:
        raw_brake = raw_brake / 100.0

    # Drop duplicate / non-increasing distance samples (interp requires monotonic x)
    keep = np.concatenate([[True], np.diff(raw_dist) > 0])
    raw_dist = raw_dist[keep]

    def kept(arr: np.ndarray) -> np.ndarray:
        return arr[keep]

    grid = np.arange(0.0, min(track_length_m, raw_dist[-1]), distance_interval)

    def resample(arr: np.ndarray) -> np.ndarray:
        return np.interp(grid, raw_dist, arr)

    speed = resample(kept(raw_speed))

    if "time" in cols:
        raw_time = kept(df[cols["time"]].to_numpy(dtype=float))
        elapsed = resample(raw_time - raw_time[0])
    else:
        # Integrate dt = ds / v over the grid
        dt = distance_interval / np.maximum(speed, 1.0)
        elapsed = np.cumsum(dt)

    return NormalizedLap(
        lap_number=0,
        lap_time=float(elapsed[-1]),
        track_length=track_length_m,
        distance=grid,
        speed=speed,
        throttle=resample(kept(raw_throttle)),
        brake=resample(kept(raw_brake)),
        steering=resample(kept(channel("steering"))),
        gear=np.round(resample(kept(channel("gear", 0.0)))).astype(int),
        rpm=resample(kept(channel("rpm"))),
        lat=resample(kept(channel("lat"))),
        lon=resample(kept(channel("lon"))),
        elapsed_time=elapsed,
        is_valid=True,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_g61_import.py -v`
Expected: 5 PASS + 1 PASS or SKIP (real fixture). If the real-fixture test fails, the alias table or unit detection needs the actual export's reality — fix the importer, not the test.

- [ ] **Step 6: Commit**

```bash
git add core/benchmark/g61_import.py tests/test_g61_import.py
git commit -m "feat: Garage 61 CSV import to NormalizedLap"
```

---

### Task 5: Reference lap store

**Files:**
- Create: `core/benchmark/reference_store.py`
- Test: `tests/test_reference_store.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_reference_store.py`:

```python
"""Tests for the reference lap store."""

from pathlib import Path

import numpy as np
import pytest

from core.benchmark.reference_store import ReferenceStore
from core.telemetry.normalizer import NormalizedLap


def _lap(lap_time: float = 100.0, n: int = 500) -> NormalizedLap:
    return NormalizedLap(
        lap_number=0,
        lap_time=lap_time,
        track_length=float(n),
        distance=np.arange(n, dtype=float),
        speed=np.full(n, 50.0),
        throttle=np.ones(n),
        brake=np.zeros(n),
        steering=np.zeros(n),
        gear=np.full(n, 4),
        rpm=np.full(n, 6000.0),
        lat=np.zeros(n),
        lon=np.zeros(n),
        elapsed_time=np.linspace(0, lap_time, n),
        is_valid=True,
    )


@pytest.fixture
def store(tmp_path: Path) -> ReferenceStore:
    return ReferenceStore(tmp_path / "refs.db")


def test_save_and_get_roundtrip(store):
    store.save("523", "BMW M2 CS Racing", _lap(), source="g61")
    ref = store.get("523", "BMW M2 CS Racing")
    assert ref is not None
    assert ref.source == "g61"
    np.testing.assert_allclose(ref.lap.speed, _lap().speed)
    assert ref.lap.lap_time == pytest.approx(100.0)


def test_get_missing_returns_none(store):
    assert store.get("999", "Nonexistent Car") is None


def test_g61_preferred_over_personal_best(store):
    store.save("523", "BMW M2 CS Racing", _lap(lap_time=99.0), source="personal_best")
    store.save("523", "BMW M2 CS Racing", _lap(lap_time=101.0), source="g61")
    ref = store.get("523", "BMW M2 CS Racing")
    assert ref.source == "g61"


def test_save_same_source_overwrites(store):
    store.save("523", "BMW M2 CS Racing", _lap(lap_time=100.0), source="g61")
    store.save("523", "BMW M2 CS Racing", _lap(lap_time=98.0), source="g61")
    ref = store.get("523", "BMW M2 CS Racing")
    assert ref.lap.lap_time == pytest.approx(98.0)
    assert len(store.list_all()) == 1


def test_list_all_metadata(store):
    store.save("523", "BMW M2 CS Racing", _lap(), source="g61", driver_name="A. Fast")
    entries = store.list_all()
    assert len(entries) == 1
    assert entries[0].track_id == "523"
    assert entries[0].car == "BMW M2 CS Racing"
    assert entries[0].driver_name == "A. Fast"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_reference_store.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

Create `core/benchmark/reference_store.py`:

```python
"""SQLite store of reference laps, one per car/track combo per source.

The reference lap is the data spine of the redesign: the briefing
decomposes it, the debrief diffs against it. Sources: 'g61' (imported
Garage 61 lap, preferred) or 'personal_best' (promoted from the
driver's own sessions, fallback).
"""

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
    ref_id: int
    track_id: str
    car: str
    source: str  # 'g61' | 'personal_best'
    lap_time: float
    driver_name: str | None
    imported_at: str


@dataclass
class ReferenceLap:
    meta: ReferenceLapMeta
    lap: NormalizedLap

    @property
    def source(self) -> str:
        return self.meta.source


class ReferenceStore:
    """CRUD for reference laps."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reference_laps (
                    ref_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    track_id TEXT NOT NULL,
                    car TEXT NOT NULL,
                    source TEXT NOT NULL,
                    lap_time REAL NOT NULL,
                    track_length REAL NOT NULL,
                    driver_name TEXT,
                    imported_at TEXT NOT NULL,
                    channels BLOB NOT NULL,
                    UNIQUE(track_id, car, source)
                )
            """)

    def save(
        self,
        track_id: str,
        car: str,
        lap: NormalizedLap,
        source: str,
        driver_name: str | None = None,
    ) -> None:
        buf = io.BytesIO()
        np.savez_compressed(buf, **{f: getattr(lap, f) for f in ARRAY_FIELDS})
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO reference_laps
                    (track_id, car, source, lap_time, track_length,
                     driver_name, imported_at, channels)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(track_id, car, source) DO UPDATE SET
                    lap_time=excluded.lap_time,
                    track_length=excluded.track_length,
                    driver_name=excluded.driver_name,
                    imported_at=excluded.imported_at,
                    channels=excluded.channels
                """,
                (
                    track_id, car, source, lap.lap_time, lap.track_length,
                    driver_name, datetime.now(timezone.utc).isoformat(),
                    buf.getvalue(),
                ),
            )

    def get(self, track_id: str, car: str) -> ReferenceLap | None:
        """Best available reference for the combo: g61 preferred."""
        with self._conn() as conn:
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
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM reference_laps ORDER BY track_id, car"
            ).fetchall()
        return [self._meta(r) for r in rows]

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
        arrays = np.load(io.BytesIO(row["channels"]))
        return NormalizedLap(
            lap_number=0,
            lap_time=row["lap_time"],
            track_length=row["track_length"],
            is_valid=True,
            **{f: arrays[f] for f in ARRAY_FIELDS},
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_reference_store.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add core/benchmark/reference_store.py tests/test_reference_store.py
git commit -m "feat: SQLite reference lap store with g61/personal_best sources"
```

---

### Task 6: lovely-track-data corner seeder

185 iRacing track configs with named corner ranges as track-position fractions. Track IDs align with the directory naming we already read from IBT session YAML ("spa 2024 up" → `spa-2024-up`).

**Files:**
- Create: `core/track/lovely_seeder.py`
- Test: `tests/test_lovely_seeder.py`

- [ ] **Step 1: Inspect the real data shape once**

Run:

```powershell
.venv/Scripts/python.exe -c "import requests; r = requests.get('https://raw.githubusercontent.com/Lovely-Sim-Racing/lovely-track-data/main/data/iracing/spa-2024-up.json', timeout=30); print(r.status_code); print(r.text[:1500])"
```

Record the actual top-level keys (expected: track metadata plus a turns/corners list with `start`/`end` fractions and `name`). If the URL 404s, fetch `https://raw.githubusercontent.com/Lovely-Sim-Racing/lovely-track-data/main/data/manifest.json` and locate the correct path scheme. Adjust the parsing code in Step 4 and the sample JSON in the test to the **real** shape before proceeding.

- [ ] **Step 2: Write failing tests**

Create `tests/test_lovely_seeder.py` (sample JSON below matches what Step 1 found — update if reality differs):

```python
"""Tests for lovely-track-data corner seeding."""

from pathlib import Path
from unittest.mock import patch

import pytest

from core.track.lovely_seeder import (
    lovely_track_slug,
    parse_lovely_corners,
    seed_track_from_lovely,
)
from core.track.models import Track, TrackType
from core.track.track_db import TrackDB

SAMPLE_LOVELY_JSON = {
    "name": "Circuit de Spa-Francorchamps",
    "length": 7004,
    "turns": [
        {"start": 0.005, "end": 0.025, "name": "La Source"},
        {"start": 0.138, "end": 0.155, "name": "Eau Rouge"},
        {"start": 0.155, "end": 0.175, "name": "Raidillon"},
    ],
}


def test_slug_from_ibt_track_name():
    assert lovely_track_slug("spa 2024 up") == "spa-2024-up"
    assert lovely_track_slug("roadamerica full") == "roadamerica-full"
    assert lovely_track_slug("monza combinedchicanes") == "monza-combinedchicanes"


def test_parse_corners_converts_fractions_to_meters():
    corners = parse_lovely_corners(SAMPLE_LOVELY_JSON, track_id="523",
                                   track_length_m=7004.0)
    assert len(corners) == 3
    eau_rouge = corners[1]
    assert eau_rouge.name == "Eau Rouge"
    assert eau_rouge.distance_start_meters == pytest.approx(0.138 * 7004, abs=1.0)
    assert eau_rouge.distance_end_meters == pytest.approx(0.155 * 7004, abs=1.0)
    assert eau_rouge.track_id == "523"


def test_corners_numbered_sequentially_by_position():
    corners = parse_lovely_corners(SAMPLE_LOVELY_JSON, track_id="523",
                                   track_length_m=7004.0)
    assert [c.corner_number for c in corners] == [1, 2, 3]


def test_seed_track_upserts_into_db(tmp_path: Path):
    db = TrackDB(tmp_path / "tracks.db")
    db.upsert_track(Track(
        track_id="523", name="Spa", config="Grand Prix",
        length_meters=7004.0, track_type=TrackType.ROAD, character=None,
    ))
    with patch("core.track.lovely_seeder._fetch_lovely_json",
               return_value=SAMPLE_LOVELY_JSON):
        count = seed_track_from_lovely(db, track_id="523",
                                       ibt_track_name="spa 2024 up",
                                       track_length_m=7004.0)
    assert count == 3
    names = [c.name for c in db.get_corners("523")]
    assert "Eau Rouge" in names


def test_seed_missing_track_returns_zero(tmp_path: Path):
    db = TrackDB(tmp_path / "tracks.db")
    with patch("core.track.lovely_seeder._fetch_lovely_json", return_value=None):
        count = seed_track_from_lovely(db, track_id="999",
                                       ibt_track_name="notreal track",
                                       track_length_m=1000.0)
    assert count == 0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_lovely_seeder.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Implement**

Create `core/track/lovely_seeder.py` (adjust key names to Step 1 reality):

```python
"""Seed corner names from lovely-track-data (Lovely-Sim-Racing on GitHub).

Covers ~185 iRacing track configs (vs ~30 from Crew Chief) with named
corner ranges as track-position fractions (0-1). License: CC BY-NC-SA 4.0
(non-commercial, attribution) — fine for this personal tool.

Track slugs align with iRacing's track directory naming, which we already
extract from IBT session YAML: "spa 2024 up" -> "spa-2024-up".
"""

import logging

import requests

from core.track.models import Corner
from core.track.track_db import TrackDB

logger = logging.getLogger(__name__)

RAW_BASE = (
    "https://raw.githubusercontent.com/Lovely-Sim-Racing/"
    "lovely-track-data/main/data/iracing"
)


def lovely_track_slug(ibt_track_name: str) -> str:
    """Convert IBT session YAML track name to a lovely-track-data slug."""
    return ibt_track_name.strip().lower().replace(" ", "-")


def _fetch_lovely_json(slug: str) -> dict | None:
    """Fetch a track's JSON; None if absent or unreachable."""
    url = f"{RAW_BASE}/{slug}.json"
    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.warning("lovely-track-data fetch failed for %s: %s", slug, exc)
        return None


def parse_lovely_corners(
    data: dict, track_id: str, track_length_m: float
) -> list[Corner]:
    """Convert lovely turn entries (fractions) to Corner models (meters)."""
    turns = data.get("turns", [])
    corners = []
    for i, turn in enumerate(
        sorted(turns, key=lambda t: t.get("start", 0.0)), start=1
    ):
        name = turn.get("name")
        if name is None or "start" not in turn or "end" not in turn:
            continue
        corners.append(Corner(
            corner_id=None,
            track_id=track_id,
            corner_number=i,  # positional ordering, NOT official turn number
            name=name,
            distance_start_meters=turn["start"] * track_length_m,
            distance_end_meters=turn["end"] * track_length_m,
            corner_type=None,
        ))
    return corners


def seed_track_from_lovely(
    db: TrackDB,
    track_id: str,
    ibt_track_name: str,
    track_length_m: float,
) -> int:
    """Fetch and upsert lovely-track-data corners for a track.

    Returns the number of corners seeded (0 = no data / fetch failed;
    callers fall back to Crew Chief seeding, then heuristic detection).
    """
    data = _fetch_lovely_json(lovely_track_slug(ibt_track_name))
    if data is None:
        return 0
    corners = parse_lovely_corners(data, track_id, track_length_m)
    if not corners:
        return 0
    db.upsert_corners(track_id, corners)
    return len(corners)
```

- [ ] **Step 5: Run tests, then run a live smoke check**

Run: `.venv/Scripts/python.exe -m pytest tests/test_lovely_seeder.py -v`
Expected: 5 PASS

Live smoke check (network):

```powershell
.venv/Scripts/python.exe -c "from core.track.lovely_seeder import _fetch_lovely_json, parse_lovely_corners; d = _fetch_lovely_json('spa-2024-up'); print(len(parse_lovely_corners(d, '523', 7004.0)), 'corners'); print([c.name for c in parse_lovely_corners(d, '523', 7004.0)][:5])"
```

Expected: a plausible corner count (~19 for Spa) with real names. If keys differ from the sample, fix the parser AND the test sample JSON to match reality.

- [ ] **Step 6: Commit**

```bash
git add core/track/lovely_seeder.py tests/test_lovely_seeder.py
git commit -m "feat: seed corner names from lovely-track-data (185 iRacing configs)"
```

---

### Task 7: Loss-region annotation with corner names

**Files:**
- Create: `core/track/segment_annotator.py`
- Test: `tests/test_segment_annotator.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_segment_annotator.py`:

```python
"""Tests for annotating loss regions with corner names."""

from core.telemetry.loss_regions import LossRegion
from core.track.models import Corner
from core.track.segment_annotator import annotate_region


def _corner(name: str, start: float, end: float) -> Corner:
    return Corner(
        corner_id=None, track_id="523", corner_number=1, name=name,
        distance_start_meters=start, distance_end_meters=end, corner_type=None,
    )


CORNERS = [
    _corner("La Source", 35.0, 175.0),
    _corner("Eau Rouge", 966.0, 1086.0),
    _corner("Raidillon", 1086.0, 1226.0),
]


def test_region_inside_corner_gets_name():
    region = LossRegion(distance_start=1000.0, distance_end=1080.0, time_lost=0.3)
    assert annotate_region(region, CORNERS, track_length=7004.0) == "Eau Rouge"


def test_region_spanning_corners_joins_names():
    region = LossRegion(distance_start=1000.0, distance_end=1200.0, time_lost=0.5)
    assert annotate_region(region, CORNERS, track_length=7004.0) == (
        "Eau Rouge / Raidillon"
    )


def test_region_near_corner_within_tolerance():
    # Braking zone starts 40m before the corner's DB start
    region = LossRegion(distance_start=930.0, distance_end=960.0, time_lost=0.2)
    assert annotate_region(region, CORNERS, track_length=7004.0,
                           tolerance_m=50.0) == "Eau Rouge"


def test_region_far_from_any_corner_falls_back_to_position():
    region = LossRegion(distance_start=4400.0, distance_end=4500.0, time_lost=0.2)
    label = annotate_region(region, CORNERS, track_length=7004.0)
    assert "4.4 km" in label


def test_no_corners_at_all_falls_back_to_position():
    region = LossRegion(distance_start=1000.0, distance_end=1080.0, time_lost=0.3)
    label = annotate_region(region, [], track_length=7004.0)
    assert "1.0 km" in label
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_segment_annotator.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

Create `core/track/segment_annotator.py`:

```python
"""Annotate loss regions with corner names from the track database.

Corners are labels on the analysis, never its foundation: if no named
corner overlaps a loss region, the label degrades gracefully to a
position description rather than inventing a turn number.
"""

from core.telemetry.loss_regions import LossRegion
from core.track.models import Corner


def annotate_region(
    region: LossRegion,
    corners: list[Corner],
    track_length: float,
    tolerance_m: float = 50.0,
) -> str:
    """Human label for a loss region: corner name(s) or position fallback."""
    overlapping = [
        c for c in corners
        if c.name
        and c.distance_start_meters - tolerance_m <= region.distance_end
        and c.distance_end_meters + tolerance_m >= region.distance_start
    ]
    if overlapping:
        overlapping.sort(key=lambda c: c.distance_start_meters)
        return " / ".join(dict.fromkeys(c.name for c in overlapping))

    km = region.distance_start / 1000.0
    return f"~{km:.1f} km from start/finish"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_segment_annotator.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add core/track/segment_annotator.py tests/test_segment_annotator.py
git commit -m "feat: annotate loss regions with corner names, position fallback"
```

---

### Task 8: Debrief orchestrator

The new analysis path: align → delta → loss regions → annotate → per-region diagnosis. No corner detection.

**Files:**
- Create: `core/coaching/debrief.py`
- Test: `tests/test_debrief.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_debrief.py`:

```python
"""Tests for the debrief orchestrator (reference-lap delta analysis)."""

import numpy as np
import pytest

from core.coaching.debrief import DebriefAnalysis, RegionDiagnosis, build_debrief
from core.telemetry.normalizer import NormalizedLap
from core.track.models import Corner


def _lap(speed: np.ndarray, brake: np.ndarray | None = None,
         throttle: np.ndarray | None = None) -> NormalizedLap:
    n = len(speed)
    dt = 1.0 / np.maximum(speed, 1.0)
    return NormalizedLap(
        lap_number=1, lap_time=float(dt.sum()), track_length=float(n),
        distance=np.arange(n, dtype=float),
        speed=speed,
        throttle=throttle if throttle is not None else np.ones(n),
        brake=brake if brake is not None else np.zeros(n),
        steering=np.zeros(n), gear=np.full(n, 4), rpm=np.full(n, 6000.0),
        lat=np.zeros(n), lon=np.zeros(n),
        elapsed_time=np.cumsum(dt), is_valid=True,
    )


def _reference(n: int = 2000) -> NormalizedLap:
    x = np.arange(n, dtype=float)
    speed = np.full(n, 60.0)
    speed -= 35.0 * np.exp(-((x - 500.0) ** 2) / (2 * 50.0**2))  # corner at 500m
    brake = np.where((x > 380) & (x < 480), 0.8, 0.0)
    throttle = np.where((x > 380) & (x < 560), 0.0, 1.0)
    return _lap(speed, brake, throttle)


def _slower_driver(n: int = 2000) -> NormalizedLap:
    """Same lap but over-slows the corner and brakes 30m earlier."""
    x = np.arange(n, dtype=float)
    speed = np.full(n, 60.0)
    speed -= 42.0 * np.exp(-((x - 500.0) ** 2) / (2 * 55.0**2))  # deeper dip
    brake = np.where((x > 350) & (x < 480), 0.8, 0.0)  # brakes at 350 not 380
    throttle = np.where((x > 350) & (x < 580), 0.0, 1.0)
    return _lap(speed, brake, throttle)


CORNERS = [Corner(
    corner_id=None, track_id="t", corner_number=1, name="Test Hairpin",
    distance_start_meters=420.0, distance_end_meters=580.0, corner_type=None,
)]


def test_debrief_finds_the_loss_region():
    result = build_debrief(_slower_driver(), _reference(), CORNERS)
    assert isinstance(result, DebriefAnalysis)
    assert len(result.diagnoses) >= 1
    top = result.diagnoses[0]
    assert 350 <= top.region.distance_start <= 550


def test_diagnosis_labeled_with_corner_name():
    result = build_debrief(_slower_driver(), _reference(), CORNERS)
    assert result.diagnoses[0].label == "Test Hairpin"


def test_braking_delta_detects_early_braking():
    result = build_debrief(_slower_driver(), _reference(), CORNERS)
    top = result.diagnoses[0]
    # Driver brakes ~30m earlier than reference -> negative delta
    assert top.braking_delta_m == pytest.approx(-30.0, abs=10.0)


def test_min_speed_delta_detects_overslowing():
    result = build_debrief(_slower_driver(), _reference(), CORNERS)
    top = result.diagnoses[0]
    # Driver min speed ~18 m/s vs reference ~25 m/s -> negative delta
    assert top.min_speed_delta_ms < -3.0


def test_total_delta_positive_for_slower_driver():
    result = build_debrief(_slower_driver(), _reference(), CORNERS)
    assert result.total_time_delta > 0


def test_identical_laps_produce_no_diagnoses():
    result = build_debrief(_reference(), _reference(), CORNERS)
    assert result.diagnoses == []
    assert result.total_time_delta == pytest.approx(0.0, abs=0.01)


def test_top_n_limits_diagnoses():
    result = build_debrief(_slower_driver(), _reference(), CORNERS, top_n=1)
    assert len(result.diagnoses) <= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_debrief.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

Create `core/coaching/debrief.py`:

```python
"""Debrief orchestrator: driver lap vs reference lap, loss-region first.

Replaces the corner-detection-driven analysis path. Pipeline:
align -> cumulative delta -> loss regions -> annotate -> diagnose.
Every number in the output is arithmetic on the aligned traces and
can be displayed for audit; the AI synthesis layer narrates these
numbers and nothing else.
"""

from dataclasses import dataclass

import numpy as np

from core.telemetry.alignment import find_distance_offset, shift_lap
from core.telemetry.loss_regions import LossRegion, find_loss_regions
from core.telemetry.normalizer import NormalizedLap
from core.track.models import Corner
from core.track.segment_annotator import annotate_region

BRAKE_THRESHOLD = 0.05
THROTTLE_THRESHOLD = 0.9
BRAKE_SEARCH_BACK_M = 200.0


@dataclass
class RegionDiagnosis:
    """Deterministic metrics for one loss region."""

    region: LossRegion
    label: str
    braking_delta_m: float | None  # negative = driver brakes earlier
    min_speed_delta_ms: float  # negative = driver over-slows
    throttle_delta_m: float | None  # positive = driver back on power later
    driver_min_speed_ms: float
    reference_min_speed_ms: float


@dataclass
class DebriefAnalysis:
    """Full debrief of one driver lap against the reference."""

    driver_lap_time: float
    reference_lap_time: float
    total_time_delta: float
    alignment_offset_m: float
    cumulative_delta: np.ndarray
    distance: np.ndarray
    diagnoses: list[RegionDiagnosis]


def _onset(
    mask: np.ndarray, start_idx: int, end_idx: int
) -> int | None:
    """First index in [start_idx, end_idx) where mask is True."""
    span = mask[start_idx:end_idx]
    hits = np.flatnonzero(span)
    return int(start_idx + hits[0]) if len(hits) else None


def _diagnose_region(
    region: LossRegion,
    driver: NormalizedLap,
    reference: NormalizedLap,
    corners: list[Corner],
    interval_m: float,
) -> RegionDiagnosis:
    n = min(len(driver.distance), len(reference.distance))
    start = max(0, int((region.distance_start - BRAKE_SEARCH_BACK_M) / interval_m))
    end = min(n, int(region.distance_end / interval_m) + 1)

    drv_brake = _onset(driver.brake[:n] > BRAKE_THRESHOLD, start, end)
    ref_brake = _onset(reference.brake[:n] > BRAKE_THRESHOLD, start, end)
    braking_delta = (
        (drv_brake - ref_brake) * interval_m
        if drv_brake is not None and ref_brake is not None
        else None
    )

    drv_min = float(driver.speed[start:end].min())
    ref_min = float(reference.speed[start:end].min())

    # Throttle pickup searched from each lap's min-speed point forward
    drv_apex = start + int(np.argmin(driver.speed[start:end]))
    ref_apex = start + int(np.argmin(reference.speed[start:end]))
    search_end = min(n, end + int(100 / interval_m))
    drv_thr = _onset(driver.throttle[:n] > THROTTLE_THRESHOLD, drv_apex, search_end)
    ref_thr = _onset(reference.throttle[:n] > THROTTLE_THRESHOLD, ref_apex, search_end)
    throttle_delta = (
        (drv_thr - ref_thr) * interval_m
        if drv_thr is not None and ref_thr is not None
        else None
    )

    return RegionDiagnosis(
        region=region,
        label=annotate_region(region, corners, track_length=driver.track_length),
        braking_delta_m=braking_delta,
        min_speed_delta_ms=drv_min - ref_min,
        throttle_delta_m=throttle_delta,
        driver_min_speed_ms=drv_min,
        reference_min_speed_ms=ref_min,
    )


def build_debrief(
    driver: NormalizedLap,
    reference: NormalizedLap,
    corners: list[Corner],
    top_n: int = 3,
) -> DebriefAnalysis:
    """Analyze one driver lap against the reference lap."""
    interval_m = float(driver.distance[1] - driver.distance[0])

    offset = find_distance_offset(driver.speed, reference.speed,
                                  interval_m=interval_m)
    aligned_ref = shift_lap(reference, -offset)

    n = min(len(driver.distance), len(aligned_ref.distance))
    cum_delta = (
        (driver.elapsed_time[:n] - driver.elapsed_time[0])
        - (aligned_ref.elapsed_time[:n] - aligned_ref.elapsed_time[0])
    )
    distance = driver.distance[:n]

    regions = find_loss_regions(cum_delta, distance)[:top_n]
    diagnoses = [
        _diagnose_region(r, driver, aligned_ref, corners, interval_m)
        for r in regions
    ]

    return DebriefAnalysis(
        driver_lap_time=driver.lap_time,
        reference_lap_time=reference.lap_time,
        total_time_delta=float(cum_delta[-1]) if n else 0.0,
        alignment_offset_m=offset * interval_m,
        cumulative_delta=cum_delta,
        distance=distance,
        diagnoses=diagnoses,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_debrief.py -v`
Expected: 7 PASS. The synthetic-lap tolerances (`abs=10.0` on braking delta) account for smoothing; if failures exceed tolerance, debug the pipeline (alignment first), don't widen tolerances.

- [ ] **Step 5: Commit**

```bash
git add core/coaching/debrief.py tests/test_debrief.py
git commit -m "feat: debrief orchestrator - align, delta, loss regions, diagnose"
```

---

### Task 9: Official track map assets

**Files:**
- Modify: `core/benchmark/iracing_api.py` (add `get_track_assets` to `LiveIRacingAPI`, after `get_tracks` at line ~253)
- Create: `core/track/track_assets.py`
- Test: `tests/test_track_assets.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_track_assets.py`:

```python
"""Tests for official iRacing track map asset caching."""

from pathlib import Path
from unittest.mock import MagicMock

from core.track.track_assets import TrackAssetCache

ASSETS_RESPONSE = {
    "523": {
        "track_map": "https://example.com/maps/spa/",
        "track_map_layers": {
            "background": "background.svg",
            "active": "active.svg",
            "turns": "turns.svg",
            "start-finish": "start-finish.svg",
        },
        "detail_copy": "<p>Legendary Belgian circuit.</p>",
    }
}


def _cache(tmp_path: Path) -> TrackAssetCache:
    api = MagicMock()
    api.get_track_assets.return_value = ASSETS_RESPONSE
    fetcher = MagicMock(side_effect=lambda url: f"<svg data-src='{url}'/>".encode())
    return TrackAssetCache(api=api, cache_dir=tmp_path, fetch_bytes=fetcher)


def test_downloads_and_caches_layers(tmp_path: Path):
    cache = _cache(tmp_path)
    layers = cache.get_map_layers("523", layers=["active", "turns"])
    assert set(layers) == {"active", "turns"}
    assert (tmp_path / "523" / "active.svg").exists()
    assert (tmp_path / "523" / "turns.svg").exists()


def test_second_call_uses_cache_not_network(tmp_path: Path):
    cache = _cache(tmp_path)
    cache.get_map_layers("523", layers=["active"])
    cache.api.get_track_assets.reset_mock()
    cache.fetch_bytes.reset_mock()
    cache.get_map_layers("523", layers=["active"])
    cache.api.get_track_assets.assert_not_called()
    cache.fetch_bytes.assert_not_called()


def test_detail_copy_returned(tmp_path: Path):
    cache = _cache(tmp_path)
    assert "Belgian" in cache.get_detail_copy("523")


def test_unknown_track_returns_empty(tmp_path: Path):
    cache = _cache(tmp_path)
    assert cache.get_map_layers("999", layers=["active"]) == {}
    assert cache.get_detail_copy("999") == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_track_assets.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Add API endpoint method**

In `core/benchmark/iracing_api.py`, inside `LiveIRacingAPI` directly after `get_tracks()` (~line 253):

```python
    def get_track_assets(self) -> dict:
        """Get track map/asset metadata for all tracks, keyed by track_id.

        Includes track_map (base URL), track_map_layers (SVG layer filenames
        incl. the official 'turns' layer), and detail_copy (description HTML).
        """
        return self._api_get("/data/track/assets")
```

- [ ] **Step 4: Implement the cache**

Create `core/track/track_assets.py`:

```python
"""Download and cache official iRacing track map SVGs and descriptions.

The Data API's track/assets endpoint provides layered SVG maps per track
(background / active / pitroad / start-finish / turns). The 'turns' layer
carries official turn numbers — we display these rather than inventing
numbering. Assets are iRacing-copyrighted: cache locally for personal
use, never redistribute.
"""

import json
from pathlib import Path
from typing import Callable

import requests


def _default_fetch(url: str) -> bytes:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.content


class TrackAssetCache:
    """Lazily downloads track map layers; serves from disk afterwards."""

    def __init__(
        self,
        api,  # IRacingAPIClient with get_track_assets()
        cache_dir: Path,
        fetch_bytes: Callable[[str], bytes] = _default_fetch,
    ):
        self.api = api
        self.cache_dir = Path(cache_dir)
        self.fetch_bytes = fetch_bytes
        self._assets: dict | None = None

    def _track_dir(self, track_id: str) -> Path:
        return self.cache_dir / str(track_id)

    def _load_assets(self) -> dict:
        """Asset index, cached on disk so the API is hit once per machine."""
        index_path = self.cache_dir / "assets_index.json"
        if self._assets is None:
            if index_path.exists():
                self._assets = json.loads(index_path.read_text(encoding="utf-8"))
            else:
                self._assets = self.api.get_track_assets()
                index_path.parent.mkdir(parents=True, exist_ok=True)
                index_path.write_text(json.dumps(self._assets), encoding="utf-8")
        return self._assets

    def get_map_layers(
        self, track_id: str, layers: list[str] = ("active", "turns", "start-finish")
    ) -> dict[str, Path]:
        """Local SVG paths per requested layer; downloads on first access."""
        track_dir = self._track_dir(track_id)
        result: dict[str, Path] = {}
        missing = []
        for layer in layers:
            path = track_dir / f"{layer}.svg"
            if path.exists():
                result[layer] = path
            else:
                missing.append(layer)

        if not missing:
            return result

        entry = self._load_assets().get(str(track_id))
        if entry is None:
            return result
        base = entry.get("track_map", "")
        layer_files = entry.get("track_map_layers", {})
        track_dir.mkdir(parents=True, exist_ok=True)
        for layer in missing:
            filename = layer_files.get(layer)
            if not filename:
                continue
            path = track_dir / f"{layer}.svg"
            path.write_bytes(self.fetch_bytes(base + filename))
            result[layer] = path
        return result

    def get_detail_copy(self, track_id: str) -> str:
        """Official track description HTML (scouting prompt grounding)."""
        entry = self._load_assets().get(str(track_id))
        return (entry or {}).get("detail_copy", "") or ""
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_track_assets.py -v`
Expected: 4 PASS

- [ ] **Step 6: Live smoke check (network + credentials), then commit**

```powershell
.venv/Scripts/python.exe -c "from dotenv import load_dotenv; load_dotenv(); import os; from core.benchmark.iracing_api import LiveIRacingAPI; from core.track.track_assets import TrackAssetCache; from pathlib import Path; api = LiveIRacingAPI(client_id=os.environ['IRACING_CLIENT_ID'], client_secret=os.environ['IRACING_CLIENT_SECRET'], username=os.environ['IRACING_USERNAME'], password=os.environ['IRACING_PASSWORD']); cache = TrackAssetCache(api, Path('data/track_maps')); print(cache.get_map_layers('523'))"
```

Expected: dict with three local SVG paths under `data/track_maps/523/`. Check `LiveIRacingAPI.__init__` (line ~126) for its real constructor kwargs first and adjust the smoke command. If the response keys differ (e.g. assets keyed differently than track_id strings), fix `track_assets.py` and the test fixture to match reality. Add `data/track_maps/` to `.gitignore`.

```bash
git add core/benchmark/iracing_api.py core/track/track_assets.py tests/test_track_assets.py .gitignore
git commit -m "feat: official iRacing track map SVG fetch and cache (turns layer)"
```

---

### Task 10: GPS track map component

**Files:**
- Create: `app/components/track_map.py`
- Test: `tests/test_track_map.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_track_map.py`:

```python
"""Tests for the GPS-derived track map figure builder."""

import numpy as np
import plotly.graph_objects as go

from app.components.track_map import build_loss_map
from core.telemetry.loss_regions import LossRegion


def _circle_lap(n: int = 360):
    theta = np.linspace(0, 2 * np.pi, n)
    lat = 50.0 + 0.01 * np.sin(theta)
    lon = 5.0 + 0.01 * np.cos(theta)
    distance = np.linspace(0, 7000, n)
    return lat, lon, distance


def test_returns_plotly_figure():
    lat, lon, distance = _circle_lap()
    fig = build_loss_map(lat, lon, distance, regions=[])
    assert isinstance(fig, go.Figure)


def test_loss_regions_get_their_own_traces():
    lat, lon, distance = _circle_lap()
    regions = [
        LossRegion(distance_start=1000.0, distance_end=1500.0, time_lost=0.4),
        LossRegion(distance_start=4000.0, distance_end=4300.0, time_lost=0.2),
    ]
    fig = build_loss_map(lat, lon, distance, regions=regions)
    # 1 base outline trace + 1 trace per region
    assert len(fig.data) == 3


def test_region_trace_labeled_with_time_lost():
    lat, lon, distance = _circle_lap()
    regions = [LossRegion(distance_start=1000.0, distance_end=1500.0,
                          time_lost=0.4)]
    fig = build_loss_map(lat, lon, distance, regions=regions,
                         labels=["Eau Rouge"])
    assert "Eau Rouge" in fig.data[1].name
    assert "0.4" in fig.data[1].name


def test_aspect_ratio_locked():
    lat, lon, distance = _circle_lap()
    fig = build_loss_map(lat, lon, distance, regions=[])
    assert fig.layout.yaxis.scaleanchor == "x"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_track_map.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

Create `app/components/track_map.py`:

```python
"""GPS-derived track map with loss regions colored by time lost.

Display-only component (no analysis logic): takes lat/lon/distance
arrays plus LossRegions and returns a Plotly figure. The official
SVG maps (track_assets) are for briefings; this GPS outline is for
debriefs, where loss spans must be projected onto track position.
"""

import numpy as np
import plotly.graph_objects as go

from core.telemetry.loss_regions import LossRegion

# Reds from amber to deep red, most time lost = darkest
_REGION_COLORS = ["#d62728", "#ff7f0e", "#ffbf00"]


def build_loss_map(
    lat: np.ndarray,
    lon: np.ndarray,
    distance: np.ndarray,
    regions: list[LossRegion],
    labels: list[str] | None = None,
) -> go.Figure:
    """Track outline (grey) with each loss region overlaid in color."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=lon, y=lat, mode="lines",
        line={"color": "#888", "width": 2},
        name="Track", hoverinfo="skip",
    ))

    for i, region in enumerate(regions):
        mask = (distance >= region.distance_start) & (
            distance <= region.distance_end
        )
        label = labels[i] if labels and i < len(labels) else f"Region {i + 1}"
        fig.add_trace(go.Scatter(
            x=lon[mask], y=lat[mask], mode="lines",
            line={"color": _REGION_COLORS[i % len(_REGION_COLORS)], "width": 6},
            name=f"{label} (+{region.time_lost:.1f}s)",
        ))

    fig.update_layout(
        xaxis={"visible": False},
        yaxis={"visible": False, "scaleanchor": "x"},
        showlegend=True,
        margin={"l": 10, "r": 10, "t": 10, "b": 10},
        height=420,
    )
    return fig
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_track_map.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add app/components/track_map.py tests/test_track_map.py
git commit -m "feat: GPS track map component with loss-region overlay"
```

---

### Task 11: Validation gate — reconcile against Garage 61 (the trust contract)

**User checkpoint:** needs real paired data — an IBT session AND the G61 CSV export of a lap from that same session (G61 ingests the user's own laps automatically; export the user's own best lap from the session). Ask the user to place them at `tests/fixtures/g61/paired_session.ibt` and `tests/fixtures/g61/paired_lap.csv`, and to report (a) the official lap time G61 displays for that lap, (b) the G61-displayed gap if they compared two of their own laps. Record these in the test constants.

**Files:**
- Test: `tests/test_g61_validation_gate.py`

- [ ] **Step 1: Obtain paired fixtures from the user** (checkpoint above — blocks until provided)

- [ ] **Step 2: Write the validation test**

Create `tests/test_g61_validation_gate.py` (fill the two constants from the user's report):

```python
"""THE VALIDATION GATE: our numbers must reconcile with Garage 61.

G61 is the community gold standard for iRacing lap data. If our
pipeline disagrees with what G61 displays for the same lap, our
pipeline is wrong. This is a permanent fixture test, not a one-off.
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
    parser = IBTParser()
    ibt = parser.parse(IBT_FILE)
    laps = Normalizer().normalize_session(
        parser.get_laps(ibt), ibt.session.track_length_m
    )
    valid = [l for l in laps if l.is_valid]
    return min(valid, key=lambda l: l.lap_time)


@pytest.fixture(scope="module")
def g61_lap(ibt_best_lap):
    with open(CSV_FILE) as f:
        return import_g61_csv(f, track_length_m=ibt_best_lap.track_length)


def test_g61_lap_time_matches_displayed(g61_lap):
    if G61_DISPLAYED_LAP_TIME is None:
        pytest.skip("G61 displayed lap time not recorded yet")
    assert g61_lap.lap_time == pytest.approx(G61_DISPLAYED_LAP_TIME, abs=0.2)


def test_same_lap_from_both_sources_agrees(ibt_best_lap, g61_lap):
    """The exported G61 lap IS one of our IBT laps: deltas must be ~zero."""
    # Lap times agree
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
```

Note: check the real attribute names on `IBTFile`/`IBTSession` (`core/telemetry/ibt_parser.py:105-130`) and `Normalizer.normalize_session` (`core/telemetry/normalizer.py:136`) signatures; adjust the fixture code to the actual API — change the test plumbing, never the assertions.

- [ ] **Step 3: Run the gate**

Run: `.venv/Scripts/python.exe -m pytest tests/test_g61_validation_gate.py -v`
Expected: PASS (or SKIP without fixtures). **If it fails: this is the most important failure in the project — STOP, use superpowers:systematic-debugging, and fix the pipeline (likely suspects in order: G61 unit/column mapping, alignment offset, elapsed-time integration). Do not proceed to Task 12 with a failing gate.**

- [ ] **Step 4: Commit**

```bash
git add tests/test_g61_validation_gate.py
git commit -m "test: G61 validation gate - pipeline must reconcile with Garage 61"
```

---

### Task 12: Wire into the coaching page

Minimal display wiring: import a reference, debrief against it. No business logic in the Streamlit file.

**Files:**
- Modify: `app/pages/coaching.py`
- Modify: `app/streamlit_app.py` (only if a new sidebar entry is needed)

- [ ] **Step 1: Read the current page structure**

Read `app/pages/coaching.py` fully. Identify: where the IBT upload happens, where `analyze_session` is called, where plots render. The debrief view ADDS a reference-based path beside the existing self-referential one; do not delete the existing flow in this task.

- [ ] **Step 2: Add reference import + debrief sections**

In `app/pages/coaching.py`, after the existing session analysis section, add (adapt names to the file's actual conventions and unit helpers):

```python
import numpy as np

from app.components.track_map import build_loss_map
from core.benchmark.g61_import import import_g61_csv
from core.benchmark.reference_store import ReferenceStore
from core.coaching.debrief import build_debrief

REFERENCE_DB = Path("data") / "reference_laps.db"


def render_reference_section(track_id: str, car: str,
                             track_length_m: float) -> None:
    """Reference lap import + status for the current combo."""
    store = ReferenceStore(REFERENCE_DB)
    ref = store.get(track_id, car)

    with st.expander("Reference lap", expanded=ref is None):
        if ref is not None:
            st.caption(
                f"Reference: {ref.meta.source} — "
                f"{ref.meta.lap_time:.3f}s"
                + (f" by {ref.meta.driver_name}" if ref.meta.driver_name else "")
            )
        uploaded = st.file_uploader(
            "Import Garage 61 CSV (a clean lap 1-2s faster than you)",
            type="csv", key="g61_csv",
        )
        driver_name = st.text_input("Driver name (optional)", key="g61_driver")
        if uploaded is not None and st.button("Save as reference"):
            lap = import_g61_csv(uploaded, track_length_m=track_length_m)
            store.save(track_id, car, lap, source="g61",
                       driver_name=driver_name or None)
            st.success(f"Reference saved: {lap.lap_time:.3f}s")
            st.rerun()


def render_debrief(driver_lap, track_id: str, car: str,
                   corners: list) -> None:
    """Loss-region debrief of the driver's best lap vs the reference."""
    store = ReferenceStore(REFERENCE_DB)
    ref = store.get(track_id, car)
    if ref is None:
        st.info("No reference lap for this combo yet — import one above "
                "to unlock the reference debrief.")
        return

    result = build_debrief(driver_lap, ref.lap, corners)

    st.subheader("Where you're losing time vs the reference")
    st.caption(
        f"Your lap {result.driver_lap_time:.3f}s vs reference "
        f"{result.reference_lap_time:.3f}s "
        f"(gap {result.total_time_delta:+.3f}s, "
        f"alignment offset {result.alignment_offset_m:+.0f}m)"
    )

    if np.any(driver_lap.lat) and np.any(driver_lap.lon):
        st.plotly_chart(build_loss_map(
            driver_lap.lat, driver_lap.lon, result.distance,
            [d.region for d in result.diagnoses],
            labels=[d.label for d in result.diagnoses],
        ), use_container_width=True)

    for d in result.diagnoses:
        with st.container(border=True):
            st.markdown(f"**{d.label}** — +{d.region.time_lost:.2f}s")
            cols = st.columns(3)
            if d.braking_delta_m is not None:
                cols[0].metric("Braking point",
                               f"{d.braking_delta_m:+.0f} m",
                               help="negative = you brake earlier than the reference")
            cols[1].metric("Min speed",
                           f"{d.min_speed_delta_ms:+.1f} m/s",
                           help="negative = you over-slow the corner")
            if d.throttle_delta_m is not None:
                cols[2].metric("Back to power",
                               f"{d.throttle_delta_m:+.0f} m",
                               help="positive = you pick up throttle later")
```

Call `render_reference_section(...)` before the analysis runs and `render_debrief(...)` after the existing results display, passing the best valid lap, the track/car identifiers the page already has, and `track_db.get_corners(track_id)`. Use the existing `app/components/units.py` helpers (`fmt_speed`, `fmt_distance`) instead of raw `m/s`/`m` strings where the page already does so — match its conventions.

- [ ] **Step 3: Run the app and verify manually**

Run: `.venv/Scripts/python.exe -m streamlit run app/streamlit_app.py`
Verify: coaching page loads; reference expander appears; importing a G61 CSV saves and reruns; with a reference present, the debrief section renders the map and region cards. Then stop the server.

- [ ] **Step 4: Run the full test suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: all prior tests still pass (209+ existing plus the new ones; 3 pre-existing skips remain).

- [ ] **Step 5: Commit**

```bash
git add app/pages/coaching.py app/streamlit_app.py
git commit -m "feat: reference import and loss-region debrief in coaching page"
```

---

### Task 13: Update project docs

**Files:**
- Modify: `CLAUDE.md` (Current Status + Implementation Notes)

- [ ] **Step 1: Update CLAUDE.md**

Add to Current Status a "Stage 1: Trust Rebuild (reference-lap redesign)" checklist marking what this plan shipped; add Implementation Notes entries for: alignment (cross-correlation, circular shift), loss regions (Savitzky-Golay slope threshold, merge gap), G61 import (alias table, unit heuristics: >130 = km/h, >1.5 = percent pedals), reference store (npz blobs in SQLite, g61 > personal_best), lovely-track-data seeder (slug mapping, fraction→meters), track assets (layer cache, turns layer), debrief orchestrator (no corner detection in path), and the validation gate. Point to the spec for rationale.

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: Stage 1 trust rebuild status and implementation notes"
```

---

## Self-review notes

- **Spec coverage:** reference store (T5), delta/loss regions (T3), G61 import + alignment (T2, T4), validation gate (T11), lovely + annotation (T6, T7), pyirsdk oracle (T1), official maps + GPS map (T9, T10), debrief orchestrator replacing corner detection (T8), UI wiring (T12). Personal-best auto-promotion into the store is deliberately deferred to Stage 3 (the watcher is the natural place to promote PBs after each session); G61 import plus manual flow covers Stage 1. Crew Chief seeding already exists and stays untouched.
- **Stages 2 (briefing) and 3 (watcher) get separate plans** after this one ships and the validation gate is green. Deferred there deliberately: the `iracingdataapi` client swap (Stage 2 — pace context is its consumer), the manual corner-name edit path (Stage 2 UI), and personal-best auto-promotion (Stage 3 watcher).
- **Known reality checks built in:** G61 CSV column names (T4 S1), lovely-track-data JSON shape (T6 S1), track assets response shape (T9 S6), `IBTFile`/`Normalizer` attribute names (T1, T11) — each task says to verify against reality first and fix code/tests to match.
