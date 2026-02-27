import pytest
from pathlib import Path


TELEMETRY_DIR = Path(r"C:\Users\antho\Documents\iRacing\telemetry")


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to the test fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_ibt_path(fixtures_dir: Path) -> Path:
    """Path to a real IBT file for testing.

    Place a test IBT file in tests/fixtures/ (any .ibt file).
    Tests that need this fixture will skip if no IBT file is available.
    """
    ibt_files = list(fixtures_dir.glob("*.ibt"))
    if not ibt_files:
        pytest.skip("No sample IBT file available in tests/fixtures/")
    return ibt_files[0]


@pytest.fixture
def multilap_ibt_path() -> Path:
    """Path to a real IBT file with many laps for multi-lap tests.

    Looks in the user's telemetry directory for a Road America session
    (known to have 7+ valid laps), falling back to any large IBT file.
    """
    if not TELEMETRY_DIR.exists():
        pytest.skip("iRacing telemetry directory not found")

    # Prefer Road America (known to have many valid laps)
    for p in TELEMETRY_DIR.glob("formulair04_roadamerica*.ibt"):
        if p.stat().st_size > 30_000_000:
            return p

    # Fallback: any large IBT file likely has multiple laps
    for p in sorted(TELEMETRY_DIR.glob("*.ibt"), key=lambda x: x.stat().st_size, reverse=True):
        if p.stat().st_size > 30_000_000:
            return p

    pytest.skip("No multi-lap IBT file found in telemetry directory")


@pytest.fixture
def bathurst_ibt_path() -> Path:
    """Path to a Bathurst IBT file for track-variety tests."""
    if not TELEMETRY_DIR.exists():
        pytest.skip("iRacing telemetry directory not found")

    for p in TELEMETRY_DIR.glob("*bathurst*.ibt"):
        if p.stat().st_size > 30_000_000:
            return p

    pytest.skip("No Bathurst IBT file found")
