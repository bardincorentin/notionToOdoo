"""Orchestrates the Notion → Odoo Knowledge synchronisation."""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from .i18n import _
from .notion.client import NotionClient
from .notion.parser import NotionParser
from .odoo.client import OdooClient
from .store import ArticleStore

logger = logging.getLogger(__name__)


@dataclass
class SyncItem:
    """Outcome of syncing a single Notion page (used by the HTML report)."""

    title: str
    notion_page_id: str
    action: str  # "created" | "updated" | "skipped" | "error"
    odoo_article_id: int | None = None
    detail: str = ""


@dataclass
class SyncStats:
    """Counters collected during a sync run."""

    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    error_messages: list[str] = field(default_factory=list)
    items: list[SyncItem] = field(default_factory=list)

    def add_item(
        self,
        title: str,
        notion_page_id: str,
        action: str,
        odoo_article_id: int | None = None,
        detail: str = "",
    ) -> None:
        self.items.append(SyncItem(title, notion_page_id, action, odoo_article_id, detail))

    def report(self) -> str:
        lines = [
            _("Sync complete:"),
            f"  {_('Created'):<12}: {self.created}",
            f"  {_('Updated'):<12}: {self.updated}",
            f"  {_('Skipped'):<12}: {self.skipped}",
            f"  {_('Errors'):<12}: {self.errors}",
        ]
        for msg in self.error_messages:
            lines.append(f"  ⚠  {msg}")
        return "\n".join(lines)


