"""Unit tests for NotionParser — no network calls required."""

import pytest

from src.notion.parser import NotionParser


@pytest.fixture
def parser() -> NotionParser:
    return NotionParser()


# ---------------------------------------------------------------- helpers

def _block(block_type: str, data: dict, children: list | None = None) -> dict:
    return {
        "id": "block-id",
        "type": block_type,
        block_type: data,
        "has_children": bool(children),
        "children": children or [],
    }


def _rich(text: str, **annotations) -> dict:
    return {
        "type": "text",
        "plain_text": text,
        "text": {"content": text, "link": None},
        "annotations": {
            "bold": False,
            "italic": False,
            "strikethrough": False,
            "underline": False,
            "code": False,
            "color": "default",
            **annotations,
        },
    }


# ---------------------------------------------------------------- paragraphs

class TestParagraph:
    def test_simple(self, parser):
        block = _block("paragraph", {"rich_text": [_rich("Hello world")]})
        html = parser.blocks_to_html([block])
        assert html == "<p>Hello world</p>"

    def test_empty(self, parser):
        block = _block("paragraph", {"rich_text": []})
        html = parser.blocks_to_html([block])
        assert "<p>" in html

    def test_escapes_html(self, parser):
        block = _block("paragraph", {"rich_text": [_rich("<script>alert(1)</script>")]})
        html = parser.blocks_to_html([block])
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


# ---------------------------------------------------------------- headings

class TestHeadings:
    @pytest.mark.parametrize("level", [1, 2, 3])
    def test_heading(self, parser, level):
        block = _block(f"heading_{level}", {"rich_text": [_rich("Title")]})
        html = parser.blocks_to_html([block])
        assert f"<h{level}>Title</h{level}>" in html


# ---------------------------------------------------------------- annotations

class TestAnnotations:
    def test_bold(self, parser):
        block = _block("paragraph", {"rich_text": [_rich("Bold", bold=True)]})
        html = parser.blocks_to_html([block])
        assert "<strong>Bold</strong>" in html

    def test_italic(self, parser):
        block = _block("paragraph", {"rich_text": [_rich("Italic", italic=True)]})
        html = parser.blocks_to_html([block])
        assert "<em>Italic</em>" in html

    def test_code_annotation(self, parser):
        block = _block("paragraph", {"rich_text": [_rich("code()", code=True)]})
        html = parser.blocks_to_html([block])
        assert "<code>code()</code>" in html

    def test_strikethrough(self, parser):
        block = _block("paragraph", {"rich_text": [_rich("del", strikethrough=True)]})
        html = parser.blocks_to_html([block])
        assert "<s>del</s>" in html

    def test_underline(self, parser):
        block = _block("paragraph", {"rich_text": [_rich("ul", underline=True)]})
        html = parser.blocks_to_html([block])
        assert "<u>ul</u>" in html

    def test_color(self, parser):
        block = _block("paragraph", {"rich_text": [_rich("colored", color="red")]})
        html = parser.blocks_to_html([block])
        assert 'color:red' in html

    def test_background_color(self, parser):
        block = _block("paragraph", {"rich_text": [_rich("bg", color="blue_background")]})
        html = parser.blocks_to_html([block])
        assert 'background-color:blue' in html


# ---------------------------------------------------------------- lists

class TestLists:
    def test_bullet_list(self, parser):
        items = [
            _block("bulleted_list_item", {"rich_text": [_rich("A")]}),
            _block("bulleted_list_item", {"rich_text": [_rich("B")]}),
        ]
        html = parser.blocks_to_html(items)
        assert "<ul>" in html
        assert "<li>A</li>" in html
        assert "<li>B</li>" in html

    def test_numbered_list(self, parser):
        items = [
            _block("numbered_list_item", {"rich_text": [_rich("One")]}),
            _block("numbered_list_item", {"rich_text": [_rich("Two")]}),
        ]
        html = parser.blocks_to_html(items)
        assert "<ol>" in html
        assert "<li>One</li>" in html

    def test_separate_lists(self, parser):
        """Bullet and numbered lists should not be merged."""
        blocks = [
            _block("bulleted_list_item", {"rich_text": [_rich("A")]}),
            _block("numbered_list_item", {"rich_text": [_rich("1")]}),
        ]
        html = parser.blocks_to_html(blocks)
        assert "<ul>" in html
        assert "<ol>" in html


