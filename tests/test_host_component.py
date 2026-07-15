"""Host helpers — TELEMETRY_DIR env override, watcher freshness reads."""

from pathlib import Path

from app.components.host import (
    relative_time,
    telemetry_dir,
    watcher_last_activity,
)


class TestTelemetryDir:
    def test_env_var_overrides(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TELEMETRY_DIR", str(tmp_path))
        assert telemetry_dir() == tmp_path

    def test_default_is_documents_iracing_telemetry(self, monkeypatch):
        monkeypatch.delenv("TELEMETRY_DIR", raising=False)
        expected = Path.home() / "Documents" / "iRacing" / "telemetry"
        assert telemetry_dir() == expected


class TestWatcherLastActivity:
    def test_none_when_no_log(self, tmp_path):
        assert watcher_last_activity(run_dir=tmp_path) is None

    def test_mtime_when_log_exists(self, tmp_path):
        log = tmp_path / "telemetry-watcher.log"
        log.write_text("scan ok", encoding="utf-8")
        assert watcher_last_activity(run_dir=tmp_path) == log.stat().st_mtime


class TestRelativeTime:
    def test_buckets_exact(self):
        now = 1_000_000.0
        assert relative_time(now - 5, now) == "just now"
        assert relative_time(now - 240, now) == "4m ago"
        assert relative_time(now - 7200, now) == "2h ago"
        assert relative_time(now - 3 * 86400, now) == "3d ago"

    def test_future_timestamps_clamp_to_just_now(self):
        assert relative_time(2_000_000.0, 1_000_000.0) == "just now"
