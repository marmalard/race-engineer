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