# ---------------------------------------------------------------- to_do

class TestToDo:
    def test_unchecked(self, parser):
        block = _block("to_do", {"rich_text": [_rich("Task")], "checked": False})
        html = parser.blocks_to_html([block])
        assert 'type="checkbox"' in html
        assert "checked" not in html.replace('type="checkbox"', '')

    def test_checked(self, parser):
        block = _block("to_do", {"rich_text": [_rich("Done")], "checked": True})
        html = parser.blocks_to_html([block])
        assert 'checked="checked"' in html


# ---------------------------------------------------------------- code block

class TestCodeBlock:
    def test_basic(self, parser):
        block = _block("code", {"rich_text": [_rich("x = 1")], "language": "python"})
        html = parser.blocks_to_html([block])
        assert "<pre><code" in html
        assert "x = 1" in html
        assert "language-python" in html

    def test_escapes_content(self, parser):
        block = _block("code", {"rich_text": [_rich("<b>hack</b>")], "language": "html"})
        html = parser.blocks_to_html([block])
        assert "<b>" not in html
        assert "&lt;b&gt;" in html


# ---------------------------------------------------------------- quote

class TestQuote:
    def test_basic(self, parser):
        block = _block("quote", {"rich_text": [_rich("Famous quote")]})
        html = parser.blocks_to_html([block])
        assert "<blockquote>" in html
        assert "Famous quote" in html


# ---------------------------------------------------------------- divider

class TestDivider:
    def test_divider(self, parser):
        block = _block("divider", {})
        html = parser.blocks_to_html([block])
        assert "<hr/>" in html


# ---------------------------------------------------------------- image

class TestImage:
    def test_external(self, parser):
        block = _block(
            "image",
            {"type": "external", "external": {"url": "https://example.com/img.png"}, "caption": []},
        )
        html = parser.blocks_to_html([block])
        assert "<img" in html
        assert "https://example.com/img.png" in html

    def test_with_caption(self, parser):
        block = _block(
            "image",
            {
                "type": "external",
                "external": {"url": "https://example.com/img.png"},
                "caption": [_rich("My caption")],
            },
        )
        html = parser.blocks_to_html([block])
        assert "<figcaption>My caption</figcaption>" in html


# ---------------------------------------------------------------- callout

class TestCallout:
    def test_with_emoji(self, parser):
        block = _block(
            "callout",
            {
                "rich_text": [_rich("Note")],
                "icon": {"type": "emoji", "emoji": "💡"},
            },
        )
        html = parser.blocks_to_html([block])
        assert 'class="callout"' in html
        assert "💡" in html
        assert "Note" in html


# ---------------------------------------------------------------- toggle

class TestToggle:
    def test_toggle(self, parser):
        child = _block("paragraph", {"rich_text": [_rich("Inner")]})
        block = _block(
            "toggle",
            {"rich_text": [_rich("Click me")]},
            children=[child],
        )
        html = parser.blocks_to_html([block])
        assert "<details>" in html
        assert "<summary>Click me</summary>" in html
        assert "Inner" in html


# ---------------------------------------------------------------- title / icon extraction

class TestPageMetadata:
    def test_extract_title(self, parser):
        page = {
            "properties": {
                "title": {
                    "type": "title",
                    "title": [_rich("My Page")],
                }
            }
        }
        assert parser.extract_title(page) == "My Page"

    def test_extract_title_missing(self, parser):
        assert parser.extract_title({"properties": {}}) == "Untitled"

    def test_extract_icon_emoji(self, parser):
        page = {"icon": {"type": "emoji", "emoji": "🚀"}}
        assert parser.extract_icon(page) == "🚀"

    def test_extract_icon_no_icon(self, parser):
        assert parser.extract_icon({}) == ""


