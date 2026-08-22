"""Unit tests for SyncEngine — Notion and Odoo clients are mocked."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from src.store import ArticleStore
from src.sync import SyncEngine, SyncStats


@pytest.fixture
def notion():
    m = MagicMock()
    m.get_page.return_value = {
        "id": "page1",
        "properties": {
            "title": {"type": "title", "title": [{"plain_text": "Test Page", "type": "text"}]}
        },
        "icon": {"type": "emoji", "emoji": "📄"},
    }
    m.get_block_children.return_value = [
        {
            "id": "b1",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {
                        "type": "text",
                        "plain_text": "Hello",
                        "text": {"content": "Hello", "link": None},
                        "annotations": {
                            "bold": False, "italic": False, "strikethrough": False,
                            "underline": False, "code": False, "color": "default"
                        },
                    }
                ]
            },
            "has_children": False,
            "children": [],
        }
    ]
    return m


@pytest.fixture
def odoo():
    m = MagicMock()
    m.upsert_article.return_value = (42, True)
    return m


@pytest.fixture
def engine(notion, odoo) -> SyncEngine:
    return SyncEngine(notion, odoo)


# ---------------------------------------------------------------- sync_page

class TestSyncPage:
    def test_calls_notion_and_odoo(self, engine, notion, odoo):
        stats = engine.sync_page("page1")
        notion.get_page.assert_called_once_with("page1")
        notion.get_block_children.assert_called_once_with("page1")
        odoo.upsert_article.assert_called_once()
        assert stats.created == 1
        assert stats.errors == 0

    def test_error_in_odoo_increments_errors(self, engine, odoo):
        odoo.upsert_article.side_effect = Exception("DB error")
        stats = engine.sync_page("page1")
        assert stats.errors == 1
        assert stats.created == 0

    def test_passes_parent_id(self, notion, odoo):
        engine = SyncEngine(notion, odoo, odoo_parent_id=10)
        engine.sync_page("page1")
        call_kwargs = odoo.upsert_article.call_args
        assert call_kwargs.kwargs.get("parent_id") == 10 or call_kwargs.args[2] == 10


class TestSyncPageChildPages:
    def test_recurses_into_child_pages(self, notion, odoo):
        """child_page blocks should trigger recursive sync."""
        child_page_block = {
            "id": "child-page-id",
            "type": "child_page",
            "child_page": {"title": "Child"},
            "has_children": False,
            "children": [],
        }
        # First call (parent page) returns a child_page block; second call (child page) returns []
        notion.get_block_children.side_effect = [[child_page_block], []]
        notion.get_page.side_effect = lambda pid: {
            "id": pid,
            "properties": {
                "title": {"type": "title", "title": [{"plain_text": pid, "type": "text"}]}
            },
            "icon": {},
        }
        odoo.upsert_article.return_value = (99, True)

        engine = SyncEngine(notion, odoo)
        engine.sync_page("page1")
        # get_page called for page1 + child-page-id
        assert notion.get_page.call_count == 2


# ---------------------------------------------------------------- sync_database

class TestSyncDatabase:
    def test_syncs_all_pages(self, notion, odoo):
        notion.query_database.return_value = [{"id": "p1"}, {"id": "p2"}]
        notion.get_page.side_effect = lambda pid: {
            "id": pid,
            "properties": {"title": {"type": "title", "title": [{"plain_text": pid, "type": "text"}]}},
            "icon": {},
        }
        engine = SyncEngine(notion, odoo)
        stats = engine.sync_database("db1")
        assert odoo.upsert_article.call_count == 2
        assert stats.created == 2

    def test_continues_on_page_error(self, notion, odoo):
        notion.query_database.return_value = [{"id": "p1"}, {"id": "p2"}]
        notion.get_page.side_effect = Exception("Notion down")
        engine = SyncEngine(notion, odoo)
        stats = engine.sync_database("db1")
        assert stats.errors == 2


# ---------------------------------------------------------------- sync_search

class TestSyncSearch:
    def test_syncs_all_results(self, notion, odoo):
        notion.search.return_value = [{"id": "p1"}, {"id": "p2"}]
        notion.get_page.side_effect = lambda pid: {
            "id": pid,
            "properties": {"title": {"type": "title", "title": [{"plain_text": pid, "type": "text"}]}},
            "icon": {},
        }
        engine = SyncEngine(notion, odoo)
        stats = engine.sync_search("docs")
        notion.search.assert_called_once_with("docs", object_type="page")
        assert stats.created == 2

    def test_continues_on_page_error(self, notion, odoo):
        notion.search.return_value = [{"id": "p1"}, {"id": "p2"}]
        notion.get_page.side_effect = Exception("Notion down")
        engine = SyncEngine(notion, odoo)
        stats = engine.sync_search()
        assert stats.errors == 2


class TestSyncPageUnexpectedError:
    def test_unexpected_error_is_recorded(self, notion, odoo):
        notion.get_page.side_effect = RuntimeError("boom")
        engine = SyncEngine(notion, odoo)
        stats = engine.sync_page("page1")
        assert stats.errors == 1
        assert "boom" in stats.error_messages[0]


# ---------------------------------------------------------------- dry_run

class TestDryRun:
    def test_dry_run_skips_odoo(self, notion, odoo):
        engine = SyncEngine(notion, odoo, dry_run=True)
        stats = engine.sync_page("page1")
        odoo.upsert_article.assert_not_called()
        # In dry run mode we count as "created" for reporting purposes
        assert stats.created == 1


# ---------------------------------------------------------------- store integration

class TestSyncWithStore:
    @pytest.fixture
    def store(self):
        with ArticleStore(":memory:") as s:
            yield s

    def test_unmapped_page_falls_back_to_name_upsert_and_records_mapping(
        self, notion, odoo, store
    ):
        """Migration path: pages unknown to the store use the legacy name-based upsert."""
        engine = SyncEngine(notion, odoo, store=store)
        engine.sync_page("page1")
        odoo.upsert_article.assert_called_once()
        assert store.get("page1") == 42

    def test_mapped_page_updates_by_id_not_name(self, notion, odoo, store):
        store.set("page1", 7)
        odoo.article_exists.return_value = True
        engine = SyncEngine(notion, odoo, store=store)
        stats = engine.sync_page("page1")
        odoo.update_article.assert_called_once()
        assert odoo.update_article.call_args.args[0] == 7
        odoo.upsert_article.assert_not_called()
        assert stats.updated == 1
        assert stats.created == 0

    def test_stale_mapping_is_recreated(self, notion, odoo, store):
        """If the mapped article was deleted in Odoo, recreate and remap."""
        store.set("page1", 7)
        odoo.article_exists.return_value = False
        engine = SyncEngine(notion, odoo, store=store)
        stats = engine.sync_page("page1")
        odoo.upsert_article.assert_called_once()
        assert store.get("page1") == 42
        assert stats.created == 1

    def test_child_pages_are_mapped_too(self, notion, odoo, store):
        child_page_block = {
            "id": "child-page-id",
            "type": "child_page",
            "child_page": {"title": "Child"},
            "has_children": False,
            "children": [],
        }
        notion.get_block_children.side_effect = [[child_page_block], []]
        notion.get_page.side_effect = lambda pid: {
            "id": pid,
            "properties": {
                "title": {"type": "title", "title": [{"plain_text": pid, "type": "text"}]}
            },
            "icon": {},
        }
        engine = SyncEngine(notion, odoo, store=store)
        engine.sync_page("page1")
        assert store.get("page1") == 42
        assert store.get("child-page-id") == 42


# ---------------------------------------------------------------- --since filter

class TestSinceFilter:
    SINCE = datetime(2024, 6, 1, tzinfo=UTC)

    def _page(self, pid, last_edited):
        return {
            "id": pid,
            "last_edited_time": last_edited,
            "properties": {
                "title": {"type": "title", "title": [{"plain_text": pid, "type": "text"}]}
            },
            "icon": {},
        }

    def test_old_page_is_skipped(self, notion, odoo):
        notion.get_page.return_value = self._page("page1", "2024-01-01T00:00:00.000Z")
        engine = SyncEngine(notion, odoo, since=self.SINCE)
        stats = engine.sync_page("page1")
        odoo.upsert_article.assert_not_called()
        assert stats.skipped == 1
        assert stats.created == 0

    def test_recent_page_is_synced(self, notion, odoo):
        notion.get_page.return_value = self._page("page1", "2024-07-01T00:00:00.000Z")
        engine = SyncEngine(notion, odoo, since=self.SINCE)
        stats = engine.sync_page("page1")
        odoo.upsert_article.assert_called_once()
        assert stats.created == 1
        assert stats.skipped == 0

    def test_page_without_last_edited_time_is_synced(self, notion, odoo):
        page = self._page("page1", "")
        del page["last_edited_time"]
        notion.get_page.return_value = page
        engine = SyncEngine(notion, odoo, since=self.SINCE)
        stats = engine.sync_page("page1")
        assert stats.created == 1

    def test_skipped_parent_still_recurses_into_children(self, notion, odoo):
        """Editing a child does not bump the parent's last_edited_time."""
        child_page_block = {
            "id": "child-page-id",
            "type": "child_page",
            "child_page": {"title": "Child"},
            "has_children": False,
            "children": [],
        }
        notion.get_block_children.side_effect = [[child_page_block], []]
        notion.get_page.side_effect = [
            self._page("page1", "2024-01-01T00:00:00.000Z"),  # parent: too old
            self._page("child-page-id", "2024-07-01T00:00:00.000Z"),  # child: fresh
        ]
        engine = SyncEngine(notion, odoo, since=self.SINCE)
        stats = engine.sync_page("page1")
        assert stats.skipped == 1
        assert stats.created == 1

    def test_skipped_parent_uses_store_mapping_for_child_parent_id(self, notion, odoo):
        """Children of a skipped page nest under its previously mapped article."""
        child_page_block = {
            "id": "child-page-id",
            "type": "child_page",
            "child_page": {"title": "Child"},
            "has_children": False,
            "children": [],
        }
        notion.get_block_children.side_effect = [[child_page_block], []]
        notion.get_page.side_effect = [
            self._page("page1", "2024-01-01T00:00:00.000Z"),
            self._page("child-page-id", "2024-07-01T00:00:00.000Z"),
        ]
        with ArticleStore(":memory:") as store:
            store.set("page1", 123)
            odoo.article_exists.return_value = False
            engine = SyncEngine(notion, odoo, since=self.SINCE, store=store)
            engine.sync_page("page1")
        assert odoo.upsert_article.call_args.kwargs["parent_id"] == 123


