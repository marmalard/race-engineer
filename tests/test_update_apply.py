"""apply_update (the crux, spec 9): SHA mismatch writes NOTHING;
selective swap replaces code and preserves data/, .env, .venv."""

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from core.update.apply import (
    UpdateApplyError,
    UpdateVerificationError,
    apply_update,
)


def _make_zip(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _good_zip() -> bytes:
    return _make_zip({
        "app/pages/new.py": "new app code",
        "core/update/new.py": "new core code",
        "scripts/new.py": "new script",
        "pyproject.toml": '[project]\nversion = "0.2.0"\n',
        "uv.lock": "new lock",
        ".python-version": "3.14",
    })


def _install_root(tmp_path: Path) -> Path:
    root = tmp_path / "RaceEngineer"
    for entry in ("app", "core", "scripts"):
        (root / entry).mkdir(parents=True)
        (root / entry / "old.py").write_text("old", encoding="utf-8")
    (root / "pyproject.toml").write_text("old", encoding="utf-8")
    (root / "uv.lock").write_text("old", encoding="utf-8")
    (root / ".python-version").write_text("old", encoding="utf-8")
    # The preserved trio:
    (root / "data").mkdir()
    (root / "data" / "races.db").write_bytes(b"race history")
    (root / ".env").write_text("ANTHROPIC_API_KEY=sk-friend\n", encoding="utf-8")
    (root / ".venv").mkdir()
    (root / ".venv" / "python.exe").write_bytes(b"venv bits")
    (root / "uv.exe").write_bytes(b"uv bits")
    return root


def _sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


class TestVerification:
    def test_sha_mismatch_raises_and_writes_nothing(self, tmp_path):
        root = _install_root(tmp_path)
        blob = _good_zip()
        with pytest.raises(UpdateVerificationError):
            apply_update(blob, "0" * 64, root)
        # NOTHING changed — old code intact.
        assert (root / "app" / "old.py").read_text(encoding="utf-8") == "old"
        assert (root / "pyproject.toml").read_text(encoding="utf-8") == "old"

    def test_sha_comparison_is_case_insensitive(self, tmp_path):
        root = _install_root(tmp_path)
        blob = _good_zip()
        apply_update(blob, _sha(blob).upper(), root)
        assert (root / "app" / "pages" / "new.py").exists()


    def test_empty_expected_digest_raises_verification_error(self, tmp_path):
        root = _install_root(tmp_path)
        blob = _good_zip()
        with pytest.raises(UpdateVerificationError):
            apply_update(blob, "", root)
        assert (root / "app" / "old.py").exists()

    def test_none_expected_digest_raises_verification_error(self, tmp_path):
        root = _install_root(tmp_path)
        blob = _good_zip()
        with pytest.raises(UpdateVerificationError):
            apply_update(blob, None, root)
        assert (root / "app" / "old.py").exists()


class TestSelectiveSwap:
    def test_swap_replaces_code_entries(self, tmp_path):
        root = _install_root(tmp_path)
        blob = _good_zip()
        apply_update(blob, _sha(blob), root)
        assert not (root / "app" / "old.py").exists()
        assert (root / "app" / "pages" / "new.py").read_text(
            encoding="utf-8"
        ) == "new app code"
        assert (root / "uv.lock").read_text(encoding="utf-8") == "new lock"

    def test_swap_preserves_data_env_venv_and_uv(self, tmp_path):
        root = _install_root(tmp_path)
        blob = _good_zip()
        apply_update(blob, _sha(blob), root)
        assert (root / "data" / "races.db").read_bytes() == b"race history"
        assert (root / ".env").read_text(encoding="utf-8") == (
            "ANTHROPIC_API_KEY=sk-friend\n"
        )
        assert (root / ".venv" / "python.exe").read_bytes() == b"venv bits"
        assert (root / "uv.exe").read_bytes() == b"uv bits"


class TestMalformedInput:
    def test_not_a_zip_raises_apply_error_and_writes_nothing(self, tmp_path):
        root = _install_root(tmp_path)
        blob = b"definitely not a zip"
        with pytest.raises(UpdateApplyError):
            apply_update(blob, _sha(blob), root)
        assert (root / "app" / "old.py").exists()

    def test_zip_missing_entries_raises_and_writes_nothing(self, tmp_path):
        root = _install_root(tmp_path)
        blob = _make_zip({"app/pages/new.py": "only the app dir"})
        with pytest.raises(UpdateApplyError):
            apply_update(blob, _sha(blob), root)
        assert (root / "core" / "old.py").exists()

    def test_zip_slip_member_raises(self, tmp_path):
        root = _install_root(tmp_path)
        blob = _make_zip({"../evil.py": "escape"})
        with pytest.raises(UpdateApplyError):
            apply_update(blob, _sha(blob), root)
