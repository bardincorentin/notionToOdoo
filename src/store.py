"""Persistent Notion → Odoo ID mapping backed by a SQLite sidecar file.

Stores ``notion_page_id → odoo_article_id`` so that syncs are idempotent
even when pages are renamed, eliminating the name-collision issues of the
purely name-based upsert. When a page has no mapping yet, the sync engine
falls back to the legacy name-based lookup and records the result here,
which transparently migrates existing installations.
"""

import logging
import sqlite3
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

DEFAULT_STORE_PATH = ".notion_odoo_map.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS article_map (
    notion_page_id  TEXT PRIMARY KEY,
    odoo_article_id INTEGER NOT NULL,
    synced_at       TEXT NOT NULL
)
"""


def normalize_page_id(page_id: str) -> str:
    """Canonicalise a Notion page ID (lowercase, no dashes).

    Notion accepts both dashed UUIDs and 32-char hex strings; storing a
    single canonical form makes lookups work regardless of input format.
    """
    return page_id.replace("-", "").strip().lower()


class ArticleStore:
    """SQLite-backed mapping of Notion page IDs to Odoo article IDs.

    Args:
        path: Path of the SQLite database file. Use ``":memory:"`` for an
            ephemeral store (tests, dry runs).
    """

    def __init__(self, path: str = DEFAULT_STORE_PATH):
        self._path = path
        self._conn = sqlite3.connect(path)
        self._conn.execute(_SCHEMA)
        self._conn.commit()
        logger.debug("Article store opened at %s", path)

    # ------------------------------------------------------------------ CRUD

    def get(self, notion_page_id: str) -> int | None:
        """Return the mapped Odoo article ID, or None if unknown."""
        row = self._conn.execute(
            "SELECT odoo_article_id FROM article_map WHERE notion_page_id = ?",
            (normalize_page_id(notion_page_id),),
        ).fetchone()
        return row[0] if row else None

    def set(self, notion_page_id: str, odoo_article_id: int) -> None:
        """Insert or update the mapping for a Notion page."""
        self._conn.execute(
            "INSERT INTO article_map (notion_page_id, odoo_article_id, synced_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(notion_page_id) DO UPDATE SET "
            "odoo_article_id = excluded.odoo_article_id, synced_at = excluded.synced_at",
            (
                normalize_page_id(notion_page_id),
                odoo_article_id,
                datetime.now(UTC).isoformat(),
            ),
        )
        self._conn.commit()

    def remove(self, notion_page_id: str) -> None:
        """Delete the mapping for a Notion page (no-op if absent)."""
        self._conn.execute(
            "DELETE FROM article_map WHERE notion_page_id = ?",
            (normalize_page_id(notion_page_id),),
        )
        self._conn.commit()

    def __len__(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM article_map").fetchone()[0]

    # ------------------------------------------------------------- lifecycle

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ArticleStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
