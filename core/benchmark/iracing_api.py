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


# --- Phase 4 data models (pre-race briefing plumbing) ---

@dataclass
class RaceGuideSession:
    """An upcoming official session from /data/season/race_guide.

    entry_count and session_id only populate ~30 minutes before the
    session starts (registration window); before that they are 0/None.
    """

    series_id: int
    season_id: int
    race_week_num: int
    start_time: str  # ISO timestamp
    end_time: str  # ISO timestamp
    entry_count: int  # live registration count; 0 until reg opens
    session_id: int | None  # None until the session is created
    super_session: bool


@dataclass
class SeriesResultRow:
    """One race subsession from /data/results/search_series.

    session_id is shared by every split of one timeslot — group on it and
    sort by strength_of_field descending to reconstruct the split ladder
    (the API exposes no explicit split number).
    """

    subsession_id: int
    session_id: int  # timeslot / split-group key
    start_time: str  # ISO timestamp
    end_time: str  # ISO timestamp
    strength_of_field: int
    num_drivers: int
    track_id: int
    track_name: str
    event_best_lap_time: float  # seconds (0 if not available)
    event_average_lap: float  # seconds (0 if not available)
    num_cautions: int
    num_lead_changes: int
    winner_name: str
    winner_cust_id: int
    season_id: int
    series_id: int
    race_week_num: int
    official_session: bool


@dataclass
class RegisteredDriver:
    """One roster entry from /data/session/reg_drivers_list.

    The roster is only populated while the session is live (from launch
    until completion); before launch and after completion the endpoint
    returns success with empty entries.
    """

    cust_id: int
    display_name: str
    car_id: int
    car_name: str
    reg_status: str  # e.g. "reg_joined"
    irating: int | None  # None when unrated (-1 in the raw payload)
    safety_rating: float | None
    cpi: float | None
    license_level: int
    group_name: str  # e.g. "Class A"
    mpr_num_races: int


@dataclass
class SpectatorSubsession:
    """A live subsession from /data/season/spectator_subsessionids_detail.

    Used to discover live subsession_ids (join season_id to a series to
    find the user's session) for the reg_drivers_list roster call.
    """

    subsession_id: int
    session_id: int
    season_id: int
    start_time: str  # ISO timestamp
    race_week_num: int
    event_type: int


@dataclass
class RaceWeek:
    """One race week's track and race format from a season schedule."""

    race_week_num: int
    track_id: int
    track_name: str
    config_name: str
    start_date: str  # ISO date
    race_time_limit: int | None  # minutes; None when lap-limited
    race_lap_limit: int | None  # laps; None when time-limited
    start_type: str  # e.g. "Standing", "Rolling"
    standing_start: bool
    max_pct_fuel_fill: float | None  # fuel-fill cap; None when unrestricted


@dataclass
class SeasonSchedule:
    """The briefing slice of one season from /data/series/seasons.

    Deliberately tiny: the raw payload is ~7 MB across all seasons and is
    NOT retained — only calendar + race-format fields survive parsing.
    """

    series_id: int
    series_name: str
    season_id: int
    season_name: str
    race_week: int  # current race week number
    max_weeks: int
    weeks: list[RaceWeek] = field(default_factory=list)


@dataclass
class MemberLicense:
    """One category license from a member profile."""

    category_id: int
    category: str  # e.g. "sports_car"
    irating: int | None  # None when unrated (-1 in the raw payload)
    safety_rating: float | None
    cpi: float | None
    license_level: int
    group_name: str  # e.g. "Class A", "Rookie"


@dataclass
class MemberProfile:
    """Identity + licenses slice of /data/member/profile.

    The building block of an opponent card: current iRating / SR per
    category. Trend comes from get_member_chart_data, career volume from
    get_member_career, recent form from get_member_recent_races.
    """

    cust_id: int
    display_name: str
    licenses: list[MemberLicense] = field(default_factory=list)

    def license_for_category(self, category_id: int) -> MemberLicense | None:
        """Return the license for a category id, or None if absent."""
        for lic in self.licenses:
            if lic.category_id == category_id:
                return lic
        return None


@dataclass
class IRatingPoint:
    """One point of a member's iRating time series (chart_data)."""

    when: str  # ISO date
    value: int


