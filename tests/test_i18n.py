"""Unit tests for the FR/EN i18n helper."""

from src.i18n import _, get_lang, translate
from src.sync import SyncStats


class TestGetLang:
    def test_french_from_lang(self, monkeypatch):
        monkeypatch.delenv("LANGUAGE", raising=False)
        monkeypatch.delenv("LC_ALL", raising=False)
        monkeypatch.setenv("LANG", "fr_FR.UTF-8")
        assert get_lang() == "fr"

    def test_english_from_lang(self, monkeypatch):
        monkeypatch.delenv("LANGUAGE", raising=False)
        monkeypatch.delenv("LC_ALL", raising=False)
        monkeypatch.setenv("LANG", "en_US.UTF-8")
        assert get_lang() == "en"

    def test_language_takes_precedence(self, monkeypatch):
        monkeypatch.setenv("LANGUAGE", "fr")
        monkeypatch.setenv("LANG", "en_US.UTF-8")
        assert get_lang() == "fr"

    def test_defaults_to_english(self, monkeypatch):
        for var in ("LANGUAGE", "LC_ALL", "LANG"):
            monkeypatch.delenv(var, raising=False)
        assert get_lang() == "en"

    def test_non_french_locale_is_english(self, monkeypatch):
        monkeypatch.delenv("LANGUAGE", raising=False)
        monkeypatch.delenv("LC_ALL", raising=False)
        monkeypatch.setenv("LANG", "de_DE.UTF-8")
        assert get_lang() == "en"


class TestTranslate:
    def test_english_passthrough(self, monkeypatch):
        monkeypatch.setenv("LANGUAGE", "en")
        assert translate("Sync complete:") == "Sync complete:"

    def test_french_translation(self, monkeypatch):
        monkeypatch.setenv("LANGUAGE", "fr")
        assert translate("Sync complete:") == "Synchronisation terminée :"

    def test_formatting_placeholders(self, monkeypatch):
        monkeypatch.setenv("LANGUAGE", "fr")
        msg = translate("ERROR: environment variable '{name}' is not set.", name="ODOO_URL")
        assert "ODOO_URL" in msg
        assert msg.startswith("ERREUR")

    def test_untranslated_message_passes_through_in_french(self, monkeypatch):
        monkeypatch.setenv("LANGUAGE", "fr")
        assert translate("some untranslated text") == "some untranslated text"

    def test_underscore_alias(self, monkeypatch):
        monkeypatch.setenv("LANGUAGE", "fr")
        assert _("Created") == "Créés"


class TestReportTranslation:
    def test_report_in_french(self, monkeypatch):
        monkeypatch.setenv("LANGUAGE", "fr")
        report = SyncStats(created=2).report()
        assert "Synchronisation terminée :" in report
        assert "Créés" in report

    def test_report_in_english(self, monkeypatch):
        monkeypatch.setenv("LANGUAGE", "en")
        report = SyncStats(created=2).report()
        assert "Sync complete:" in report
        assert "Created" in report
