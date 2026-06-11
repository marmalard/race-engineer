"""iRacing Data API client.

Implements the Password Limited OAuth flow for authentication and
the two-step data retrieval pattern (endpoint -> signed link -> data).
"""

import base64
import hashlib
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx


# --- Data models ---

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
class RecentRace:
    """A recent race result for the authenticated member."""

    session_id: int
    series_name: str
    track_name: str
    track_id: int
    car_name: str
    car_id: int
    start_position: int
    finish_position: int
    incidents: int
    best_lap_time: float  # seconds (0 if not available)
    best_qual_lap_time: float  # seconds (0 if not available)
    strength_of_field: int
    field_size: int
    session_start_time: str  # ISO timestamp
    irating_new: int
    irating_old: int


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

    @abstractmethod
    def get_member_recent_races(
        self, cust_id: int | None = None
    ) -> list[RecentRace]:
        """Get the member's recent race results."""
        ...


# --- OAuth helpers ---

def _mask_secret(secret: str, identifier: str) -> str:
    """Mask a credential using SHA-256 as required by iRacing OAuth.

    Algorithm: base64(SHA-256(secret + lowercase(identifier)))
    """
    normalized_id = identifier.strip().lower()
    combined = f"{secret}{normalized_id}"
    hasher = hashlib.sha256()
    hasher.update(combined.encode("utf-8"))
    return base64.b64encode(hasher.digest()).decode("utf-8")


# --- Token management ---

@dataclass
class _TokenData:
    """Internal token storage."""

    access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0  # Unix timestamp


# --- Live implementation ---

