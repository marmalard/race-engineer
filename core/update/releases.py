"""GitHub Releases lookup for the update channel (B2, spec 5.1/5.4).

PURE update logic: no process control, no Streamlit. Only release TAGS
are ever considered — never a branch ref; unreviewed commits cannot
reach a client. check_for_update is fail-quiet (None on any failure,
logged) because the app must never break over a failed update check.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)

RELEASES_LATEST_URL = (
    "https://api.github.com/repos/marmalard/race-engineer/releases/latest"
)


@dataclass(frozen=True)
class UpdateInfo:
    tag: str
    zip_url: str
    sha256: str
    notes: str


def parse_tag(tag: str) -> tuple[int, int, int] | None:
    """'v1.2.3' or '1.2.3' -> (1, 2, 3); None when malformed."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", tag.strip())
    if match is None:
        return None
    return tuple(int(g) for g in match.groups())  # type: ignore[return-value]


def _default_get(url: str):
    import httpx

    return httpx.get(url, follow_redirects=True, timeout=30.0)


def _sha_for(sums_text: str, zip_name: str) -> str | None:
    """The 64-hex digest on the SHA256SUMS line naming zip_name."""
    for line in sums_text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == zip_name:
            if re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
                return parts[0].lower()
    return None


def check_for_update(
    current_version: str, *, get: Callable | None = None
) -> UpdateInfo | None:
    """The latest release, when strictly newer than current_version and
    carrying both the zip asset and its SHA256SUMS. None otherwise."""
    get = get or _default_get
    try:
        resp = get(RELEASES_LATEST_URL)
        if resp.status_code != 200:
            return None
        release = resp.json()
        tag = release.get("tag_name", "")
        latest, current = parse_tag(tag), parse_tag(current_version)
        if latest is None or current is None or latest <= current:
            return None
        assets = {a.get("name"): a for a in release.get("assets", [])}
        zip_name = f"race-engineer-{tag}.zip"
        zip_asset = assets.get(zip_name)
        sums_asset = assets.get("SHA256SUMS")
        if zip_asset is None or sums_asset is None:
            return None  # no checksum, no offer (spec 5.4)
        sums_resp = get(sums_asset["browser_download_url"])
        if sums_resp.status_code != 200:
            return None
        sha = _sha_for(sums_resp.text, zip_name)
        if sha is None:
            return None
        return UpdateInfo(
            tag=tag,
            zip_url=zip_asset["browser_download_url"],
            sha256=sha,
            notes=release.get("body") or "",
        )
    except Exception:  # noqa: BLE001 — fail-quiet by contract
        logger.warning("update check failed", exc_info=True)
        return None


def download_zip(url: str, *, get: Callable | None = None) -> bytes:
    """The release zip bytes; raises on any HTTP failure (the caller's
    update flow reports it — downloading is already user-consented)."""
    get = get or _default_get
    resp = get(url)
    if resp.status_code != 200:
        raise RuntimeError(f"download failed: HTTP {resp.status_code} for {url}")
    return resp.content
