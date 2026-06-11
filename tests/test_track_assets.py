"""Tests for official iRacing track map asset caching."""

from pathlib import Path
from unittest.mock import MagicMock

from core.track.track_assets import TrackAssetCache

ASSETS_RESPONSE = {
    "523": {
        "track_map": "https://example.com/maps/spa/",
        "track_map_layers": {
            "background": "background.svg",
            "active": "active.svg",
            "turns": "turns.svg",
            "start-finish": "start-finish.svg",
        },
        "detail_copy": "<p>Legendary Belgian circuit.</p>",
    }
}


def _cache(tmp_path: Path) -> TrackAssetCache:
    api = MagicMock()
    api.get_track_assets.return_value = ASSETS_RESPONSE
    fetcher = MagicMock(side_effect=lambda url: f"<svg data-src='{url}'/>".encode())
    return TrackAssetCache(api=api, cache_dir=tmp_path, fetch_bytes=fetcher)


def test_downloads_and_caches_layers(tmp_path: Path):
    cache = _cache(tmp_path)
    layers = cache.get_map_layers("523", layers=["active", "turns"])
    assert set(layers) == {"active", "turns"}
    assert (tmp_path / "523" / "active.svg").exists()
    assert (tmp_path / "523" / "turns.svg").exists()


def test_second_call_uses_cache_not_network(tmp_path: Path):
    cache = _cache(tmp_path)
    cache.get_map_layers("523", layers=["active"])
    cache.api.get_track_assets.reset_mock()
    cache.fetch_bytes.reset_mock()
    cache.get_map_layers("523", layers=["active"])
    cache.api.get_track_assets.assert_not_called()
    cache.fetch_bytes.assert_not_called()


def test_detail_copy_returned(tmp_path: Path):
    cache = _cache(tmp_path)
    assert "Belgian" in cache.get_detail_copy("523")


def test_unknown_track_returns_empty(tmp_path: Path):
    cache = _cache(tmp_path)
    assert cache.get_map_layers("999", layers=["active"]) == {}
    assert cache.get_detail_copy("999") == ""