@dataclass
class CareerStats:
    """One category's career statistics from /data/stats/member_career."""

    category_id: int
    category: str  # e.g. "Sports Car"
    starts: int
    wins: int
    top5: int
    poles: int
    avg_start_position: float
    avg_finish_position: float
    laps: int
    laps_led: int
    avg_incidents: float
    win_percentage: float


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

    @abstractmethod
    def get_track_assets(self) -> dict:
        """Get track map/asset metadata for all tracks, keyed by track_id."""
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

    def _fetch_chunked(self, data: dict | list) -> list:
        """Assemble a chunked Data API payload into one list.

        Chunked endpoints (lap_chart_data, lap_data) return a dict whose
        chunk_info lists S3 files; each file is a JSON array. Non-chunked
        list payloads pass through unchanged.
        """
        if isinstance(data, list):
            return data
        chunk_info = data.get("chunk_info") if isinstance(data, dict) else None
        if not chunk_info:
            return []
        base = chunk_info["base_download_url"]
        rows: list = []
        for name in chunk_info["chunk_file_names"]:
            url = base + name
            for attempt in (1, 2):  # retry once per spec
                try:
                    resp = self._client.get(url)
                    resp.raise_for_status()
                    rows.extend(resp.json())
                    break
                except httpx.HTTPError:
                    if attempt == 2:
                        raise
        return rows

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

    def get_subsession_results(self, subsession_id: int) -> dict:
        """Get full official results for a subsession (all simsessions)."""
        return self._api_get(
            "/data/results/get", {"subsession_id": subsession_id}
        )

    def get_lap_chart_data(
        self, subsession_id: int, simsession_number: int
    ) -> list[dict]:
        """Get every car's position on every lap (chunked endpoint)."""
        data = self._api_get(
            "/data/results/lap_chart_data",
            {
                "subsession_id": subsession_id,
                "simsession_number": simsession_number,
            },
        )
        return self._fetch_chunked(data)

    def get_lap_data(
        self, subsession_id: int, simsession_number: int, cust_id: int
    ) -> list[dict]:
        """Get one driver's per-lap times and events (chunked endpoint)."""
        data = self._api_get(
            "/data/results/lap_data",
            {
                "subsession_id": subsession_id,
                "simsession_number": simsession_number,
                "cust_id": cust_id,
            },
        )
        return self._fetch_chunked(data)

    # --- Phase 4: pre-race briefing plumbing ---

    def get_race_guide(
        self, from_time: str | None = None
    ) -> list[RaceGuideSession]:
        """Get upcoming official sessions from /data/season/race_guide.

        The guide returns a 3-hour block starting at from_time (ISO
        timestamp, defaults to now server-side); page forward by passing
        later from_time values. entry_count / session_id populate only
        ~30 minutes before each session's start.
        """
        params = {"from": from_time} if from_time is not None else None
        data = self._api_get("/data/season/race_guide", params)
        return parse_race_guide(data)

    def search_series_results(
        self,
        season_id: int | None = None,
        season_year: int | None = None,
        season_quarter: int | None = None,
        series_id: int | None = None,
        race_week_num: int | None = None,
        official_only: bool = True,
        event_types: int = 5,
    ) -> list[SeriesResultRow]:
        """Search official results via /data/results/search_series.

        Pass either season_id, or season_year + season_quarter + series_id.
        Response is chunked with chunk_info nested one level deeper than
        the lap-data endpoints (under a data key) — normalized here.

        An empty-but-success response returns [] — that emptiness is NOT
        an error and callers must never disk-cache it (same lesson as the
        race-capture _cached_fetch fix). One popular series-week is ~4 MB;
        callers should fetch once per series-week.
        """
        params: dict = {
            "official_only": official_only,
            "event_types": event_types,
        }
        if season_id is not None:
            params["season_id"] = season_id
        if season_year is not None:
            params["season_year"] = season_year
        if season_quarter is not None:
            params["season_quarter"] = season_quarter
        if series_id is not None:
            params["series_id"] = series_id
        if race_week_num is not None:
            params["race_week_num"] = race_week_num

        data = self._api_get("/data/results/search_series", params)
        # chunk_info may live under data (search_series) or at top level
        holder = data.get("data", data) if isinstance(data, dict) else data
        if not isinstance(holder, (dict, list)):
            return []
        rows = self._fetch_chunked(holder)
        return parse_series_results(rows)

    def get_reg_drivers(self, subsession_id: int) -> list[RegisteredDriver]:
        """Get the live roster for a subsession via reg_drivers_list.

        Only populated while the session is live (launch to completion).
        Returns [] before launch and after completion (success with empty
        entries — emptiness is ambiguous, not an error; the endpoint also
        returns empty for ids it does not recognize, never a 4xx).
        """
        data = self._api_get(
            "/data/session/reg_drivers_list",
            {"subsession_id": subsession_id},
        )
        return parse_reg_drivers(data)

    def get_spectator_subsessions(
        self, event_types: int = 5
    ) -> list[SpectatorSubsession]:
        """List live subsessions (spectator discovery).

        Used to find the subsession_id of a just-launched session for
        get_reg_drivers. event_types 5 = Race.
        """
        data = self._api_get(
            "/data/season/spectator_subsessionids_detail",
            {"event_types": event_types},
        )
        return parse_spectator_subsessions(data)

    def get_series_seasons(
        self, include_series: bool = True
    ) -> list[SeasonSchedule]:
        """Get the active-season calendar via /data/series/seasons.

        The raw payload is ~7 MB (153 active seasons); only the briefing
        slice (calendar + race format per week) is parsed and returned —
        the raw blob is not retained. Callers should cache the result
        (roughly daily freshness is fine).
        """
        data = self._api_get(
            "/data/series/seasons", {"include_series": include_series}
        )
        return parse_season_schedules(data)

    def get_member_profile(self, cust_id: int) -> MemberProfile | None:
        """Get a member's identity + licenses via /data/member/profile.

        Opponent-card building block; 2-3 calls per opponent add up for
        a full field (12 cars = 24-36 calls) — callers should cache.
        """
        data = self._api_get("/data/member/profile", {"cust_id": cust_id})
        return parse_member_profile(data)

    def get_member_chart_data(
        self, cust_id: int, category_id: int = 5, chart_type: int = 1
    ) -> list[IRatingPoint]:
        """Get a member's iRating time series via /data/member/chart_data.

        category_id: 5 = sports_car, 6 = formula (1 oval, 2 road legacy).
        chart_type 1 = iRating.
        """
        data = self._api_get(
            "/data/member/chart_data",
            {
                "cust_id": cust_id,
                "category_id": category_id,
                "chart_type": chart_type,
            },
        )
        return parse_chart_data(data)

    def get_member_career(self, cust_id: int) -> list[CareerStats]:
        """Get per-category career stats via /data/stats/member_career."""
        data = self._api_get(
            "/data/stats/member_career", {"cust_id": cust_id}
        )
        return parse_member_career(data)


