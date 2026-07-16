"""UI preference store — unit toggle survives reloads via a host file."""

from app.components.prefs import load_unit_system, save_unit_system


class TestUnitSystemPrefs:
    def test_round_trip(self, tmp_path):
        p = tmp_path / "ui_prefs.json"
        save_unit_system("Imperial", path=p)
        assert load_unit_system(path=p) == "Imperial"
        save_unit_system("Metric", path=p)
        assert load_unit_system(path=p) == "Metric"

    def test_missing_file_defaults_metric(self, tmp_path):
        assert load_unit_system(path=tmp_path / "nope.json") == "Metric"

    def test_corrupt_file_defaults_metric(self, tmp_path):
        p = tmp_path / "ui_prefs.json"
        p.write_text("not json{{{", encoding="utf-8")
        assert load_unit_system(path=p) == "Metric"

    def test_invalid_stored_value_defaults_metric(self, tmp_path):
        p = tmp_path / "ui_prefs.json"
        p.write_text('{"unit_system": "Furlongs"}', encoding="utf-8")
        assert load_unit_system(path=p) == "Metric"

    def test_save_rejects_invalid_values_silently(self, tmp_path):
        p = tmp_path / "ui_prefs.json"
        save_unit_system("Furlongs", path=p)
        assert not p.exists()

    def test_save_creates_parent_dirs(self, tmp_path):
        p = tmp_path / "deep" / "ui_prefs.json"
        save_unit_system("Imperial", path=p)
        assert load_unit_system(path=p) == "Imperial"
