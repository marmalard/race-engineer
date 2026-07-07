"""Tests for the iRacing Data API client.

Uses mocks for all HTTP interactions — no real API calls.
"""

import base64
import hashlib
import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from core.benchmark.iracing_api import (
    _mask_secret,
    _parse_lap_time,
    _TokenData,
    LiveIRacingAPI,
    StubIRacingAPI,
    PaceData,
    DriverStats,
    RecentRace,
)


class TestMaskSecret:
    """Test the SHA-256 credential masking algorithm."""

    def test_mask_secret_known_output(self):
        """Verify the masking algorithm produces the expected SHA-256 hash."""
        secret = "my_secret"
        identifier = "my_client_id"

        # Manual computation: SHA-256("my_secretmy_client_id") -> base64
        combined = f"{secret}{identifier.strip().lower()}"
        expected = base64.b64encode(
            hashlib.sha256(combined.encode("utf-8")).digest()
        ).decode("utf-8")

        assert _mask_secret(secret, identifier) == expected

    def test_mask_secret_case_normalization(self):
        """Identifier should be lowercased before hashing."""
        result_lower = _mask_secret("secret", "User@Example.COM")
        result_upper = _mask_secret("secret", "user@example.com")
        assert result_lower == result_upper

    def test_mask_secret_strips_whitespace(self):
        """Identifier should be stripped of leading/trailing whitespace."""
        result_clean = _mask_secret("secret", "user@example.com")
        result_padded = _mask_secret("secret", "  user@example.com  ")
        assert result_clean == result_padded

    def test_mask_secret_returns_base64(self):
        """Result should be valid base64."""
        result = _mask_secret("password", "username")
        decoded = base64.b64decode(result)
        assert len(decoded) == 32  # SHA-256 produces 32 bytes


class TestLiveIRacingAPIAuth:
    """Test authentication and token management with mocked HTTP."""

    @pytest.fixture
    def api(self):
        """Create an API client with mocked httpx."""
        with patch("core.benchmark.iracing_api.httpx.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client

            client = LiveIRacingAPI(
                client_id="test-client",
                client_secret="test-secret",
                username="test@example.com",
                password="test-password",
            )
            yield client, mock_client

    def test_authenticate_stores_token(self, api):
        """Successful auth should store access and refresh tokens."""
        client, mock_http = api

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "access_123",
            "refresh_token": "refresh_456",
            "expires_in": 600,
        }
        mock_http.post.return_value = mock_resp

        client._authenticate()

        assert client._token.access_token == "access_123"
        assert client._token.refresh_token == "refresh_456"
        assert client._token.expires_at > time.time()

    def test_authenticate_sends_correct_params(self, api):
        """Auth request should include correct grant_type and scope."""
        client, mock_http = api

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "access_token": "tok",
            "refresh_token": "ref",
            "expires_in": 600,
        }
        mock_http.post.return_value = mock_resp

        client._authenticate()

        call_kwargs = mock_http.post.call_args
        data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
        assert data["grant_type"] == "password_limited"
        assert data["scope"] == "iracing.auth"
        assert data["username"] == "test@example.com"

    def test_refresh_uses_refresh_token(self, api):
        """Token refresh should use the refresh_token grant type."""
        client, mock_http = api

        # Set an existing refresh token
        client._token = _TokenData(
            access_token="old_access",
            refresh_token="refresh_456",
            expires_at=0,
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "new_access",
            "refresh_token": "new_refresh",
            "expires_in": 600,
        }
        mock_http.post.return_value = mock_resp

        client._refresh()

        call_kwargs = mock_http.post.call_args
        data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
        assert data["grant_type"] == "refresh_token"
        assert data["refresh_token"] == "refresh_456"
        assert client._token.access_token == "new_access"

    def test_refresh_fallback_to_full_auth(self, api):
        """If refresh fails, should fall back to full authentication."""
        client, mock_http = api

        client._token = _TokenData(
            access_token="old",
            refresh_token="expired_refresh",
            expires_at=0,
        )

        # First call (refresh) fails, second call (auth) succeeds
        fail_resp = MagicMock()
        fail_resp.status_code = 401

        ok_resp = MagicMock()
        ok_resp.json.return_value = {
            "access_token": "new_from_auth",
            "refresh_token": "new_ref",
            "expires_in": 600,
        }
        mock_http.post.side_effect = [fail_resp, ok_resp]

        client._refresh()
        assert client._token.access_token == "new_from_auth"

    def test_refresh_without_refresh_token_authenticates(self, api):
        """If no refresh token, _refresh should call _authenticate."""
        client, mock_http = api

        client._token = _TokenData(
            access_token="", refresh_token="", expires_at=0
        )

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "access_token": "fresh",
            "refresh_token": "ref",
            "expires_in": 600,
        }
        mock_http.post.return_value = mock_resp

        client._refresh()
        assert client._token.access_token == "fresh"

    def test_ensure_token_reuses_valid_token(self, api):
        """Should not re-auth if token is still valid."""
        client, mock_http = api

        client._token = _TokenData(
            access_token="still_valid",
            refresh_token="ref",
            expires_at=time.time() + 300,
        )

        token = client._ensure_token()
        assert token == "still_valid"
        mock_http.post.assert_not_called()

    def test_ensure_token_refreshes_expired(self, api):
        """Should refresh when token is expired."""
        client, mock_http = api

        client._token = _TokenData(
            access_token="expired",
            refresh_token="ref_tok",
            expires_at=time.time() - 10,
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "refreshed",
            "refresh_token": "new_ref",
            "expires_in": 600,
        }
        mock_http.post.return_value = mock_resp

        token = client._ensure_token()
        assert token == "refreshed"


