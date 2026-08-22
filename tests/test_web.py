"""Unit tests for the minimal web UI (engine injected, no network)."""

from unittest.mock import MagicMock

import pytest

from src.sync import SyncStats
from src.web import create_app


@pytest.fixture
def engine():
    m = MagicMock()
    m.sync_page.return_value = SyncStats(created=1)
    m.sync_database.return_value = SyncStats(created=2)
    m.sync_search.return_value = SyncStats(updated=3)
    return m


@pytest.fixture
def client(engine):
    app = create_app(engine_factory=lambda **kwargs: engine)
    app.testing = True
    return app.test_client()


class TestIndex:
    def test_renders_form(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert b"<form" in response.data
        assert b'name="mode"' in response.data


class TestSync:
    def test_page_mode(self, client, engine):
        response = client.post("/sync", data={"mode": "page", "target": "abc123"})
        assert response.status_code == 200
        engine.sync_page.assert_called_once_with("abc123")
        assert b"Created" in response.data

    def test_database_mode(self, client, engine):
        response = client.post("/sync", data={"mode": "database", "target": "db1"})
        assert response.status_code == 200
        engine.sync_database.assert_called_once_with("db1")

    def test_search_mode_without_target(self, client, engine):
        response = client.post("/sync", data={"mode": "search"})
        assert response.status_code == 200
        engine.sync_search.assert_called_once_with("")

    def test_page_mode_requires_target(self, client, engine):
        response = client.post("/sync", data={"mode": "page", "target": ""})
        assert response.status_code == 400
        engine.sync_page.assert_not_called()

    def test_unknown_mode_rejected(self, client, engine):
        response = client.post("/sync", data={"mode": "hack"})
        assert response.status_code == 400

    def test_sync_errors_yield_500(self, client, engine):
        engine.sync_page.return_value = SyncStats(errors=1)
        response = client.post("/sync", data={"mode": "page", "target": "abc"})
        assert response.status_code == 500

    def test_factory_exception_yields_500(self, engine):
        def broken_factory(**kwargs):
            raise RuntimeError("environment variable 'ODOO_URL' is not set")

        app = create_app(engine_factory=broken_factory)
        app.testing = True
        response = app.test_client().post("/sync", data={"mode": "search"})
        assert response.status_code == 500
        assert b"ODOO_URL" in response.data

    def test_options_passed_to_factory(self, engine):
        received = {}

        def factory(**kwargs):
            received.update(kwargs)
            return engine

        app = create_app(engine_factory=factory)
        app.testing = True
        app.test_client().post(
            "/sync",
            data={"mode": "search", "dry_run": "on", "include_properties": "on"},
        )
        assert received == {"dry_run": True, "publish": False, "include_properties": True}

    def test_error_message_is_escaped(self, engine):
        def broken_factory(**kwargs):
            raise RuntimeError("<script>alert(1)</script>")

        app = create_app(engine_factory=broken_factory)
        app.testing = True
        response = app.test_client().post("/sync", data={"mode": "search"})
        assert b"<script>alert(1)</script>" not in response.data
        assert b"&lt;script&gt;" in response.data


class TestEngineFromEnv:
    def test_dry_run_needs_only_notion_token(self, monkeypatch):
        import src.web as web

        monkeypatch.setenv("NOTION_TOKEN", "secret_x")
        monkeypatch.delenv("ODOO_URL", raising=False)
        monkeypatch.setattr(web, "NotionClient", MagicMock())
        engine = web._engine_from_env(dry_run=True, publish=False, include_properties=False)
        assert engine._dry_run is True
        assert engine._odoo is None

    def test_missing_variable_raises(self, monkeypatch):
        monkeypatch.delenv("NOTION_TOKEN", raising=False)
        from src.web import _engine_from_env

        with pytest.raises(RuntimeError, match="NOTION_TOKEN"):
            _engine_from_env(dry_run=True, publish=False, include_properties=False)

    def test_full_engine_uses_odoo_and_store(self, monkeypatch, tmp_path):
        import src.web as web

        for name, value in {
            "NOTION_TOKEN": "secret_x",
            "ODOO_URL": "https://odoo.example.com",
            "ODOO_DB": "db",
            "ODOO_USER": "u",
            "ODOO_PASSWORD": "p",
            "SYNC_STORE_PATH": str(tmp_path / "map.db"),
            "ODOO_PARENT_ARTICLE_ID": "7",
        }.items():
            monkeypatch.setenv(name, value)
        monkeypatch.delenv("ODOO_VERSION", raising=False)
        monkeypatch.setattr(web, "NotionClient", MagicMock())
        odoo_cls = MagicMock()
        monkeypatch.setattr(web, "OdooClient", odoo_cls)

        engine = web._engine_from_env(dry_run=False, publish=True, include_properties=False)
        odoo_cls.assert_called_once()
        assert engine._odoo is odoo_cls.return_value
        assert engine._store is not None
        assert engine._parent_id == 7
        assert engine._publish is True
        engine._store.close()

    def test_odoo_version_15_uses_document_page_client(self, monkeypatch, tmp_path):
        import src.web as web

        for name, value in {
            "NOTION_TOKEN": "secret_x",
            "ODOO_URL": "https://odoo.example.com",
            "ODOO_DB": "db",
            "ODOO_USER": "u",
            "ODOO_PASSWORD": "p",
            "SYNC_STORE_PATH": str(tmp_path / "map.db"),
            "ODOO_VERSION": "15",
        }.items():
            monkeypatch.setenv(name, value)
        monkeypatch.setattr(web, "NotionClient", MagicMock())
        legacy_cls = MagicMock()
        monkeypatch.setattr(web, "OdooDocumentPageClient", legacy_cls)

        engine = web._engine_from_env(dry_run=False, publish=False, include_properties=False)
        legacy_cls.assert_called_once()
        assert engine._odoo is legacy_cls.return_value
        engine._store.close()
