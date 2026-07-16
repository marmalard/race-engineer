"""Version source of truth + release manifest (B2).

get_version reads the real pyproject (single version source, spec 5.1);
bump math and layout detection are pure.
"""

from pathlib import Path

import pytest

from core.update.manifest import RELEASE_ENTRIES, is_installed_layout
from core.update.version import bump_version, get_version

_ROOT = Path(__file__).resolve().parent.parent


class TestGetVersion:
    def test_reads_the_real_pyproject(self):
        # Whatever the current version is, it parses as x.y.z.
        version = get_version()
        assert bump_version(version, "patch")  # round-trips through the parser

    def test_reads_an_explicit_pyproject(self, tmp_path):
        py = tmp_path / "pyproject.toml"
        py.write_text('[project]\nname = "x"\nversion = "1.2.3"\n', encoding="utf-8")
        assert get_version(py) == "1.2.3"


class TestBumpVersion:
    def test_patch(self):
        assert bump_version("0.1.0", "patch") == "0.1.1"

    def test_minor_resets_patch(self):
        assert bump_version("0.1.7", "minor") == "0.2.0"

    def test_malformed_version_raises(self):
        with pytest.raises(ValueError):
            bump_version("0.1", "patch")

    def test_unknown_part_raises(self):
        with pytest.raises(ValueError):
            bump_version("0.1.0", "major-ish")


class TestManifest:
    def test_release_entries_exact(self):
        # The swap/zip whitelist -- data/, .env, .venv are preserved by
        # NOT being here. Changing this list changes what an update
        # replaces on a friend's machine.
        assert RELEASE_ENTRIES == (
            "app", "core", "scripts",
            "pyproject.toml", "uv.lock", ".python-version",
        )

    def test_release_entries_exist_in_this_checkout(self):
        for entry in RELEASE_ENTRIES:
            assert (_ROOT / entry).exists(), entry

    def test_dev_checkout_is_not_installed_layout(self):
        assert not is_installed_layout(_ROOT)

    def test_uv_exe_marks_installed_layout(self, tmp_path):
        (tmp_path / "uv.exe").write_bytes(b"")
        assert is_installed_layout(tmp_path)
