"""build_release: bump math delegated to core.update.version (tested
there); here we pin pyproject rewriting, zip contents (RELEASE_ENTRIES
in, data//.env/.venv/__pycache__ out), the SHA256SUMS line, and the
baked-credential generator."""

import hashlib
import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(
        name, _ROOT / "scripts" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module)  # 3.14: dataclasses need registration
    spec.loader.exec_module(module)
    return module


build_release = _load_script("build_release")


def _fake_checkout(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    for entry in ("app", "core", "scripts"):
        (root / entry).mkdir(parents=True)
        (root / entry / "keep.py").write_text("# code\n", encoding="utf-8")
    (root / "core" / "sub").mkdir()
    (root / "core" / "sub" / "deep.py").write_text("# nested\n", encoding="utf-8")
    (root / "core" / "__pycache__").mkdir()
    (root / "core" / "__pycache__" / "keep.cpython-314.pyc").write_bytes(b"x")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    (root / "uv.lock").write_text("lock\n", encoding="utf-8")
    (root / ".python-version").write_text("3.14\n", encoding="utf-8")
    # Things that must NEVER ship:
    (root / "data").mkdir()
    (root / "data" / "races.db").write_bytes(b"secret history")
    (root / ".env").write_text("ANTHROPIC_API_KEY=sk-real\n", encoding="utf-8")
    (root / ".venv").mkdir()
    (root / ".venv" / "big.dll").write_bytes(b"x" * 10)
    return root


class TestWritePyprojectVersion:
    def test_rewrites_only_the_version_line(self, tmp_path):
        py = tmp_path / "pyproject.toml"
        py.write_text(
            '[project]\nname = "x"\nversion = "0.1.0"\n', encoding="utf-8"
        )
        build_release.write_pyproject_version(py, "0.2.0")
        text = py.read_text(encoding="utf-8")
        assert 'version = "0.2.0"' in text
        assert 'name = "x"' in text

    def test_missing_version_line_raises(self, tmp_path):
        py = tmp_path / "pyproject.toml"
        py.write_text('[project]\nname = "x"\n', encoding="utf-8")
        with pytest.raises(ValueError):
            build_release.write_pyproject_version(py, "0.2.0")


class TestBuildZip:
    def test_zip_contains_code_and_excludes_private_files(self, tmp_path):
        root = _fake_checkout(tmp_path)
        out = tmp_path / "dist" / "race-engineer-v0.1.0.zip"
        build_release.build_zip(root, out)
        names = zipfile.ZipFile(out).namelist()
        assert "app/keep.py" in names
        assert "core/keep.py" in names
        assert "core/sub/deep.py" in names
        assert "scripts/keep.py" in names
        assert "pyproject.toml" in names
        assert "uv.lock" in names
        assert ".python-version" in names
        for name in names:
            assert not name.startswith("data/")
            assert not name.startswith(".venv/")
            assert ".env" not in name
            assert "__pycache__" not in name
            assert not name.endswith(".pyc")

    def test_returned_sha_matches_the_file(self, tmp_path):
        root = _fake_checkout(tmp_path)
        out = tmp_path / "dist" / "z.zip"
        sha = build_release.build_zip(root, out)
        assert sha == hashlib.sha256(out.read_bytes()).hexdigest()


class TestSha256SumsLine:
    def test_two_space_gnu_format(self):
        line = build_release.sha256sums_line("ab" * 32, "race-engineer-v0.2.0.zip")
        assert line == f"{'ab' * 32}  race-engineer-v0.2.0.zip\n"


class TestRefreshBakedCredentials:
    def test_writes_importable_module_from_env(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            "IRACING_CLIENT_ID=1226848-pwlimited\n"
            "IRACING_CLIENT_SECRET=sekrit\n",
            encoding="utf-8",
        )
        out = tmp_path / "_baked.py"
        assert build_release.refresh_baked_credentials(env, out) is True
        ns: dict = {}
        exec(out.read_text(encoding="utf-8"), ns)
        assert ns["BAKED_DEFAULTS"] == {
            "IRACING_CLIENT_ID": "1226848-pwlimited",
            "IRACING_CLIENT_SECRET": "sekrit",
        }

    def test_missing_credential_writes_nothing(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("ANTHROPIC_API_KEY=sk-x\n", encoding="utf-8")
        out = tmp_path / "_baked.py"
        assert build_release.refresh_baked_credentials(env, out) is False
        assert not out.exists()
