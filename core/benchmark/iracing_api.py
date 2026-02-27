"""iRacing Data API client.

Abstract interface with a stub implementation for use until API access
is approved.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class PaceData:
    """Pace context data for a car/track combination."""

    track_id: str
    car_id: str
    season: str
    irating_brackets: dict[str, float] = field(default_factory=dict)
    fastest_qualifying: float = 0.0
    median_qualifying: float = 0.0


@dataclass
class DriverStats:
    """Basic driver statistics from iRacing."""

    driver_id: int
    display_name: str
    irating: int
    license_class: str
    license_level: float


class IRacingAPIClient(ABC):
    """Abstract interface for iRacing Data API."""

    @abstractmethod
    def get_pace_data(
        self,
        track_id: str,
        car_id: str,
        season: str | None = None,
    ) -> PaceData:
        """Get pace context for a car/track combination."""
        ...

    @abstractmethod
    def get_driver_stats(self, driver_id: int) -> DriverStats:
        """Get driver statistics."""
        ...


class StubIRacingAPI(IRacingAPIClient):
    """Stub implementation until iRacing Data API access is approved.

    All methods raise NotImplementedError with a clear message.
    """

    def get_pace_data(
        self,
        track_id: str,
        car_id: str,
        season: str | None = None,
    ) -> PaceData:
        raise NotImplementedError(
            "iRacing Data API access not yet available. "
            "Scouting reports will use web search for pace context instead."
        )

    def get_driver_stats(self, driver_id: int) -> DriverStats:
        raise NotImplementedError(
            "iRacing Data API access not yet available."
        )