# ---------------------------------------------------------------- properties

class TestIncludeProperties:
    def test_properties_prepended_to_body(self, notion, odoo):
        notion.get_page.return_value = {
            "id": "page1",
            "properties": {
                "title": {"type": "title", "title": [{"plain_text": "Test", "type": "text"}]},
                "Status": {"type": "status", "status": {"name": "Done"}},
                "Tags": {"type": "multi_select", "multi_select": [{"name": "infra"}]},
            },
            "icon": {},
        }
        engine = SyncEngine(notion, odoo, include_properties=True)
        engine.sync_page("page1")
        body = odoo.upsert_article.call_args.kwargs["body"]
        assert '<table class="notion-properties">' in body
        assert "Done" in body
        assert "infra" in body
        assert body.index("notion-properties") < body.index("<p>Hello</p>")

    def test_properties_omitted_by_default(self, engine, odoo):
        engine.sync_page("page1")
        body = odoo.upsert_article.call_args.kwargs["body"]
        assert "notion-properties" not in body

    def test_no_properties_leaves_body_unchanged(self, notion, odoo):
        engine = SyncEngine(notion, odoo, include_properties=True)
        engine.sync_page("page1")
        body = odoo.upsert_article.call_args.kwargs["body"]
        assert "notion-properties" not in body


