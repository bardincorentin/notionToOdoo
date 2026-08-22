"""Unit tests for the HTML sync report."""

from datetime import UTC, datetime

from src.report import render_report, write_report
from src.sync import SyncStats


def _stats_with_items() -> SyncStats:
    stats = SyncStats(created=1, updated=1, skipped=1, errors=1)
    stats.add_item("Page A", "id-a", "created", odoo_article_id=42)
    stats.add_item("Page B", "id-b", "updated", odoo_article_id=7)
    stats.add_item("Page C", "id-c", "skipped", detail="not modified since 2024-06-01")
    stats.add_item("Page D", "id-d", "error", detail="boom")
    return stats


class TestRenderReport:
    def test_contains_summary_counts(self):
        html_doc = render_report(_stats_with_items())
        assert "Created: 1" in html_doc
        assert "Updated: 1" in html_doc
        assert "Skipped: 1" in html_doc
        assert "Errors: 1" in html_doc

    def test_contains_one_row_per_item(self):
        html_doc = render_report(_stats_with_items())
        for title in ("Page A", "Page B", "Page C", "Page D"):
            assert title in html_doc
        assert html_doc.count("<tr>") == 5  # header + 4 items

    def test_shows_odoo_id_and_detail(self):
        html_doc = render_report(_stats_with_items())
        assert "42" in html_doc
        assert "boom" in html_doc
        assert "not modified since 2024-06-01" in html_doc

    def test_escapes_html_in_titles(self):
        stats = SyncStats()
        stats.add_item("<script>alert(1)</script>", "id-x", "created")
        html_doc = render_report(stats)
        assert "<script>alert(1)</script>" not in html_doc
        assert "&lt;script&gt;" in html_doc

    def test_empty_run_renders_placeholder(self):
        html_doc = render_report(SyncStats())
        assert "No pages were processed." in html_doc

    def test_uses_provided_timestamp(self):
        when = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        html_doc = render_report(SyncStats(), generated_at=when)
        assert "2024-06-01T12:00:00+00:00" in html_doc


class TestWriteReport:
    def test_writes_file(self, tmp_path):
        path = tmp_path / "sync-report.html"
        write_report(_stats_with_items(), str(path))
        content = path.read_text(encoding="utf-8")
        assert content.startswith("<!DOCTYPE html>")
        assert "Page A" in content