class LiveIRacingAPI(IRacingAPIClient):
    """Live iRacing Data API client using Password Limited OAuth.

    Handles authentication, token refresh, and the two-step data
    retrieval pattern (endpoint returns a signed link, follow it for data).
    """

    TOKEN_URL = "https://oauth.iracing.com/oauth2/token"
    BASE_URL = "https://members-ng.iracing.com"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        username: str,
        password: str,
    ):
        self.client_id = client_id
        self._masked_secret = _mask_secret(client_secret, client_id)
        self._masked_password = _mask_secret(password, username)
        self.username = username
        self._token = _TokenData()
        self._client = httpx.Client(timeout=30.0)

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # --- Authentication ---

    def _authenticate(self) -> None:
        """Perform full password_limited authentication."""
        resp = self._client.post(
            self.TOKEN_URL,
            data={
                "grant_type": "password_limited",
                "client_id": self.client_id,
                "client_secret": self._masked_secret,
                "username": self.username,
                "password": self._masked_password,
                "scope": "iracing.auth",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        data = resp.json()

        self._token = _TokenData(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", ""),
            expires_at=time.time() + data.get("expires_in", 600) - 30,
        )

    def _refresh(self) -> None:
        """Refresh the access token using the single-use refresh token."""
        if not self._token.refresh_token:
            self._authenticate()
            return

        resp = self._client.post(
            self.TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self._masked_secret,
                "refresh_token": self._token.refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if resp.status_code != 200:
            # Refresh token may be consumed/expired — fall back to full auth
            self._authenticate()
            return

        data = resp.json()
        self._token = _TokenData(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", ""),
            expires_at=time.time() + data.get("expires_in", 600) - 30,
        )

    def _ensure_token(self) -> str:
        """Ensure we have a valid access token, authenticating if needed."""
        if not self._token.access_token or time.time() >= self._token.expires_at:
            if self._token.refresh_token:
                self._refresh()
            else:
                self._authenticate()
        return self._token.access_token

    # --- Data API calls ---

    def _api_get(self, endpoint: str, params: dict | None = None) -> dict:
        """Make a two-step Data API call.

        Step 1: GET the endpoint with Bearer token -> get a signed link
        Step 2: GET the signed link (no auth header) -> get the actual data
        """
        token = self._ensure_token()

        # Step 1: Get the signed link
        resp = self._client.get(
            f"{self.BASE_URL}{endpoint}",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        link_data = resp.json()

        if "link" not in link_data:
            # Some endpoints return data directly
            return link_data

        # Step 2: Follow the signed link (no auth header)
        data_resp = self._client.get(link_data["link"])
        data_resp.raise_for_status()
        return data_resp.json()

    # --- Public API methods ---

    def get_member_summary(self) -> dict:
        """Get summary stats for the authenticated member."""
        return self._api_get("/data/stats/member_summary")

    def get_member_info(self) -> dict:
        """Get info for the authenticated member."""
        return self._api_get("/data/member/info")

    def get_tracks(self) -> list[dict]:
        """Get all tracks."""
        return self._api_get("/data/track/get")

    def get_track_assets(self) -> dict:
        """Get track map/asset metadata for all tracks, keyed by track_id.

        Includes track_map (base URL), track_map_layers (SVG layer filenames
        incl. the official 'turns' layer), and detail_copy (description HTML).
        """
        return self._api_get("/data/track/assets")

    def get_cars(self) -> list[dict]:
        """Get all cars."""
        return self._api_get("/data/car/get")

    def get_series(self) -> list[dict]:
        """Get all series."""
        return self._api_get("/data/series/get")

    def get_season_results(
        self, season_id: int, race_week_num: int | None = None
    ) -> dict:
        """Get results for a season."""
        params: dict = {"season_id": season_id}
        if race_week_num is not None:
            params["race_week_num"] = race_week_num
        return self._api_get("/data/results/season_results", params)

    def get_driver_stats(self, driver_id: int) -> DriverStats:
        """Get driver statistics."""
        data = self._api_get("/data/stats/member_summary")

        # Extract from the response
        if isinstance(data, list) and len(data) > 0:
            entry = data[0]
        elif isinstance(data, dict):
            entry = data
        else:
            raise ValueError(f"Unexpected response format: {type(data)}")

        return DriverStats(
            driver_id=driver_id,
            display_name=entry.get("display_name", ""),
            irating=entry.get("irating", 0),
            license_class=entry.get("license_class", ""),
            license_level=entry.get("license_level", 0.0),
        )

    def get_pace_data(
        self,
        track_id: str,
        car_id: str,
        season: str | None = None,
    ) -> PaceData:
        """Get pace context for a car/track combination.

        Uses season results to build iRating bracket pace data.
        This is a higher-level method that aggregates raw API data.
        """
        # TODO: Implement full pace aggregation from season results
        # For now, return empty pace data
        return PaceData(
            track_id=track_id,
            car_id=car_id,
            season=season or "",
        )

    def get_member_recent_races(
        self, cust_id: int | None = None
    ) -> list[RecentRace]:
        """Get the member's recent race results.

        Returns the last ~10 official race results with lap times,
        finishing positions, and strength of field data.
        """
        params: dict = {}
        if cust_id is not None:
            params["cust_id"] = cust_id
        data = self._api_get(
            "/data/stats/member_recent_races", params or None
        )

        # Handle both list responses and {"races": [...]} wrapper
        if isinstance(data, list):
            races_list = data
        elif isinstance(data, dict):
            races_list = data.get("races", [])
        else:
            return []

        results = []
        for race in races_list:
            # Track may be nested dict or flat field
            if isinstance(race.get("track"), dict):
                track_name = race["track"].get("track_name", "")
                track_id = race["track"].get("track_id", 0)
            else:
                track_name = race.get("track_name", "")
                track_id = race.get("track_id", 0)

            results.append(RecentRace(
                session_id=race.get("subsession_id", 0),
                series_name=race.get("series_name", ""),
                track_name=track_name,
                track_id=track_id,
                car_name=race.get("car_name", ""),
                car_id=race.get("car_id", 0),
                start_position=race.get("start_position", 0),
                finish_position=race.get("finish_position", 0),
                incidents=race.get("incidents", 0),
                best_lap_time=_parse_lap_time(race.get("best_lap_time", 0)),
                best_qual_lap_time=_parse_lap_time(
                    race.get("best_qual_lap_time", 0)
                ),
                strength_of_field=race.get("strength_of_field", 0),
                field_size=race.get("field_size", 0),
                session_start_time=race.get("session_start_time", ""),
                irating_new=race.get("newi_rating", 0),
                irating_old=race.get("oldi_rating", 0),
            ))
        return results


def _parse_lap_time(value: int | float) -> float:
    """Parse a lap time value from the iRacing API.

    The API may return lap times in 1/10000th of a second (e.g. 1234567
    means 123.4567s). Values over 600 are assumed to be in this format
    since no lap time in iRacing exceeds 10 minutes.
    """
    if isinstance(value, (int, float)) and value > 600:
        return value / 10000.0
    return float(value)


class StubIRacingAPI(IRacingAPIClient):
    """Stub implementation for when credentials are not configured."""

    def get_pace_data(
        self,
        track_id: str,
        car_id: str,
        season: str | None = None,
    ) -> PaceData:
        raise NotImplementedError(
            "iRacing Data API credentials not configured. "
            "Add them to your .env file."
        )

    def get_driver_stats(self, driver_id: int) -> DriverStats:
        raise NotImplementedError(
            "iRacing Data API credentials not configured."
        )

    def get_member_recent_races(
        self, cust_id: int | None = None
    ) -> list[RecentRace]:
        return []  # Graceful fallback: no data, not an error