# ---------------------------------------------------------------- unknown blocks

class TestUnknownBlocks:
    def test_unknown_renders_comment(self, parser):
        block = _block("synced_block", {})
        html = parser.blocks_to_html([block])
        assert "unsupported block" in html
        assert "synced_block" in html

    @pytest.mark.parametrize("block_type", ["child_page", "child_database", "table_row"])
    def test_structural_blocks_skipped_silently(self, parser, block_type):
        html = parser.blocks_to_html([_block(block_type, {})])
        assert html == ""


# ---------------------------------------------------------------- file / pdf

class TestFileBlocks:
    def test_external_file_renders_link(self, parser):
        block = _block(
            "file",
            {"type": "external", "external": {"url": "https://x/doc.zip"}, "caption": []},
        )
        html = parser.blocks_to_html([block])
        assert '<a href="https://x/doc.zip">https://x/doc.zip</a>' in html

    def test_pdf_with_caption(self, parser):
        block = _block(
            "pdf",
            {"type": "file", "file": {"url": "https://x/f.pdf"}, "caption": [_rich("Spec")]},
        )
        html = parser.blocks_to_html([block])
        assert '<a href="https://x/f.pdf">Spec</a>' in html

    def test_file_without_url_renders_nothing(self, parser):
        html = parser.blocks_to_html([_block("file", {"type": "external"})])
        assert html == ""


# ---------------------------------------------------------------- page properties

class TestExtractProperties:
    def test_select_and_status(self, parser):
        page = {
            "properties": {
                "Priority": {"type": "select", "select": {"name": "High"}},
                "Status": {"type": "status", "status": {"name": "In progress"}},
            }
        }
        props = parser.extract_properties(page)
        assert props == {"Priority": "High", "Status": "In progress"}

    def test_multi_select_joined(self, parser):
        page = {
            "properties": {
                "Tags": {
                    "type": "multi_select",
                    "multi_select": [{"name": "infra"}, {"name": "docs"}],
                }
            }
        }
        assert parser.extract_properties(page) == {"Tags": "infra, docs"}

    def test_date_with_and_without_end(self, parser):
        page = {
            "properties": {
                "Due": {"type": "date", "date": {"start": "2024-06-01", "end": None}},
                "Sprint": {"type": "date", "date": {"start": "2024-06-01", "end": "2024-06-14"}},
            }
        }
        props = parser.extract_properties(page)
        assert props["Due"] == "2024-06-01"
        assert props["Sprint"] == "2024-06-01 → 2024-06-14"

    def test_checkbox_number_url(self, parser):
        page = {
            "properties": {
                "Done": {"type": "checkbox", "checkbox": True},
                "Score": {"type": "number", "number": 3.5},
                "Link": {"type": "url", "url": "https://example.com"},
            }
        }
        props = parser.extract_properties(page)
        assert props["Done"] == "✓"
        assert props["Score"] == "3.5"
        assert props["Link"] == "https://example.com"

    def test_people_and_rich_text(self, parser):
        page = {
            "properties": {
                "Owner": {"type": "people", "people": [{"name": "Ada"}, {"name": "Alan"}]},
                "Notes": {"type": "rich_text", "rich_text": [_rich("Some note")]},
            }
        }
        props = parser.extract_properties(page)
        assert props["Owner"] == "Ada, Alan"
        assert props["Notes"] == "Some note"

    def test_timestamps(self, parser):
        page = {
            "properties": {
                "Created": {"type": "created_time", "created_time": "2024-01-01T00:00:00.000Z"},
                "Edited": {
                    "type": "last_edited_time",
                    "last_edited_time": "2024-06-01T00:00:00.000Z",
                },
            }
        }
        props = parser.extract_properties(page)
        assert props["Created"] == "2024-01-01T00:00:00.000Z"
        assert props["Edited"] == "2024-06-01T00:00:00.000Z"

    def test_title_and_empty_values_skipped(self, parser):
        page = {
            "properties": {
                "title": {"type": "title", "title": [_rich("My page")]},
                "Empty select": {"type": "select", "select": None},
                "Empty tags": {"type": "multi_select", "multi_select": []},
                "Unknown": {"type": "relation", "relation": [{"id": "x"}]},
            }
        }
        assert parser.extract_properties(page) == {}


