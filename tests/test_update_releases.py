"""check_for_update: GitHub payloads mocked, NO network (spec 9). The
fail-quiet contract matters most — the app must never break because the
update check did."""

import pytest

from core.update.releases import (
    UpdateInfo,
    check_for_update,
    download_zip,
    parse_tag,
)


class _FakeResp:
    def __init__(self, status_code=200, json_data=None, text="", content=b""):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.content = content

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


def _release_payload(tag="v0.2.0", *, with_zip=True, with_sums=True, body="notes"):
    assets = []
    if with_zip:
        assets.append({
            "name": f"race-engineer-{tag}.zip",
            "browser_download_url": f"https://gh/{tag}.zip",
        })
    if with_sums:
        assets.append({
            "name": "SHA256SUMS",
            "browser_download_url": "https://gh/SHA256SUMS",
        })
    return {"tag_name": tag, "body": body, "assets": assets}


def _fake_get(release_json, sums_text="", *, release_status=200, sums_status=200):
    def get(url):
        if "SHA256SUMS" in url:
            return _FakeResp(sums_status, text=sums_text)
        return _FakeResp(release_status, json_data=release_json)
    return get


_SHA = "a" * 64


class TestParseTag:
    def test_parses_v_prefixed(self):
        assert parse_tag("v1.2.3") == (1, 2, 3)

    def test_parses_bare(self):
        assert parse_tag("1.2.3") == (1, 2, 3)

    def test_malformed_is_none(self):
        assert parse_tag("release-candidate") is None

    def test_numeric_compare_not_lexical(self):
        assert parse_tag("v0.10.0") > parse_tag("v0.9.9")


class TestCheckForUpdate:
    def test_newer_tag_returns_update_info(self):
        get = _fake_get(
            _release_payload("v0.2.0"),
            f"{_SHA}  race-engineer-v0.2.0.zip\n",
        )
        info = check_for_update("0.1.0", get=get)
        assert info == UpdateInfo(
            tag="v0.2.0", zip_url="https://gh/v0.2.0.zip",
            sha256=_SHA, notes="notes",
        )

    def test_same_version_returns_none(self):
        get = _fake_get(_release_payload("v0.1.0"), f"{_SHA}  x.zip\n")
        assert check_for_update("0.1.0", get=get) is None

    def test_older_release_returns_none(self):
        get = _fake_get(_release_payload("v0.0.9"), f"{_SHA}  x.zip\n")
        assert check_for_update("0.1.0", get=get) is None

    def test_missing_sums_asset_returns_none(self):
        # An update without a checksum is not offered (spec 5.4).
        get = _fake_get(_release_payload("v0.2.0", with_sums=False))
        assert check_for_update("0.1.0", get=get) is None

    def test_missing_zip_asset_returns_none(self):
        get = _fake_get(_release_payload("v0.2.0", with_zip=False))
        assert check_for_update("0.1.0", get=get) is None

    def test_sums_without_our_zip_line_returns_none(self):
        get = _fake_get(
            _release_payload("v0.2.0"), f"{_SHA}  something-else.zip\n"
        )
        assert check_for_update("0.1.0", get=get) is None

    def test_http_error_returns_none(self):
        get = _fake_get(_release_payload("v0.2.0"), release_status=503)
        assert check_for_update("0.1.0", get=get) is None

    def test_network_exception_returns_none(self):
        def get(url):
            raise OSError("no network")
        assert check_for_update("0.1.0", get=get) is None

    def test_malformed_tag_returns_none(self):
        get = _fake_get(_release_payload("nightly"), f"{_SHA}  x.zip\n")
        assert check_for_update("0.1.0", get=get) is None


class TestDownloadZip:
    def test_returns_bytes_on_200(self):
        def get(url):
            return _FakeResp(200, content=b"zipbytes")
        assert download_zip("https://gh/x.zip", get=get) == b"zipbytes"

    def test_raises_on_http_error(self):
        def get(url):
            return _FakeResp(404)
        with pytest.raises(RuntimeError):
            download_zip("https://gh/x.zip", get=get)
