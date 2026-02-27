"""IBT file parser for iRacing telemetry.

Reads iRacing .ibt binary telemetry files and extracts session metadata,
channel definitions, and telemetry data into structured Python objects.

IBT binary layout:
    [irsdk_header        - 112 bytes]
    [irsdk_diskSubHeader -  32 bytes]
    [Session Info YAML   - at sessionInfoOffset, sessionInfoLen bytes]
    [Variable Headers    - at varHeaderOffset, numVars * 144 bytes each]
    [Telemetry Samples   - at varBuf[0].bufOffset, sessionRecordCount * bufLen bytes]
"""

from dataclasses import dataclass, field
from pathlib import Path
import struct

import numpy as np
import pandas as pd
import yaml


# --- Binary format constants ---

# irsdk_header: 10 ints (40 bytes) + pad[2] (8 bytes) + varBuf[4] (4*16=64 bytes) = 112 bytes
HEADER_FMT = "<iiiiiiiiii"  # 10 ints = 40 bytes
HEADER_SIZE = struct.calcsize(HEADER_FMT)  # 40

# Padding after header fields
HEADER_PAD_SIZE = 8  # pad1[2] = 2 ints = 8 bytes

# varBuf entry: tickCount(i), bufOffset(i), pad[2](ii) = 16 bytes each, 4 entries
VARBUF_FMT = "<iiii"
VARBUF_SIZE = struct.calcsize(VARBUF_FMT)  # 16
VARBUF_COUNT = 4

# Total header = 40 + 8 + 64 = 112
TOTAL_HEADER_SIZE = HEADER_SIZE + HEADER_PAD_SIZE + (VARBUF_SIZE * VARBUF_COUNT)

# irsdk_diskSubHeader: sessionStartDate(q), sessionStartTime(d),
#                       sessionEndTime(d), sessionLapCount(i), sessionRecordCount(i)
DISK_SUB_HEADER_FMT = "<qddii"
DISK_SUB_HEADER_SIZE = struct.calcsize(DISK_SUB_HEADER_FMT)  # 32

# irsdk_varHeader: type(i), offset(i), count(i), countAsTime(B), pad(3x),
#                  name(32s), desc(64s), unit(32s) = 144 bytes
VAR_HEADER_FMT = "<iiiB3x32s64s32s"
VAR_HEADER_SIZE = struct.calcsize(VAR_HEADER_FMT)  # 144

# Variable type mapping: type_id -> (struct_format, byte_size, numpy_dtype)
VAR_TYPE_MAP: dict[int, tuple[str, int, np.dtype]] = {
    0: ("c", 1, np.dtype("S1")),     # irsdk_char
    1: ("?", 1, np.dtype("bool")),    # irsdk_bool
    2: ("i", 4, np.dtype("<i4")),     # irsdk_int
    3: ("I", 4, np.dtype("<u4")),     # irsdk_bitField
    4: ("f", 4, np.dtype("<f4")),     # irsdk_float
    5: ("d", 8, np.dtype("<f8")),     # irsdk_double
}


# --- Data classes ---

@dataclass
class IBTHeader:
    """Main file header."""

    version: int
    status: int
    tick_rate: int
    session_info_update: int
    session_info_len: int
    session_info_offset: int
    num_vars: int
    var_header_offset: int
    num_buf: int
    buf_len: int
    var_buf_offset: int  # From varBuf[0].bufOffset


@dataclass
class IBTDiskSubHeader:
    """Disk sub-header with session-level metadata."""

    session_start_date: int
    session_start_time: float
    session_end_time: float
    session_lap_count: int
    session_record_count: int


@dataclass
class IBTVarHeader:
    """Definition of a single telemetry variable/channel."""

    var_type: int
    offset: int
    count: int
    count_as_time: bool
    name: str
    desc: str
    unit: str


@dataclass
class IBTSession:
    """Parsed session metadata from the YAML session info string."""

    track_name: str
    track_id: int
    track_length_km: float
    car_name: str
    car_id: int
    driver_name: str
    driver_id: int
    session_type: str
    raw: dict = field(default_factory=dict)


@dataclass
class IBTFile:
    """Complete parsed IBT file."""

    header: IBTHeader
    disk_sub_header: IBTDiskSubHeader
    session: IBTSession
    var_headers: list[IBTVarHeader]
    telemetry: pd.DataFrame


