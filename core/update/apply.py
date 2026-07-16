"""Verify-then-swap update application (B2, spec 5.1).

Order of operations is the safety story: sha256 gate BEFORE any write,
full extraction + layout validation in a temp dir, and only then the
selective swap of RELEASE_ENTRIES into the install root. data/, .env,
.venv and uv.exe are preserved by never being swap targets.
"""

from __future__ import annotations

import hashlib
import io
import shutil
import tempfile
import zipfile
from pathlib import Path

from core.update.manifest import RELEASE_ENTRIES


class UpdateVerificationError(Exception):
    """The downloaded zip does not match the published SHA-256."""


class UpdateApplyError(Exception):
    """The zip is malformed or its layout is not a release zip."""


def apply_update(
    zip_bytes: bytes, expected_sha256: str, install_root: Path
) -> None:
    """Verify zip_bytes against expected_sha256, then selectively swap
    RELEASE_ENTRIES into install_root. Raises before writing anything on
    verification or layout failure."""
    digest = hashlib.sha256(zip_bytes).hexdigest()
    if digest != expected_sha256.strip().lower():
        raise UpdateVerificationError(
            f"sha256 mismatch: got {digest}, expected {expected_sha256}"
        )

    install_root = Path(install_root)
    with tempfile.TemporaryDirectory(prefix="race-engineer-update-") as td:
        staged = Path(td)
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                for name in zf.namelist():
                    part = Path(name)
                    if part.is_absolute() or ".." in part.parts:
                        raise UpdateApplyError(f"unsafe zip member: {name}")
                zf.extractall(staged)
        except zipfile.BadZipFile as exc:
            raise UpdateApplyError(f"malformed zip: {exc}") from exc

        missing = [e for e in RELEASE_ENTRIES if not (staged / e).exists()]
        if missing:
            raise UpdateApplyError(f"zip missing expected entries: {missing}")

        # Validate-then-swap: nothing above touched install_root.
        for entry in RELEASE_ENTRIES:
            dest = install_root / entry
            if dest.is_dir():
                shutil.rmtree(dest)
            elif dest.exists():
                dest.unlink()
            shutil.move(str(staged / entry), str(dest))