class SyncEngine:
    """Pulls content from Notion and pushes it into Odoo Knowledge.

    Args:
        notion: Authenticated :class:`NotionClient`.
        odoo: Authenticated :class:`OdooClient`.
        odoo_parent_id: Optional Odoo article ID under which all imported
            articles will be nested.
        publish: Whether to mark imported articles as published.
        dry_run: If True, parse and log without writing to Odoo.
        store: Optional :class:`ArticleStore` mapping Notion page IDs to Odoo
            article IDs. When provided, upserts resolve through the store
            first and fall back to the legacy name-based lookup (which
            migrates existing articles into the store).
        since: Only sync pages whose Notion ``last_edited_time`` is on or
            after this datetime; older pages are counted as skipped (child
            pages are still visited).
        include_properties: Prepend a metadata table with the Notion page
            properties (tags, dates, status…) to the article body.
        rehoster: Optional :class:`~src.rehost.ImageRehoster`; when provided,
            Notion-hosted images (whose URLs expire) are downloaded and
            re-uploaded as Odoo attachments before the article is written.
    """

    def __init__(
        self,
        notion: NotionClient,
        odoo: OdooClient,
        *,
        odoo_parent_id: int | None = None,
        publish: bool = False,
        dry_run: bool = False,
        store: ArticleStore | None = None,
        since: datetime | None = None,
        include_properties: bool = False,
        rehoster=None,
    ):
        self._notion = notion
        self._odoo = odoo
        self._parent_id = odoo_parent_id
        self._publish = publish
        self._dry_run = dry_run
        self._store = store
        self._since = since
        self._include_properties = include_properties
        self._rehoster = rehoster
        self._parser = NotionParser()

    # ----------------------------------------------------------------- public API

    def sync_page(self, page_id: str) -> SyncStats:
        """Sync a single Notion page to Odoo Knowledge.

        Args:
            page_id: Notion page UUID.

        Returns:
            :class:`SyncStats` with results of this sync.
        """
        stats = SyncStats()
        try:
            self._sync_page_recursive(page_id, parent_odoo_id=self._parent_id, stats=stats)
        except Exception as exc:
            logger.exception("Unexpected error syncing page %s", page_id)
            stats.errors += 1
            stats.error_messages.append(str(exc))
            stats.add_item("(unknown)", page_id, "error", detail=str(exc))
        return stats

    def sync_database(self, database_id: str) -> SyncStats:
        """Sync all pages in a Notion database to Odoo Knowledge.

        Args:
            database_id: Notion database UUID.

        Returns:
            :class:`SyncStats` with aggregated results.
        """
        stats = SyncStats()
        logger.info("Querying Notion database %s…", database_id)
        pages = self._notion.query_database(database_id)
        logger.info("Found %d pages in database", len(pages))

        for page in pages:
            page_id = page["id"]
            try:
                self._sync_page_recursive(page_id, parent_odoo_id=self._parent_id, stats=stats)
            except Exception as exc:
                logger.exception("Error syncing page %s", page_id)
                stats.errors += 1
                stats.error_messages.append(f"page {page_id}: {exc}")
                stats.add_item("(unknown)", page_id, "error", detail=str(exc))

        return stats

    def sync_database_as_table(self, database_id: str) -> SyncStats:
        """Sync a Notion database as a single summary article containing an HTML table.

        Instead of creating one article per row (see :meth:`sync_database`),
        this renders the whole database as a table: one column per property
        (title first) and one row per page. The ``--since`` filter does not
        apply because the table is a full snapshot.

        Args:
            database_id: Notion database UUID.

        Returns:
            :class:`SyncStats` with the result of the single upsert.
        """
        stats = SyncStats()
        logger.info("Building table view of Notion database %s…", database_id)
        database = self._notion.get_database(database_id)
        title = self._parser.extract_database_title(database)
        icon = self._parser.extract_icon(database)

        schema = database.get("properties", {})
        title_column = next(
            (name for name, prop in schema.items() if prop.get("type") == "title"),
            "Name",
        )
        columns = [name for name in schema if name != title_column]

        pages = self._notion.query_database(database_id)
        logger.info("Rendering %d pages as table rows", len(pages))
        rows = []
        for page in pages:
            properties = self._parser.extract_properties(page)
            rows.append(
                [self._parser.extract_title(page)] + [properties.get(c, "") for c in columns]
            )

        body_html = self._parser.simple_table([title_column, *columns], rows)

        if self._dry_run:
            logger.info("[DRY RUN] Would upsert table article: %r (%d rows)", title, len(rows))
            stats.created += 1
            stats.add_item(title, database_id, "created", detail="dry run")
            return stats

        try:
            article_id, created = self._upsert(
                database_id, title=title, body=body_html, parent_id=self._parent_id, icon=icon
            )
        except Exception as exc:
            logger.error("Failed to upsert table article '%s': %s", title, exc)
            stats.errors += 1
            stats.error_messages.append(f"'{title}': {exc}")
            stats.add_item(title, database_id, "error", detail=str(exc))
            return stats

        if created:
            stats.created += 1
        else:
            stats.updated += 1
        stats.add_item(title, database_id, "created" if created else "updated", odoo_article_id=article_id)
        return stats

    def sync_search(self, query: str = "") -> SyncStats:
        """Sync all pages returned by a Notion search query.

        Args:
            query: Free-text search query (empty = all accessible pages).

        Returns:
            :class:`SyncStats` with aggregated results.
        """
        stats = SyncStats()
        logger.info("Searching Notion for: %r", query or "(all)")
        pages = self._notion.search(query, object_type="page")
        logger.info("Found %d pages", len(pages))

        for page in pages:
            page_id = page["id"]
            try:
                self._sync_page_recursive(page_id, parent_odoo_id=self._parent_id, stats=stats)
            except Exception as exc:
                logger.exception("Error syncing page %s", page_id)
                stats.errors += 1
                stats.error_messages.append(f"page {page_id}: {exc}")
                stats.add_item("(unknown)", page_id, "error", detail=str(exc))

        return stats

    # --------------------------------------------------------------- internals

    def _sync_page_recursive(
        self, page_id: str, parent_odoo_id: int | None, stats: SyncStats
    ) -> int | None:
        """Sync one page and all its child pages.

        Returns:
            The Odoo article ID that was created or updated, or None on error.
        """
        logger.info("Syncing Notion page %s…", page_id)

        # Fetch metadata
        page = self._notion.get_page(page_id)
        title = self._parser.extract_title(page)
        icon = self._parser.extract_icon(page)

        # --since: skip pages not modified since the cutoff, but keep walking
        # the tree because editing a child does not bump the parent's
        # last_edited_time.
        if self._is_unmodified(page):
            logger.info("Skipping '%s' (not modified since %s)", title, self._since)
            stats.skipped += 1
            stats.add_item(title, page_id, "skipped", detail=f"not modified since {self._since}")
            blocks = self._notion.get_block_children(page_id)
            article_id = self._store.get(page_id) if self._store else None
            self._sync_children(blocks, parent_odoo_id=article_id or parent_odoo_id, stats=stats)
            return article_id

        # Fetch content blocks
        blocks = self._notion.get_block_children(page_id)
        body_html = self._parser.blocks_to_html(blocks)

        if self._include_properties:
            properties = self._parser.extract_properties(page)
            properties_html = self._parser.properties_to_html(properties)
            if properties_html:
                body_html = f"{properties_html}\n{body_html}" if body_html else properties_html

        logger.debug("Page '%s' — %d characters of HTML", title, len(body_html))

        if self._dry_run:
            logger.info("[DRY RUN] Would upsert article: %r (parent=%s)", title, parent_odoo_id)
            stats.created += 1
            stats.add_item(title, page_id, "created", detail="dry run")
            return None

        if self._rehoster is not None:
            body_html = self._rehoster.rehost(body_html, article_name=title)

        try:
            article_id, created = self._upsert(
                page_id, title=title, body=body_html, parent_id=parent_odoo_id, icon=icon
            )
        except Exception as exc:
            logger.error("Failed to upsert article '%s': %s", title, exc)
            stats.errors += 1
            stats.error_messages.append(f"'{title}': {exc}")
            stats.add_item(title, page_id, "error", detail=str(exc))
            return None

        if created:
            stats.created += 1
        else:
            stats.updated += 1
        stats.add_item(title, page_id, "created" if created else "updated", odoo_article_id=article_id)

        self._sync_children(blocks, parent_odoo_id=article_id, stats=stats)
        return article_id

    def _sync_children(
        self, blocks: list[dict], parent_odoo_id: int | None, stats: SyncStats
    ) -> None:
        """Recurse into child pages (Notion child_page blocks)."""
        for block in blocks:
            if block.get("type") == "child_page":
                self._sync_page_recursive(block["id"], parent_odoo_id=parent_odoo_id, stats=stats)

    def _is_unmodified(self, page: dict) -> bool:
        """Return True when --since is set and the page predates the cutoff."""
        if self._since is None:
            return False
        last_edited = page.get("last_edited_time")
        if not last_edited:
            return False
        edited_at = datetime.fromisoformat(last_edited.replace("Z", "+00:00"))
        return edited_at < self._since

    def _upsert(
        self, page_id: str, *, title: str, body: str, parent_id: int | None, icon: str
    ) -> tuple[int, bool]:
        """Create or update the Odoo article for a Notion page.

        With a store, the mapping ``notion_page_id → odoo_article_id`` wins
        over the article name, so renamed pages update in place. Unmapped
        pages fall back to the legacy name-based upsert and their resulting
        ID is recorded, migrating pre-store installations transparently.
        """
        mapped_id = self._store.get(page_id) if self._store else None
        if mapped_id is not None:
            if self._odoo.article_exists(mapped_id):
                self._odoo.update_article(mapped_id, name=title, body=body, icon=icon or None)
                return mapped_id, False
            logger.warning(
                "Mapped article %s for page %s no longer exists in Odoo — recreating",
                mapped_id,
                page_id,
            )
            self._store.remove(page_id)

        article_id, created = self._odoo.upsert_article(
            name=title,
            body=body,
            parent_id=parent_id,
            icon=icon,
            is_published=self._publish,
        )
        if self._store is not None:
            self._store.set(page_id, article_id)
        return article_id, created
