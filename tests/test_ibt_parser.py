"""Tests for IBT file parser.

These tests require a real IBT file in tests/fixtures/.
Tests will skip gracefully if no IBT file is available.
"""

import pytest

from core.telemetry.ibt_parser import IBTParser


@pytest.fixture
def parser() -> IBTParser:
    return IBTParser()


@pytest.fixture
def parsed_ibt(parser: IBTParser, sample_ibt_path):
    return parser.parse(sample_ibt_path)


class TestIBTParser:
    def test_header_reads_correctly(self, parsed_ibt):
        """Header version should be 1 or 2, tick_rate should be 60."""
        header = parsed_ibt.header
        assert header.version in (1, 2)
        assert header.tick_rate == 60
        assert header.num_vars > 0
        assert header.buf_len > 0
        assert header.var_buf_offset > 0

    def test_disk_sub_header(self, parsed_ibt):
        """Disk sub header should have positive record count."""
        dsh = parsed_ibt.disk_sub_header
        assert dsh.session_record_count > 0
        assert dsh.session_lap_count >= 0

    def test_session_info_parses(self, parsed_ibt):
        """Should extract track name, car name, driver name."""
        session = parsed_ibt.session
        assert session.track_name, "Track name should not be empty"
        assert session.track_id > 0
        assert session.track_length_km > 0
        assert session.car_name, "Car name should not be empty"
        assert session.raw, "Raw YAML dict should not be empty"

    def test_var_headers_contain_core_channels(self, parsed_ibt):
        """Key channels should be present in the variable headers."""
        var_names = {vh.name for vh in parsed_ibt.var_headers}

        # These channels should always exist in iRacing telemetry
        essential = {"Speed", "Throttle", "Brake", "Lap", "LapDist", "SessionTime"}
        missing = essential - var_names
        assert not missing, f"Missing essential channels: {missing}"

    def test_telemetry_shape(self, parsed_ibt):
        """DataFrame should have record_count rows and multiple columns."""
        df = parsed_ibt.telemetry
        expected_rows = parsed_ibt.disk_sub_header.session_record_count
        assert len(df) == expected_rows
        assert len(df.columns) > 0

    def test_speed_values_reasonable(self, parsed_ibt):
        """Speed should be non-negative and below ~120 m/s (~430 km/h)."""
        if "Speed" not in parsed_ibt.telemetry.columns:
            pytest.skip("Speed channel not present")
        speed = parsed_ibt.telemetry["Speed"]
        assert speed.min() >= -1.0, "Speed should not be significantly negative"
        assert speed.max() < 120.0, "Speed should be below 120 m/s"

    def test_throttle_brake_range(self, parsed_ibt):
        """Throttle and brake should be in [0, 1] range."""
        df = parsed_ibt.telemetry
        if "Throttle" in df.columns:
            assert df["Throttle"].min() >= -0.01
            assert df["Throttle"].max() <= 1.01
        if "Brake" in df.columns:
            assert df["Brake"].min() >= -0.01
            assert df["Brake"].max() <= 1.01

    def test_lap_dist_present(self, parsed_ibt):
        """LapDist should be present and contain reasonable values."""
        if "LapDist" not in parsed_ibt.telemetry.columns:
            pytest.skip("LapDist channel not present")
        lap_dist = parsed_ibt.telemetry["LapDist"]
        track_length_m = parsed_ibt.session.track_length_km * 1000
        assert lap_dist.max() <= track_length_m * 1.1, "LapDist exceeds track length"


class TestIBTParserLaps:
    def test_get_laps_returns_list(self, parser, parsed_ibt):
        """get_laps should return a non-empty list of DataFrames."""
        laps = parser.get_laps(parsed_ibt)
        assert isinstance(laps, list)
        assert len(laps) > 0, "Should have at least one valid lap"

    def test_each_lap_is_dataframe(self, parser, parsed_ibt):
        """Each lap should be a DataFrame with expected columns."""
        laps = parser.get_laps(parsed_ibt)
        for lap_df in laps:
            assert "Speed" in lap_df.columns or "Lap" in lap_df.columns

    def test_get_lap_times(self, parser, parsed_ibt):
        """Should return lap numbers with positive lap times."""
        lap_times = parser.get_lap_times(parsed_ibt)
        assert len(lap_times) > 0
        for lap_num, lap_time in lap_times:
            assert lap_num > 0
            assert lap_time > 0

    def test_parse_from_bytes(self, parser, sample_ibt_path):
        """Parser should accept bytes input as well as Path."""
        raw_bytes = sample_ibt_path.read_bytes()
        ibt = parser.parse(raw_bytes)
        assert ibt.header.version in (1, 2)
        assert len(ibt.telemetry) > 0