class TestLiveIRacingAPIData:
    """Test data API calls with mocked HTTP."""

    @pytest.fixture
    def authed_api(self):
        """Create an API client with a pre-set valid token."""
        with patch("core.benchmark.iracing_api.httpx.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client

            client = LiveIRacingAPI(
                client_id="test",
                client_secret="secret",
                username="user@example.com",
                password="pass",
            )
            # Pre-set a valid token so API calls don't trigger auth
            client._token = _TokenData(
                access_token="valid_token",
                refresh_token="ref",
                expires_at=time.time() + 300,
            )
            yield client, mock_client

    def test_api_get_two_step_call(self, authed_api):
        """Should follow the two-step pattern: endpoint -> signed link -> data."""
        client, mock_http = authed_api

        # Step 1 response: returns a signed link
        link_resp = MagicMock()
        link_resp.status_code = 200
        link_resp.json.return_value = {"link": "https://s3.amazonaws.com/signed-data"}

        # Step 2 response: the actual data
        data_resp = MagicMock()
        data_resp.status_code = 200
        data_resp.json.return_value = [{"track_id": 1, "name": "Spa"}]

        mock_http.get.side_effect = [link_resp, data_resp]

        result = client._api_get("/data/track/get")

        assert result == [{"track_id": 1, "name": "Spa"}]
        assert mock_http.get.call_count == 2

        # First call should have auth header
        first_call = mock_http.get.call_args_list[0]
        assert "Bearer valid_token" in str(first_call)

        # Second call should NOT have auth header (signed link)
        second_call = mock_http.get.call_args_list[1]
        assert second_call[0][0] == "https://s3.amazonaws.com/signed-data"

    def test_api_get_direct_response(self, authed_api):
        """Some endpoints return data directly without a signed link."""
        client, mock_http = authed_api

        direct_resp = MagicMock()
        direct_resp.status_code = 200
        direct_resp.json.return_value = {"cust_id": 123, "display_name": "Driver"}

        mock_http.get.return_value = direct_resp

        result = client._api_get("/data/member/info")
        assert result["cust_id"] == 123
        # Only one GET call (no signed link to follow)
        assert mock_http.get.call_count == 1

    def test_get_member_summary(self, authed_api):
        """get_member_summary should call the correct endpoint."""
        client, mock_http = authed_api

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"link": "https://s3/data"}
        mock_http.get.side_effect = [
            mock_resp,
            MagicMock(json=MagicMock(return_value={"irating": 1500})),
        ]

        result = client.get_member_summary()
        first_call = mock_http.get.call_args_list[0]
        assert "/data/stats/member_summary" in str(first_call)

    def test_get_season_results_passes_params(self, authed_api):
        """get_season_results should pass season_id and race_week_num."""
        client, mock_http = authed_api

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": []}
        mock_http.get.return_value = mock_resp

        client.get_season_results(season_id=4567, race_week_num=3)

        call_kwargs = mock_http.get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["season_id"] == 4567
        assert params["race_week_num"] == 3


