"""Data models for tracks and corners."""

from dataclasses import dataclass, field
from enum import Enum


class TrackType(Enum):
    ROAD = "road"
    OVAL = "oval"
    STREET = "street"


class TrackCharacter(Enum):
    MOMENTUM = "momentum"
    POINT_AND_SHOOT = "point-and-shoot"
    MIXED = "mixed"


class CornerType(Enum):
    HAIRPIN = "hairpin"
    SWEEPER = "sweeper"
    CHICANE = "chicane"
    KINK = "kink"
    HEAVY_BRAKING = "heavy_braking"
    DOUBLE_APEX = "double_apex"


@dataclass
class Corner:
    """A corner on a track."""

    corner_id: int | None
    track_id: str
    corner_number: int
    name: str | None
    distance_start_meters: float
    distance_end_meters: float
    corner_type: CornerType | None
    notes: str | None = None


@dataclass
class Track:
    """A track configuration."""

    track_id: str  # iRacing track ID
    name: str
    config: str | None
    length_meters: float
    track_type: TrackType
    character: TrackCharacter | None
    notes: str | None = None
    corners: list[Corner] = field(default_factory=list)