# --- Phase 4 parse functions (pure; unit-testable with inline dicts) ---

def parse_race_guide(payload: dict) -> list[RaceGuideSession]:
    """Parse a /data/season/race_guide payload into RaceGuideSession rows.

    Tolerates missing session_id / zero entry_count (both only populate
    ~30 minutes before a session starts). Returns [] for malformed input.
    """
    if not isinstance(payload, dict):
        return []
    sessions = []
    for row in payload.get("sessions") or []:
        sessions.append(RaceGuideSession(
            series_id=row.get("series_id", 0),
            season_id=row.get("season_id", 0),
            race_week_num=row.get("race_week_num", 0),
            start_time=row.get("start_time", ""),
            end_time=row.get("end_time", ""),
            entry_count=row.get("entry_count", 0) or 0,
            session_id=row.get("session_id"),
            super_session=bool(row.get("super_session", False)),
        ))
    return sessions


def parse_series_results(rows: list[dict] | None) -> list[SeriesResultRow]:
    """Parse /data/results/search_series rows into SeriesResultRow objects.

    Lap times arrive in 1/10000s and are converted to seconds. Missing
    track / winner fields are tolerated (zero / empty defaults).
    """
    if not rows:
        return []
    parsed = []
    for row in rows:
        track = row.get("track") or {}
        parsed.append(SeriesResultRow(
            subsession_id=row.get("subsession_id", 0),
            session_id=row.get("session_id", 0),
            start_time=row.get("start_time", ""),
            end_time=row.get("end_time", ""),
            strength_of_field=row.get("event_strength_of_field", 0),
            num_drivers=row.get("num_drivers", 0),
            track_id=track.get("track_id", 0),
            track_name=track.get("track_name", ""),
            event_best_lap_time=_lap_time_or_zero(
                row.get("event_best_lap_time", 0)
            ),
            event_average_lap=_lap_time_or_zero(
                row.get("event_average_lap", 0)
            ),
            num_cautions=row.get("num_cautions", 0),
            num_lead_changes=row.get("num_lead_changes", 0),
            winner_name=row.get("winner_name", ""),
            # winner_group_id is a cust_id in solo events but a TEAM id in
            # team events - do not fetch member profiles for it blindly.
            winner_cust_id=row.get("winner_group_id", 0),
            season_id=row.get("season_id", 0),
            series_id=row.get("series_id", 0),
            race_week_num=row.get("race_week_num", 0),
            official_session=bool(row.get("official_session", False)),
        ))
    return parsed