# ---------------------------------------------------------------- database as table

class TestSyncDatabaseAsTable:
    @pytest.fixture
    def db_notion(self, notion):
        notion.get_database.return_value = {
            "id": "db1",
            "title": [{"plain_text": "Tasks", "type": "text"}],
            "icon": {"type": "emoji", "emoji": "🗃"},
            "properties": {
                "Name": {"type": "title"},
                "Status": {"type": "status"},
                "Tags": {"type": "multi_select"},
            },
        }
        notion.query_database.return_value = [
            {
                "id": "p1",
                "properties": {
                    "Name": {"type": "title", "title": [{"plain_text": "Task A", "type": "text"}]},
                    "Status": {"type": "status", "status": {"name": "Done"}},
                    "Tags": {"type": "multi_select", "multi_select": [{"name": "infra"}]},
                },
            },
            {
                "id": "p2",
                "properties": {
                    "Name": {"type": "title", "title": [{"plain_text": "Task B", "type": "text"}]},
                    "Status": {"type": "status", "status": None},
                    "Tags": {"type": "multi_select", "multi_select": []},
                },
            },
        ]
        return notion

    def test_creates_single_summary_article(self, db_notion, odoo):
        engine = SyncEngine(db_notion, odoo)
        stats = engine.sync_database_as_table("db1")
        odoo.upsert_article.assert_called_once()
        kwargs = odoo.upsert_article.call_args.kwargs
        assert kwargs["name"] == "Tasks"
        assert stats.created == 1

    def test_table_contains_header_and_rows(self, db_notion, odoo):
        engine = SyncEngine(db_notion, odoo)
        engine.sync_database_as_table("db1")
        body = odoo.upsert_article.call_args.kwargs["body"]
        assert "<th>Name</th>" in body
        assert "<th>Status</th>" in body
        assert "<td>Task A</td>" in body
        assert "<td>Done</td>" in body
        assert "<td>Task B</td>" in body

    def test_empty_property_renders_empty_cell(self, db_notion, odoo):
        engine = SyncEngine(db_notion, odoo)
        engine.sync_database_as_table("db1")
        body = odoo.upsert_article.call_args.kwargs["body"]
        assert "<td></td>" in body

    def test_dry_run_skips_odoo(self, db_notion, odoo):
        engine = SyncEngine(db_notion, odoo, dry_run=True)
        stats = engine.sync_database_as_table("db1")
        odoo.upsert_article.assert_not_called()
        assert stats.created == 1
        assert stats.items[0].detail == "dry run"

    def test_upsert_error_recorded(self, db_notion, odoo):
        odoo.upsert_article.side_effect = Exception("DB error")
        engine = SyncEngine(db_notion, odoo)
        stats = engine.sync_database_as_table("db1")
        assert stats.errors == 1
        assert stats.items[0].action == "error"

    def test_database_id_mapped_in_store(self, db_notion, odoo):
        with ArticleStore(":memory:") as store:
            engine = SyncEngine(db_notion, odoo, store=store)
            engine.sync_database_as_table("db1")
            assert store.get("db1") == 42