class IBTParser:
    """Parse iRacing .ibt binary telemetry files."""

    CORE_CHANNELS = [
        "Speed",
        "Throttle",
        "Brake",
        "SteeringWheelAngle",
        "Lat",
        "Lon",
        "Alt",
        "Lap",
        "LapCurrentLapTime",
        "LapDist",
        "LapDistPct",
        "SessionTime",
        "SessionTick",
        "RPM",
        "Gear",
        # Lap validity channels
        "PlayerTrackSurface",
        "PlayerCarMyIncidentCount",
        "OnPitRoad",
    ]

    def parse(
        self,
        source: Path | bytes,
        channels: list[str] | None = None,
    ) -> IBTFile:
        """Parse an IBT file and return structured data.

        Args:
            source: Path to .ibt file or raw bytes (for Streamlit uploads).
            channels: Specific channels to extract. If None, extracts CORE_CHANNELS.
                      Pass an empty list to extract all available channels.

        Returns:
            IBTFile with header, session info, and telemetry DataFrame.
        """
        if isinstance(source, Path):
            data = source.read_bytes()
        elif isinstance(source, (bytes, bytearray)):
            data = bytes(source)
        else:
            raise TypeError(f"Expected Path or bytes, got {type(source)}")

        header = self._read_header(data)
        disk_sub = self._read_disk_sub_header(data)
        var_headers = self._read_var_headers(data, header)
        session = self._read_session_info(data, header)

        target_channels = channels if channels is not None else self.CORE_CHANNELS
        telemetry = self._read_telemetry(
            data, header, disk_sub, var_headers, target_channels
        )

        return IBTFile(
            header=header,
            disk_sub_header=disk_sub,
            session=session,
            var_headers=var_headers,
            telemetry=telemetry,
        )

    def _read_header(self, data: bytes) -> IBTHeader:
        """Read the main header from bytes 0-111."""
        if len(data) < TOTAL_HEADER_SIZE:
            raise ValueError(
                f"File too small for header: {len(data)} bytes "
                f"(need at least {TOTAL_HEADER_SIZE})"
            )

        # Read the 10 main header fields
        fields = struct.unpack_from(HEADER_FMT, data, 0)
        (
            version,
            status,
            tick_rate,
            session_info_update,
            session_info_len,
            session_info_offset,
            num_vars,
            var_header_offset,
            num_buf,
            buf_len,
        ) = fields

        if version not in (1, 2):
            import warnings
            warnings.warn(
                f"Unexpected IBT version {version} (expected 1 or 2). "
                "Parsing may not be correct.",
                stacklevel=2,
            )

        # Read varBuf[0] to get the data buffer offset
        varbuf_start = HEADER_SIZE + HEADER_PAD_SIZE
        varbuf_fields = struct.unpack_from(VARBUF_FMT, data, varbuf_start)
        var_buf_offset = varbuf_fields[1]  # bufOffset is the second field

        return IBTHeader(
            version=version,
            status=status,
            tick_rate=tick_rate,
            session_info_update=session_info_update,
            session_info_len=session_info_len,
            session_info_offset=session_info_offset,
            num_vars=num_vars,
            var_header_offset=var_header_offset,
            num_buf=num_buf,
            buf_len=buf_len,
            var_buf_offset=var_buf_offset,
        )

    def _read_disk_sub_header(self, data: bytes) -> IBTDiskSubHeader:
        """Read disk sub header from bytes 112-143."""
        offset = TOTAL_HEADER_SIZE
        fields = struct.unpack_from(DISK_SUB_HEADER_FMT, data, offset)
        return IBTDiskSubHeader(
            session_start_date=fields[0],
            session_start_time=fields[1],
            session_end_time=fields[2],
            session_lap_count=fields[3],
            session_record_count=fields[4],
        )

    def _read_var_headers(
        self, data: bytes, header: IBTHeader
    ) -> list[IBTVarHeader]:
        """Read all variable headers."""
        var_headers: list[IBTVarHeader] = []
        offset = header.var_header_offset

        for _ in range(header.num_vars):
            fields = struct.unpack_from(VAR_HEADER_FMT, data, offset)
            var_type, var_offset, count, count_as_time, name_bytes, desc_bytes, unit_bytes = fields

            var_headers.append(
                IBTVarHeader(
                    var_type=var_type,
                    offset=var_offset,
                    count=count,
                    count_as_time=bool(count_as_time),
                    name=name_bytes.split(b"\x00", 1)[0].decode("ascii", errors="replace"),
                    desc=desc_bytes.split(b"\x00", 1)[0].decode("ascii", errors="replace"),
                    unit=unit_bytes.split(b"\x00", 1)[0].decode("ascii", errors="replace"),
                )
            )
            offset += VAR_HEADER_SIZE

        return var_headers

    def _read_session_info(self, data: bytes, header: IBTHeader) -> IBTSession:
        """Read and parse the YAML session info string."""
        start = header.session_info_offset
        end = start + header.session_info_len
        yaml_bytes = data[start:end]

        # Strip trailing null bytes before parsing
        yaml_str = yaml_bytes.split(b"\x00", 1)[0].decode("ascii", errors="replace")

        try:
            raw = yaml.safe_load(yaml_str) or {}
        except yaml.YAMLError:
            raw = {}

        # Extract key fields from the YAML structure
        weekend_info = raw.get("WeekendInfo", {})
        driver_info = raw.get("DriverInfo", {})

        # Track info
        track_name = weekend_info.get("TrackDisplayName", "")
        track_id = int(weekend_info.get("TrackID", 0))

        track_length_str = weekend_info.get("TrackLength", "0 km")
        track_length_km = self._parse_track_length(track_length_str)

        # Car info - from the driver's entry in the DriverInfo
        drivers = driver_info.get("Drivers", [])
        driver_idx = driver_info.get("DriverCarIdx", 0)

        car_name = ""
        car_id = 0
        driver_name = ""
        driver_id = 0

        if drivers and driver_idx < len(drivers):
            driver_entry = drivers[driver_idx]
            car_name = driver_entry.get("CarScreenName", "")
            car_id = int(driver_entry.get("CarID", 0))
            driver_name = driver_entry.get("UserName", "")
            driver_id = int(driver_entry.get("UserID", 0))

        # Session type
        sessions = raw.get("SessionInfo", {}).get("Sessions", [])
        session_type = sessions[-1].get("SessionType", "") if sessions else ""

        return IBTSession(
            track_name=track_name,
            track_id=track_id,
            track_length_km=track_length_km,
            car_name=car_name,
            car_id=car_id,
            driver_name=driver_name,
            driver_id=driver_id,
            session_type=session_type,
            raw=raw,
        )

    def _parse_track_length(self, length_str: str) -> float:
        """Parse track length string like '3.60 km' to float km."""
        try:
            parts = length_str.strip().split()
            return float(parts[0])
        except (ValueError, IndexError):
            return 0.0

    def _read_telemetry(
        self,
        data: bytes,
        header: IBTHeader,
        disk_sub: IBTDiskSubHeader,
        var_headers: list[IBTVarHeader],
        target_channels: list[str],
    ) -> pd.DataFrame:
        """Read telemetry samples into a DataFrame.

        Uses numpy strides for fast extraction instead of per-sample Python loops.
        """
        buf_offset = header.var_buf_offset
        buf_len = header.buf_len
        record_count = disk_sub.session_record_count

        if record_count <= 0:
            return pd.DataFrame()

        # Build a name -> var_header lookup
        var_map = {vh.name: vh for vh in var_headers}

        # Determine which channels to extract
        if target_channels:
            # Filter to channels that actually exist in the file
            channels_to_read = [
                name for name in target_channels if name in var_map
            ]
        else:
            # Extract all scalar (count=1) channels
            channels_to_read = [
                vh.name for vh in var_headers if vh.count == 1
            ]

        columns: dict[str, np.ndarray] = {}

        for name in channels_to_read:
            vh = var_map[name]

            if vh.var_type not in VAR_TYPE_MAP:
                continue

            _, type_size, np_dtype = VAR_TYPE_MAP[vh.var_type]

            if vh.count == 1:
                # Scalar channel: extract with numpy strides
                start = buf_offset + vh.offset
                values = np.ndarray(
                    shape=(record_count,),
                    dtype=np_dtype,
                    buffer=data,
                    offset=start,
                    strides=(buf_len,),
                ).copy()
                columns[name] = values
            else:
                # Array channel (e.g., CarIdxLapDistPct[64]):
                # Skip for now, these are rarely needed for coaching
                pass

        return pd.DataFrame(columns)

    def get_laps(self, ibt: IBTFile) -> list[pd.DataFrame]:
        """Split telemetry into individual laps based on the Lap channel.

        Filters out incomplete laps (first lap which is typically an out-lap,
        and the last lap if incomplete). Returns complete laps only.
        """
        if "Lap" not in ibt.telemetry.columns:
            raise ValueError("Telemetry missing 'Lap' channel")

        lap_groups = ibt.telemetry.groupby("Lap")
        laps: list[pd.DataFrame] = []

        for lap_num, group in lap_groups:
            # Skip lap 0 (out-lap / pre-session)
            if lap_num <= 0:
                continue

            lap_df = group.reset_index(drop=True)

            # Skip very short laps (likely incomplete or pit laps)
            if len(lap_df) < 100:
                continue

            # Check for reasonable distance coverage if LapDist is available
            if "LapDist" in lap_df.columns:
                dist_range = lap_df["LapDist"].max() - lap_df["LapDist"].min()
                track_length = ibt.session.track_length_km * 1000
                if track_length > 0 and dist_range < track_length * 0.8:
                    continue

            laps.append(lap_df)

        return laps

    def get_lap_times(self, ibt: IBTFile) -> list[tuple[int, float]]:
        """Return list of (lap_number, lap_time) tuples.

        Uses the LapCurrentLapTime channel: the maximum value within
        each lap gives the lap time.
        """
        if "Lap" not in ibt.telemetry.columns:
            raise ValueError("Telemetry missing 'Lap' channel")

        results: list[tuple[int, float]] = []

        if "LapCurrentLapTime" in ibt.telemetry.columns:
            for lap_num, group in ibt.telemetry.groupby("Lap"):
                if lap_num <= 0:
                    continue
                # Use last value, not max — the Lap channel transitions
                # before LCT resets, so early samples may contain the
                # previous lap's stale LCT value.
                lap_time = group["LapCurrentLapTime"].iloc[-1]
                if lap_time > 0:
                    results.append((int(lap_num), float(lap_time)))
        elif "SessionTime" in ibt.telemetry.columns:
            # Fallback: compute from SessionTime deltas between lap transitions
            for lap_num, group in ibt.telemetry.groupby("Lap"):
                if lap_num <= 0:
                    continue
                lap_time = group["SessionTime"].iloc[-1] - group["SessionTime"].iloc[0]
                if lap_time > 0:
                    results.append((int(lap_num), float(lap_time)))

        return results
