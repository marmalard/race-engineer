"""env_setup owns the only knowledge of which .env keys are required
(spec 4). Values are double-quoted with escaping so passwords containing
spaces/#/quotes survive the python-dotenv parse."""

from core.config import env_setup
from core.config.env_setup import (
    REQUIRED,
    is_complete,
    read_env,
    write_env,
)


class TestRequiredContract:
    def test_required_keys_exact(self):
        assert REQUIRED == (
            "ANTHROPIC_API_KEY", "IRACING_USERNAME", "IRACING_PASSWORD",
        )


class TestIsComplete:
    def test_missing_file_is_incomplete(self, tmp_path):
        assert not is_complete(tmp_path / "no-such.env")

    def test_partial_file_is_incomplete(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            "ANTHROPIC_API_KEY=sk-x\nIRACING_USERNAME=me\nIRACING_PASSWORD=\n",
            encoding="utf-8",
        )
        assert not is_complete(env)

    def test_full_file_is_complete(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            "ANTHROPIC_API_KEY=sk-x\nIRACING_USERNAME=me\n"
            "IRACING_PASSWORD=pw\n",
            encoding="utf-8",
        )
        assert is_complete(env)


class TestReadEnv:
    def test_skips_comments_and_blanks(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            "# iRacing OAuth\n\nIRACING_USERNAME=me\n", encoding="utf-8"
        )
        assert read_env(env) == {"IRACING_USERNAME": "me"}

    def test_missing_file_reads_empty(self, tmp_path):
        assert read_env(tmp_path / "nope.env") == {}


class TestWriteEnv:
    def test_round_trip_nasty_password(self, tmp_path, monkeypatch):
        monkeypatch.setattr(env_setup.os, "environ", {})
        env = tmp_path / ".env"
        nasty = 'pa ss#w"ord\\n'  # space, hash, quote, literal backslash-n
        write_env({"IRACING_PASSWORD": nasty}, env, defaults={})
        assert read_env(env)["IRACING_PASSWORD"] == nasty

    def test_defaults_fill_missing_keys(self, tmp_path, monkeypatch):
        monkeypatch.setattr(env_setup.os, "environ", {})
        env = tmp_path / ".env"
        write_env(
            {"ANTHROPIC_API_KEY": "sk-x"},
            env,
            defaults={"IRACING_CLIENT_ID": "founder-id"},
        )
        assert read_env(env)["IRACING_CLIENT_ID"] == "founder-id"

    def test_existing_override_is_not_clobbered(self, tmp_path, monkeypatch):
        # A friend who registers their own OAuth app keeps it (spec 4).
        monkeypatch.setattr(env_setup.os, "environ", {})
        env = tmp_path / ".env"
        env.write_text("IRACING_CLIENT_ID=their-own\n", encoding="utf-8")
        write_env(
            {"ANTHROPIC_API_KEY": "sk-x"},
            env,
            defaults={"IRACING_CLIENT_ID": "founder-id"},
        )
        assert read_env(env)["IRACING_CLIENT_ID"] == "their-own"

    def test_empty_default_is_not_written(self, tmp_path, monkeypatch):
        # Public checkout without _baked.py: don't write blank cred keys.
        monkeypatch.setattr(env_setup.os, "environ", {})
        env = tmp_path / ".env"
        write_env(
            {"ANTHROPIC_API_KEY": "sk-x"}, env,
            defaults={"IRACING_CLIENT_ID": ""},
        )
        assert "IRACING_CLIENT_ID" not in read_env(env)

    def test_write_updates_process_env(self, tmp_path, monkeypatch):
        # The running app must pick up saved keys without a restart
        # (Setup page saves then st.rerun()s -- no fresh load_dotenv).
        fake_environ: dict = {}
        monkeypatch.setattr(env_setup.os, "environ", fake_environ)
        write_env({"ANTHROPIC_API_KEY": "sk-x"}, tmp_path / ".env", defaults={})
        assert fake_environ["ANTHROPIC_API_KEY"] == "sk-x"

    def test_preserves_unrelated_existing_keys(self, tmp_path, monkeypatch):
        monkeypatch.setattr(env_setup.os, "environ", {})
        env = tmp_path / ".env"
        env.write_text("SOME_OTHER=keepme\n", encoding="utf-8")
        write_env({"ANTHROPIC_API_KEY": "sk-x"}, env, defaults={})
        assert read_env(env)["SOME_OTHER"] == "keepme"
