"""Download and cache official iRacing track map SVGs and descriptions.

The Data API's track/assets endpoint provides layered SVG maps per track
(background / active / pitroad / start-finish / turns). The 'turns' layer
carries official turn numbers — we display these rather than inventing
numbering. Assets are iRacing-copyrighted: cache locally for personal
use, never redistribute.
"""

import json
from pathlib import Path
from typing import Callable

import requests


def _default_fetch(url: str) -> bytes:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.content


class TrackAssetCache:
    """Lazily downloads track map layers; serves from disk afterwards."""

    def __init__(
        self,
        api,  # IRacingAPIClient with get_track_assets()
        cache_dir: Path,
        fetch_bytes: Callable[[str], bytes] = _default_fetch,
    ):
        self.api = api
        self.cache_dir = Path(cache_dir)
        self.fetch_bytes = fetch_bytes
        self._assets: dict | None = None

    def _track_dir(self, track_id: str) -> Path:
        return self.cache_dir / str(track_id)

    def _load_assets(self) -> dict:
        """Asset index, cached on disk so the API is hit once per machine."""
        index_path = self.cache_dir / "assets_index.json"
        if self._assets is None:
            if index_path.exists():
                self._assets = json.loads(index_path.read_text(encoding="utf-8"))
            else:
                self._assets = self.api.get_track_assets()
                index_path.parent.mkdir(parents=True, exist_ok=True)
                index_path.write_text(json.dumps(self._assets), encoding="utf-8")
        return self._assets

    def get_map_layers(
        self, track_id: str, layers: list[str] = ("active", "turns", "start-finish")
    ) -> dict[str, Path]:
        """Local SVG paths per requested layer; downloads on first access."""
        track_dir = self._track_dir(track_id)
        result: dict[str, Path] = {}
        missing = []
        for layer in layers:
            path = track_dir / f"{layer}.svg"
            if path.exists():
                result[layer] = path
            else:
                missing.append(layer)

        if not missing:
            return result

        entry = self._load_assets().get(str(track_id))
        if entry is None:
            return result
        base = entry.get("track_map", "")
        layer_files = entry.get("track_map_layers", {})
        track_dir.mkdir(parents=True, exist_ok=True)
        for layer in missing:
            filename = layer_files.get(layer)
            if not filename:
                continue
            path = track_dir / f"{layer}.svg"
            path.write_bytes(self.fetch_bytes(base + filename))
            result[layer] = path
        return result

    def get_detail_copy(self, track_id: str) -> str:
        """Official track description HTML (scouting prompt grounding)."""
        entry = self._load_assets().get(str(track_id))
        return (entry or {}).get("detail_copy", "") or ""
