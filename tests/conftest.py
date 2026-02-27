import pytest
from pathlib import Path


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