def _rating_or_none(value: int | None) -> int | None:
    """Normalize an iRating value: -1 means unrated and becomes None."""
    if value is None or value == -1:
        return None
    return value


def _lap_time_or_zero(value: "int | float") -> float:
    """Lap time in seconds; the API's -1 'no valid lap' sentinel becomes 0.0.

    Guards briefing pace math: min() over split best-laps must never pick
    a sentinel. (The shared _parse_lap_time passes -1 through for the
    legacy RecentRace path, whose behavior is test-pinned.)
    """
    parsed = _parse_lap_time(value)
    return parsed if parsed > 0 else 0.0


def parse_reg_drivers(payload: dict) -> list[RegisteredDriver]:
    """Parse a /data/session/reg_drivers_list payload into roster entries.

    Empty entries with success=true is the normal pre-launch and
    post-completion state, not an error. Unrated iRating (-1) maps to
    None; a missing license block yields None ratings.
    """
    if not isinstance(payload, dict):
        return []
    drivers = []
    for entry in payload.get("entries") or []:
        license_block = entry.get("license") or {}
        drivers.append(RegisteredDriver(
            cust_id=entry.get("cust_id", 0),
            display_name=entry.get("display_name", ""),
            car_id=entry.get("car_id", 0),
            car_name=entry.get("car_name", ""),
            reg_status=entry.get("reg_status", ""),
            irating=_rating_or_none(license_block.get("irating")),
            safety_rating=license_block.get("safety_rating"),
            cpi=license_block.get("cpi"),
            license_level=license_block.get("license_level", 0),
            group_name=license_block.get("group_name", ""),
            mpr_num_races=license_block.get("mpr_num_races", 0),
        ))
    return drivers


def parse_spectator_subsessions(payload: dict) -> list[SpectatorSubsession]:
    """Parse /data/season/spectator_subsessionids_detail into rows."""
    if not isinstance(payload, dict):
        return []
    subs = []
    for row in payload.get("subsessions") or []:
        subs.append(SpectatorSubsession(
            subsession_id=row.get("subsession_id", 0),
            session_id=row.get("session_id", 0),
            season_id=row.get("season_id", 0),
            start_time=row.get("start_time", ""),
            race_week_num=row.get("race_week_num", 0),
            event_type=row.get("event_type", 0),
        ))
    return subs


def parse_season_schedules(payload: list | dict) -> list[SeasonSchedule]:
    """Parse /data/series/seasons into SeasonSchedule slices.

    Accepts the raw list or a {"seasons": [...]} wrapper. Keeps only the
    calendar and race-format fields the briefing needs; weather blobs,
    liveries and the rest of the ~7 MB payload are dropped.

    series_name lives on the per-week schedules (the season top level has
    series_id only); the first schedule that names it wins.
    """
    if isinstance(payload, dict):
        seasons_raw = payload.get("seasons") or []
    elif isinstance(payload, list):
        seasons_raw = payload
    else:
        return []

    seasons = []
    for season in seasons_raw:
        weeks = []
        series_name = ""
        for sched in season.get("schedules") or []:
            if not series_name and sched.get("series_name"):
                series_name = sched["series_name"]
            track = sched.get("track") or {}
            # First restriction only - fine for single-car series; a
            # multiclass week with per-car fuel caps needs per-car handling.
            restrictions = sched.get("car_restrictions") or []
            fuel_cap = (
                restrictions[0].get("max_pct_fuel_fill")
                if restrictions else None
            )
            start_type = sched.get("start_type", "")
            weeks.append(RaceWeek(
                race_week_num=sched.get("race_week_num", 0),
                track_id=track.get("track_id", 0),
                track_name=track.get("track_name", ""),
                config_name=track.get("config_name", ""),
                start_date=sched.get("start_date", ""),
                race_time_limit=sched.get("race_time_limit"),
                race_lap_limit=sched.get("race_lap_limit"),
                start_type=start_type,
                standing_start=start_type.lower() == "standing",
                max_pct_fuel_fill=fuel_cap,
            ))
        seasons.append(SeasonSchedule(
            series_id=season.get("series_id", 0),
            series_name=series_name,
            season_id=season.get("season_id", 0),
            season_name=season.get("season_name", ""),
            race_week=season.get("race_week", 0),
            max_weeks=season.get("max_weeks", 0),
            weeks=weeks,
        ))
    return seasons