# ---------------------------------------------------------------- report items

class TestSyncItems:
    def test_created_page_recorded(self, engine, odoo):
        stats = engine.sync_page("page1")
        assert len(stats.items) == 1
        item = stats.items[0]
        assert item.action == "created"
        assert item.title == "Test Page"
        assert item.odoo_article_id == 42

    def test_updated_page_recorded(self, notion, odoo):
        odoo.upsert_article.return_value = (7, False)
        engine = SyncEngine(notion, odoo)
        stats = engine.sync_page("page1")
        assert stats.items[0].action == "updated"
        assert stats.items[0].odoo_article_id == 7

    def test_error_recorded_with_detail(self, engine, odoo):
        odoo.upsert_article.side_effect = Exception("DB error")
        stats = engine.sync_page("page1")
        assert stats.items[0].action == "error"
        assert "DB error" in stats.items[0].detail

    def test_skipped_page_recorded(self, notion, odoo):
        notion.get_page.return_value = {
            "id": "page1",
            "last_edited_time": "2024-01-01T00:00:00.000Z",
            "properties": {
                "title": {"type": "title", "title": [{"plain_text": "Old", "type": "text"}]}
            },
            "icon": {},
        }
        engine = SyncEngine(notion, odoo, since=datetime(2024, 6, 1, tzinfo=UTC))
        stats = engine.sync_page("page1")
        assert stats.items[0].action == "skipped"

    def test_dry_run_recorded(self, notion, odoo):
        engine = SyncEngine(notion, odoo, dry_run=True)
        stats = engine.sync_page("page1")
        assert stats.items[0].action == "created"
        assert stats.items[0].detail == "dry run"

    def test_unexpected_error_recorded(self, notion, odoo):
        notion.get_page.side_effect = RuntimeError("boom")
        engine = SyncEngine(notion, odoo)
        stats = engine.sync_page("page1")
        assert stats.items[0].action == "error"
        assert stats.items[0].title == "(unknown)"


# ---------------------------------------------------------------- image rehosting

class TestRehosterIntegration:
    def test_rehoster_transforms_body_before_upsert(self, notion, odoo):
        rehoster = MagicMock()
        rehoster.rehost.return_value = "<p>rehosted</p>"
        engine = SyncEngine(notion, odoo, rehoster=rehoster)
        engine.sync_page("page1")
        rehoster.rehost.assert_called_once()
        assert odoo.upsert_article.call_args.kwargs["body"] == "<p>rehosted</p>"

    def test_rehoster_not_called_in_dry_run(self, notion, odoo):
        rehoster = MagicMock()
        engine = SyncEngine(notion, odoo, dry_run=True, rehoster=rehoster)
        engine.sync_page("page1")
        rehoster.rehost.assert_not_called()

    def test_no_rehoster_leaves_body_unchanged(self, engine, odoo):
        engine.sync_page("page1")
        assert odoo.upsert_article.call_args.kwargs["body"] == "<p>Hello</p>"


# ---------------------------------------------------------------- SyncStats

class TestSyncStats:
    def test_report_contains_counts(self):
        s = SyncStats(created=3, updated=1, skipped=0, errors=1)
        report = s.report()
        assert "3" in report
        assert "1" in report

    def test_report_lists_errors(self):
        s = SyncStats(errors=1, error_messages=["something went wrong"])
        report = s.report()
        assert "something went wrong" in report
