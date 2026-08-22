"""Unit tests for the SQLite ArticleStore."""

from src.store import ArticleStore, normalize_page_id


class TestNormalizePageId:
    def test_strips_dashes_and_lowercases(self):
        assert (
            normalize_page_id("59833787-2CF9-4FDF-8782-E53DB20768A5")
            == "598337872cf94fdf8782e53db20768a5"
        )

    def test_strips_whitespace(self):
        assert normalize_page_id("  abc123  ") == "abc123"


class TestArticleStore:
    def test_get_unknown_returns_none(self):
        with ArticleStore(":memory:") as store:
            assert store.get("unknown-page") is None

    def test_set_then_get(self):
        with ArticleStore(":memory:") as store:
            store.set("page-1", 42)
            assert store.get("page-1") == 42

    def test_set_overwrites_existing_mapping(self):
        with ArticleStore(":memory:") as store:
            store.set("page-1", 42)
            store.set("page-1", 99)
            assert store.get("page-1") == 99
            assert len(store) == 1

    def test_lookup_is_format_insensitive(self):
        """Dashed and undashed forms of the same UUID must resolve identically."""
        with ArticleStore(":memory:") as store:
            store.set("59833787-2cf9-4fdf-8782-e53db20768a5", 7)
            assert store.get("598337872cf94fdf8782e53db20768a5") == 7

    def test_remove_deletes_mapping(self):
        with ArticleStore(":memory:") as store:
            store.set("page-1", 42)
            store.remove("page-1")
            assert store.get("page-1") is None

    def test_remove_missing_is_noop(self):
        with ArticleStore(":memory:") as store:
            store.remove("never-existed")  # must not raise
            assert len(store) == 0

    def test_persists_across_connections(self, tmp_path):
        db_path = str(tmp_path / "map.db")
        with ArticleStore(db_path) as store:
            store.set("page-1", 42)
        with ArticleStore(db_path) as store:
            assert store.get("page-1") == 42

    def test_len_counts_mappings(self):
        with ArticleStore(":memory:") as store:
            store.set("page-1", 1)
            store.set("page-2", 2)
            assert len(store) == 2