def parse_member_profile(payload: dict) -> MemberProfile | None:
    """Parse /data/member/profile into a MemberProfile, or None.

    Only member_info (identity + licenses) is kept; awards, activity and
    license history are dropped. Unrated iRating (-1) maps to None.
    """
    if not isinstance(payload, dict):
        return None
    member_info = payload.get("member_info")
    if not isinstance(member_info, dict):
        return None
    licenses = []
    for lic in member_info.get("licenses") or []:
        licenses.append(MemberLicense(
            category_id=lic.get("category_id", 0),
            category=lic.get("category", ""),
            irating=_rating_or_none(lic.get("irating")),
            safety_rating=lic.get("safety_rating"),
            cpi=lic.get("cpi"),
            license_level=lic.get("license_level", 0),
            group_name=lic.get("group_name", ""),
        ))
    return MemberProfile(
        cust_id=member_info.get("cust_id", 0),
        display_name=member_info.get("display_name", ""),
        licenses=licenses,
    )


def parse_chart_data(payload: dict) -> list[IRatingPoint]:
    """Parse /data/member/chart_data into an iRating time series."""
    if not isinstance(payload, dict):
        return []
    return [
        IRatingPoint(when=p.get("when", ""), value=p.get("value", 0))
        for p in payload.get("data") or []
    ]


def parse_member_career(payload: dict) -> list[CareerStats]:
    """Parse /data/stats/member_career into per-category CareerStats."""
    if not isinstance(payload, dict):
        return []
    stats = []
    for row in payload.get("stats") or []:
        stats.append(CareerStats(
            category_id=row.get("category_id", 0),
            category=row.get("category", ""),
            starts=row.get("starts", 0),
            wins=row.get("wins", 0),
            top5=row.get("top5", 0),
            poles=row.get("poles", 0),
            avg_start_position=row.get("avg_start_position", 0),
            avg_finish_position=row.get("avg_finish_position", 0),
            laps=row.get("laps", 0),
            laps_led=row.get("laps_led", 0),
            avg_incidents=row.get("avg_incidents", 0.0),
            win_percentage=row.get("win_percentage", 0.0),
        ))
    return stats


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

    def get_track_assets(self) -> dict:
        return {}  # Graceful fallback: no assets, not an error

    def get_subsession_results(self, subsession_id: int) -> dict:
        return {}  # Graceful fallback: no data, not an error

    def get_lap_chart_data(
        self, subsession_id: int, simsession_number: int
    ) -> list[dict]:
        return []

    def get_lap_data(
        self, subsession_id: int, simsession_number: int, cust_id: int
    ) -> list[dict]:
        return []

    # --- Phase 4 parallels: graceful empty fallbacks ---

    def get_race_guide(
        self, from_time: str | None = None
    ) -> list[RaceGuideSession]:
        return []

    def search_series_results(
        self,
        season_id: int | None = None,
        season_year: int | None = None,
        season_quarter: int | None = None,
        series_id: int | None = None,
        race_week_num: int | None = None,
        official_only: bool = True,
        event_types: int = 5,
    ) -> list[SeriesResultRow]:
        return []

    def get_reg_drivers(self, subsession_id: int) -> list[RegisteredDriver]:
        return []

    def get_spectator_subsessions(
        self, event_types: int = 5
    ) -> list[SpectatorSubsession]:
        return []

    def get_series_seasons(
        self, include_series: bool = True
    ) -> list[SeasonSchedule]:
        return []

    def get_member_profile(self, cust_id: int) -> MemberProfile | None:
        return None

    def get_member_chart_data(
        self, cust_id: int, category_id: int = 5, chart_type: int = 1
    ) -> list[IRatingPoint]:
        return []

    def get_member_career(self, cust_id: int) -> list[CareerStats]:
        return []
