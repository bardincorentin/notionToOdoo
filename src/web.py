"""Minimal web UI to trigger a Notion → Odoo sync from a browser.

Run with:

    pip install -r requirements-web.txt
    flask --app src.web run          # or: python -m src.web

Connection parameters come from the same environment variables as the CLI
(see ``.env.example``). This is a thin form over :class:`~src.sync.SyncEngine`;
the sync runs synchronously in the request, so it is meant for small
workspaces and manual, occasional use, not as a public service.
"""

import html
import logging
import os

from flask import Flask, request

from .notion.client import NotionClient
from .odoo.client import OdooClient, OdooDocumentPageClient
from .store import DEFAULT_STORE_PATH, ArticleStore
from .sync import SyncEngine, SyncStats

logger = logging.getLogger(__name__)

_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>notionToOdoo</title>
<style>
body {{ font-family: sans-serif; max-width: 40rem; margin: 2rem auto; color: #222; }}
label {{ display: block; margin-top: 0.8rem; }}
input[type=text] {{ width: 100%; padding: 0.4rem; }}
button {{ margin-top: 1rem; padding: 0.5rem 1.2rem; }}
.error {{ color: #cf222e; }}
pre {{ background: #f5f5f5; padding: 1rem; }}
</style>
</head>
<body>
<h1>notionToOdoo</h1>
{content}
<form method="post" action="/sync">
  <label>Mode
    <select name="mode">
      <option value="page">page</option>
      <option value="database">database</option>
      <option value="search">search</option>
    </select>
  </label>
  <label>Target (page/database ID, or search query)
    <input type="text" name="target" placeholder="Notion ID or search query"/>
  </label>
  <label><input type="checkbox" name="dry_run"/> Dry run (do not write to Odoo)</label>
  <label><input type="checkbox" name="publish"/> Publish imported articles</label>
  <label><input type="checkbox" name="include_properties"/> Include page properties</label>
  <button type="submit">Sync</button>
</form>
</body>
</html>
"""


def _engine_from_env(*, dry_run: bool, publish: bool, include_properties: bool) -> SyncEngine:
    """Build a SyncEngine from environment variables (same ones as the CLI)."""

    def require(name: str) -> str:
        value = os.getenv(name)
        if not value:
            raise RuntimeError(f"environment variable '{name}' is not set")
        return value

    notion = NotionClient(
        token=require("NOTION_TOKEN"), timeout=int(os.getenv("NOTION_TIMEOUT", "30"))
    )

    odoo = None
    store = None
    if not dry_run:
        client_cls = OdooDocumentPageClient if os.getenv("ODOO_VERSION") == "15" else OdooClient
        odoo = client_cls(
            url=require("ODOO_URL"),
            database=require("ODOO_DB"),
            username=require("ODOO_USER"),
            password=require("ODOO_PASSWORD"),
            timeout=int(os.getenv("ODOO_TIMEOUT", "30")),
        )
        store = ArticleStore(os.getenv("SYNC_STORE_PATH", DEFAULT_STORE_PATH))

    parent_id = int(os.getenv("ODOO_PARENT_ARTICLE_ID", "0")) or None
    return SyncEngine(
        notion,
        odoo,  # type: ignore[arg-type]
        odoo_parent_id=parent_id,
        publish=publish,
        dry_run=dry_run,
        store=store,
        include_properties=include_properties,
    )


def _render(content: str = "") -> str:
    return _PAGE.format(content=content)


def _stats_html(stats: SyncStats) -> str:
    return f"<h2>Result</h2><pre>{html.escape(stats.report())}</pre>"


def create_app(engine_factory=None) -> Flask:
    """Create the Flask app.

    Args:
        engine_factory: Optional callable with the same signature as
            :func:`_engine_from_env`, injected in tests to avoid real clients.
    """
    app = Flask(__name__)
    factory = engine_factory or _engine_from_env

    @app.get("/")
    def index() -> str:
        return _render()

    @app.post("/sync")
    def sync() -> tuple[str, int]:
        mode = request.form.get("mode", "search")
        target = request.form.get("target", "").strip()

        if mode not in ("page", "database", "search"):
            return _render(f'<p class="error">Unknown mode: {html.escape(mode)}</p>'), 400
        if mode in ("page", "database") and not target:
            return _render(f'<p class="error">Mode {mode!r} requires a target ID.</p>'), 400

        try:
            engine = factory(
                dry_run="dry_run" in request.form,
                publish="publish" in request.form,
                include_properties="include_properties" in request.form,
            )
            if mode == "page":
                stats = engine.sync_page(target)
            elif mode == "database":
                stats = engine.sync_database(target)
            else:
                stats = engine.sync_search(target)
        except Exception as exc:
            logger.exception("Web sync failed")
            return _render(f'<p class="error">Sync failed: {html.escape(str(exc))}</p>'), 500

        status = 500 if stats.errors else 200
        return _render(_stats_html(stats)), status

    return app


if __name__ == "__main__":  # pragma: no cover
    create_app().run(
        host=os.getenv("WEB_HOST", "127.0.0.1"), port=int(os.getenv("WEB_PORT", "5000"))
    )