class TestParseLapTime:
    """Test lap time format detection and conversion."""

    def test_seconds_format(self):
        """Values <= 600 are assumed to be in seconds."""
        assert _parse_lap_time(123.456) == pytest.approx(123.456)

    def test_tenths_format(self):
        """Values > 600 are assumed to be in 1/10000s."""
        # 1414567 / 10000 = 141.4567
        assert _parse_lap_time(1414567) == pytest.approx(141.4567)

    def test_zero(self):
        assert _parse_lap_time(0) == 0.0

    def test_negative(self):
        """Negative values should pass through as-is (invalid marker)."""
        assert _parse_lap_time(-1) == -1.0


class TestMemberRecentRaces:
    """Tests for the member_recent_races endpoint."""

    @pytest.fixture
    def authed_api(self):
        """Create an API client with a pre-set valid token."""
        with patch("core.benchmark.iracing_api.httpx.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client

            client = LiveIRacingAPI(
                client_id="test",
                client_secret="secret",
                username="user@example.com",
                password="pass",
            )
            client._token = _TokenData(
                access_token="valid_token",
                refresh_token="ref",
                expires_at=time.time() + 300,
            )
            yield client, mock_client

    def test_parses_races_with_nested_track(self, authed_api):
        """Should handle nested track dict in API response."""
        client, mock_http = authed_api

        link_resp = MagicMock()
        link_resp.json.return_value = {"link": "https://s3/data"}

        data_resp = MagicMock()
        data_resp.json.return_value = {
            "races": [{
                "subsession_id": 12345,
                "series_name": "IMSA Michelin Pilot Challenge",
                "track": {"track_name": "Road America", "track_id": 18},
                "car_name": "BMW M4 GT4",
                "car_id": 72,
                "start_position": 5,
                "finish_position": 3,
                "incidents": 2,
                "best_lap_time": 1414567,
                "best_qual_lap_time": 1410234,
                "strength_of_field": 1850,
                "field_size": 20,
                "session_start_time": "2026-02-20T19:00:00Z",
                "newi_rating": 1600,
                "oldi_rating": 1550,
            }],
        }
        mock_http.get.side_effect = [link_resp, data_resp]

        races = client.get_member_recent_races()
        assert len(races) == 1
        assert races[0].track_name == "Road America"
        assert races[0].track_id == 18
        assert races[0].finish_position == 3
        assert races[0].best_lap_time == pytest.approx(141.4567)

    def test_parses_races_flat_track(self, authed_api):
        """Should handle flat track_name field in API response."""
        client, mock_http = authed_api

        link_resp = MagicMock()
        link_resp.json.return_value = {"link": "https://s3/data"}

        data_resp = MagicMock()
        data_resp.json.return_value = {
            "races": [{
                "subsession_id": 1,
                "series_name": "Test Series",
                "track_name": "Spa",
                "track_id": 523,
                "car_name": "MX-5",
                "car_id": 1,
                "start_position": 1,
                "finish_position": 1,
                "incidents": 0,
                "best_lap_time": 130.5,
                "best_qual_lap_time": 129.8,
                "strength_of_field": 2000,
                "field_size": 15,
                "session_start_time": "2026-02-25T20:00:00Z",
                "newi_rating": 1700,
                "oldi_rating": 1680,
            }],
        }
        mock_http.get.side_effect = [link_resp, data_resp]

        races = client.get_member_recent_races()
        assert len(races) == 1
        assert races[0].track_name == "Spa"
        assert races[0].best_lap_time == pytest.approx(130.5)

    def test_handles_list_response(self, authed_api):
        """Should handle direct list response (no 'races' wrapper)."""
        client, mock_http = authed_api

        link_resp = MagicMock()
        link_resp.json.return_value = {"link": "https://s3/data"}

        data_resp = MagicMock()
        data_resp.json.return_value = [{
            "subsession_id": 1,
            "series_name": "Test",
            "track_name": "Monza",
            "track_id": 239,
            "car_name": "Formula iR-04",
            "car_id": 2,
            "best_lap_time": 0,
            "best_qual_lap_time": 0,
        }]
        mock_http.get.side_effect = [link_resp, data_resp]

        races = client.get_member_recent_races()
        assert len(races) == 1
        assert races[0].track_name == "Monza"

    def test_empty_response(self, authed_api):
        """Should return empty list for empty response."""
        client, mock_http = authed_api

        resp = MagicMock()
        resp.json.return_value = {"races": []}
        mock_http.get.return_value = resp

        races = client.get_member_recent_races()
        assert races == []

    def test_passes_cust_id_param(self, authed_api):
        """Should pass cust_id as query parameter when provided."""
        client, mock_http = authed_api

        resp = MagicMock()
        resp.json.return_value = {"races": []}
        mock_http.get.return_value = resp

        client.get_member_recent_races(cust_id=1226848)

        call_kwargs = mock_http.get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["cust_id"] == 1226848


class TestStubIRacingAPI:
    def test_get_pace_data_raises(self):
        """Stub should raise NotImplementedError."""
        stub = StubIRacingAPI()
        with pytest.raises(NotImplementedError):
            stub.get_pace_data("spa", "bmw")

    def test_get_driver_stats_raises(self):
        """Stub should raise NotImplementedError."""
        stub = StubIRacingAPI()
        with pytest.raises(NotImplementedError):
            stub.get_driver_stats(123)

    def test_get_member_recent_races_returns_empty(self):
        """Stub should return empty list (graceful fallback)."""
        stub = StubIRacingAPI()
        assert stub.get_member_recent_races() == []


class TestContextManager:
    def test_context_manager_closes_client(self):
        """Using LiveIRacingAPI as context manager should close httpx client."""
        with patch("core.benchmark.iracing_api.httpx.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client

            with LiveIRacingAPI("id", "secret", "user", "pass") as api:
                pass

            mock_client.close.assert_called_once()


# ---------------------------------------------------------------------------
# Chunked endpoints — Task 1 (Race Debrief)
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeHTTPClient:
    """Serves canned responses keyed by URL substring."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[str] = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        for key, payload in self.routes.items():
            if key in url:
                return _FakeResponse(payload)
        raise AssertionError(f"unexpected URL: {url}")


def _api_with_fake_client(routes: dict):
    from core.benchmark.iracing_api import LiveIRacingAPI, _TokenData

    api = LiveIRacingAPI("cid", "csecret", "user", "pass")
    api._client = _FakeHTTPClient(routes)
    # Pre-seed a valid token so _ensure_token never hits the network
    api._token = _TokenData(access_token="tok", expires_at=9999999999.0)
    return api


def test_fetch_chunked_concatenates_chunks():
    routes = {
        "chunk-a.json": [{"lap_number": 1}],
        "chunk-b.json": [{"lap_number": 2}, {"lap_number": 3}],
    }
    api = _api_with_fake_client(routes)
    data = {
        "chunk_info": {
            "base_download_url": "https://s3.example/",
            "chunk_file_names": ["chunk-a.json", "chunk-b.json"],
        }
    }
    rows = api._fetch_chunked(data)
    assert [r["lap_number"] for r in rows] == [1, 2, 3]


def test_fetch_chunked_without_chunk_info_returns_list_passthrough():
    api = _api_with_fake_client({})
    assert api._fetch_chunked([{"a": 1}]) == [{"a": 1}]
    assert api._fetch_chunked({}) == []


def test_get_subsession_results_calls_results_get():
    payload = {"link": "https://s3.example/signed-results"}
    results_doc = {"subsession_id": 86748877, "session_results": []}
    api = _api_with_fake_client({
        "/data/results/get": payload,
        "signed-results": results_doc,
    })
    out = api.get_subsession_results(86748877)
    assert out["subsession_id"] == 86748877


def test_get_lap_chart_data_unwraps_chunks():
    link_doc = {"link": "https://s3.example/signed-chart"}
    chart_head = {
        "chunk_info": {
            "base_download_url": "https://s3.example/",
            "chunk_file_names": ["c0.json"],
        }
    }
    api = _api_with_fake_client({
        "/data/results/lap_chart_data": link_doc,
        "signed-chart": chart_head,
        "c0.json": [{"cust_id": 1, "lap_number": 0, "lap_position": 5}],
    })
    rows = api.get_lap_chart_data(86748877, 0)
    assert rows[0]["lap_position"] == 5


def test_stub_race_endpoints_graceful():
    from core.benchmark.iracing_api import StubIRacingAPI

    stub = StubIRacingAPI()
    assert stub.get_subsession_results(1) == {}
    assert stub.get_lap_chart_data(1, 0) == []
    assert stub.get_lap_data(1, 0, 2) == []