class TestPropertiesToHtml:
    def test_renders_table(self, parser):
        html = parser.properties_to_html({"Status": "Done", "Tags": "infra"})
        assert html.startswith('<table class="notion-properties">')
        assert "<th>Status</th><td>Done</td>" in html
        assert "<th>Tags</th><td>infra</td>" in html

    def test_escapes_html(self, parser):
        html = parser.properties_to_html({"<b>": "a & b"})
        assert "&lt;b&gt;" in html
        assert "a &amp; b" in html

    def test_empty_returns_empty_string(self, parser):
        assert parser.properties_to_html({}) == ""


# ---------------------------------------------------------------- tables

class TestTable:
    def _table(self, has_header: bool) -> dict:
        rows = [
            _block("table_row", {"cells": [[_rich("A")], [_rich("B")]]}),
            _block("table_row", {"cells": [[_rich("1")], [_rich("2")]]}),
        ]
        return _block("table", {"has_column_header": has_header}, children=rows)

    def test_with_header_row(self, parser):
        html = parser.blocks_to_html([self._table(has_header=True)])
        assert "<th>A</th><th>B</th>" in html
        assert "<td>1</td><td>2</td>" in html

    def test_without_header_row(self, parser):
        html = parser.blocks_to_html([self._table(has_header=False)])
        assert "<th>" not in html
        assert "<td>A</td><td>B</td>" in html

    def test_empty_table_renders_nothing(self, parser):
        html = parser.blocks_to_html([_block("table", {"has_column_header": True})])
        assert html == ""


# ---------------------------------------------------------------- links & embeds

class TestLinkBlocks:
    def test_bookmark(self, parser):
        block = _block("bookmark", {"url": "https://example.com", "caption": [_rich("Docs")]})
        assert '<a href="https://example.com">Docs</a>' in parser.blocks_to_html([block])

    def test_equation_block(self, parser):
        block = _block("equation", {"expression": "E = mc^2"})
        assert "<code>E = mc^2</code>" in parser.blocks_to_html([block])

    def test_video_external(self, parser):
        block = _block("video", {"type": "external", "external": {"url": "https://x/v.mp4"}})
        assert '<a href="https://x/v.mp4">' in parser.blocks_to_html([block])

    def test_embed(self, parser):
        block = _block("embed", {"url": "https://x/embed"})
        assert '<a href="https://x/embed">' in parser.blocks_to_html([block])

    def test_image_without_url_renders_comment(self, parser):
        block = _block("image", {"type": "external", "external": {}})
        assert "no URL" in parser.blocks_to_html([block])


# ---------------------------------------------------------------- rich-text edge cases

class TestRichTextEdgeCases:
    def test_inline_equation_span(self, parser):
        span = {"type": "equation", "equation": {"expression": "x^2"}, "plain_text": "x^2"}
        block = _block("paragraph", {"rich_text": [span]})
        assert "<code>x^2</code>" in parser.blocks_to_html([block])

    def test_mention_rendered_as_plain_text(self, parser):
        span = {"type": "mention", "mention": {"type": "user"}, "plain_text": "@Ada"}
        block = _block("paragraph", {"rich_text": [span]})
        assert "@Ada" in parser.blocks_to_html([block])

    def test_link_span(self, parser):
        span = _rich("click")
        span["text"]["link"] = {"url": "https://example.com"}
        block = _block("paragraph", {"rich_text": [span]})
        assert '<a href="https://example.com">click</a>' in parser.blocks_to_html([block])

    def test_renderer_exception_falls_back_to_comment(self, parser):
        # rich_text must be a list; a malformed payload triggers the fallback path
        block = _block("paragraph", {"rich_text": 42})
        assert "<!-- unsupported block: paragraph -->" in parser.blocks_to_html([block])
