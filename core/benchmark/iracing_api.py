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
