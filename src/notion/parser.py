"""Convert Notion block trees into Odoo-compatible HTML."""

import html
import logging

logger = logging.getLogger(__name__)


class NotionParser:
    """Transforms a list of Notion blocks (with nested children) into an HTML string
    suitable for the Odoo Knowledge rich-text editor (``knowledge.article.body``).

    Supported block types:
        paragraph, heading_1/2/3, bulleted_list_item, numbered_list_item,
        to_do, toggle, code, quote, divider, image, table, table_row,
        callout, bookmark, equation, file, pdf, video, embed
    """

    # Blocks that carry no inline content of their own here: child_page /
    # child_database become separate Odoo articles via the sync engine, and
    # table_row is consumed by the parent ``table`` renderer.
    _SKIP_BLOCK_TYPES = frozenset({"child_page", "child_database", "table_row"})
    _LIST_TAGS = {"bulleted_list_item": "ul", "numbered_list_item": "ol"}

    def __init__(self) -> None:
        # Built once so ``_render_block`` is a plain dict lookup per block.
        self._renderers = {
            "paragraph": self._render_paragraph,
            "heading_1": lambda d, b: self._heading(1, d),
            "heading_2": lambda d, b: self._heading(2, d),
            "heading_3": lambda d, b: self._heading(3, d),
            "to_do": self._render_todo,
            "toggle": self._render_toggle,
            "code": self._render_code,
            "quote": self._render_quote,
            "divider": lambda d, b: "<hr/>",
            "image": self._render_image,
            "table": self._render_table,
            "callout": self._render_callout,
            "bookmark": self._render_bookmark,
            "equation": self._render_equation,
            "video": self._render_video,
            "embed": self._render_embed,
            "file": self._render_file,
            "pdf": self._render_file,
        }

    def blocks_to_html(self, blocks: list[dict]) -> str:
        """Convert a flat-or-nested list of Notion blocks to an HTML string."""
        parts: list[str] = []
        i = 0
        while i < len(blocks):
            block_type = blocks[i].get("type", "")

            # Group consecutive list items so they share a single <ul>/<ol>
            list_tag = self._LIST_TAGS.get(block_type)
            if list_tag:
                items, i = self._collect_list_items(blocks, i, block_type)
                parts.append(self._render_list(items, block_type, list_tag))
                continue

            parts.append(self._render_block(blocks[i]))
            i += 1

        return "\n".join(p for p in parts if p)

    # ---------------------------------------------------------------- grouping

    def _collect_list_items(
        self, blocks: list[dict], start: int, item_type: str
    ) -> tuple[list[dict], int]:
        items = []
        i = start
        while i < len(blocks) and blocks[i].get("type") == item_type:
            items.append(blocks[i])
            i += 1
        return items, i

    # --------------------------------------------------------- block renderers

    def _heading(self, level: int, data: dict) -> str:
        return f"<h{level}>{self._rich_text(data.get('rich_text', []))}</h{level}>"

    def _render_block(self, block: dict) -> str:
        block_type = block.get("type", "")

        # Structural blocks handled elsewhere (sync recursion / parent renderers);
        # emit nothing rather than a noisy "unsupported" comment.
        if block_type in self._SKIP_BLOCK_TYPES:
            return ""

        renderer = self._renderers.get(block_type)
        if not renderer:
            logger.debug("Unhandled block type: %s", block_type)
            return f"<!-- unsupported block: {html.escape(block_type)} -->"

        try:
            return renderer(block.get(block_type, {}), block)
        except Exception as exc:
            logger.warning("Failed to render block type '%s': %s", block_type, exc)
            return f"<!-- unsupported block: {html.escape(block_type)} -->"

    def _render_file(self, data: dict, block: dict) -> str:
        caption = self._plain_text(data.get("caption", []))
        return self._link_paragraph(self._extract_file_url(data), caption)

    def _render_paragraph(self, data: dict, block: dict) -> str:
        text = self._rich_text(data.get("rich_text", []))
        if not text:
            return "<p><br/></p>"
        return f"<p>{text}</p>"

    def _render_todo(self, data: dict, block: dict) -> str:
        checked = data.get("checked", False)
        text = self._rich_text(data.get("rich_text", []))
        check_attr = ' checked="checked"' if checked else ""
        return (
            f'<p><input type="checkbox"{check_attr} disabled/> {text}</p>'
        )

    def _render_toggle(self, data: dict, block: dict) -> str:
        summary = self._rich_text(data.get("rich_text", []))
        children_html = self.blocks_to_html(block.get("children", []))
        return (
            f"<details><summary>{summary}</summary>"
            f"<div>{children_html}</div></details>"
        )

    def _render_code(self, data: dict, block: dict) -> str:
        language = data.get("language", "")
        text = self._plain_text(data.get("rich_text", []))
        escaped = html.escape(text)
        lang_attr = f' class="language-{html.escape(language)}"' if language else ""
        return f"<pre><code{lang_attr}>{escaped}</code></pre>"

    def _render_quote(self, data: dict, block: dict) -> str:
        text = self._rich_text(data.get("rich_text", []))
        children_html = self.blocks_to_html(block.get("children", []))
        inner = f"{text}{children_html}"
        return f"<blockquote>{inner}</blockquote>"

    def _render_image(self, data: dict, block: dict) -> str:
        url = self._extract_file_url(data)
        if not url:
            return "<!-- image block: no URL -->"
        caption = self._plain_text(data.get("caption", []))
        alt = html.escape(caption or "image")
        caption_html = f"<figcaption>{html.escape(caption)}</figcaption>" if caption else ""
        return (
            f'<figure><img src="{html.escape(url)}" alt="{alt}"/>{caption_html}</figure>'
        )

    def _render_table(self, data: dict, block: dict) -> str:
        has_header = data.get("has_column_header", False)
        rows = block.get("children", [])
        if not rows:
            return ""
        html_rows = []
        for idx, row_block in enumerate(rows):
            row_data = row_block.get("table_row", {})
            cells = row_data.get("cells", [])
            tag = "th" if (has_header and idx == 0) else "td"
            cell_html = "".join(
                f"<{tag}>{self._rich_text(cell)}</{tag}>" for cell in cells
            )
            html_rows.append(f"<tr>{cell_html}</tr>")
        return f"<table><tbody>{''.join(html_rows)}</tbody></table>"

    def _render_callout(self, data: dict, block: dict) -> str:
        icon_obj = data.get("icon", {})
        icon = ""
        if icon_obj.get("type") == "emoji":
            icon = html.escape(icon_obj.get("emoji", ""))
        text = self._rich_text(data.get("rich_text", []))
        children_html = self.blocks_to_html(block.get("children", []))
        return (
            f'<div class="callout">'
            f'<span class="callout-icon">{icon}</span>'
            f"<div>{text}{children_html}</div>"
            f"</div>"
        )

    def _render_bookmark(self, data: dict, block: dict) -> str:
        caption = self._plain_text(data.get("caption", []))
        return self._link_paragraph(data.get("url", ""), caption)

    def _render_equation(self, data: dict, block: dict) -> str:
        expression = html.escape(data.get("expression", ""))
        return f"<p><code>{expression}</code></p>"

    def _render_video(self, data: dict, block: dict) -> str:
        return self._link_paragraph(self._extract_file_url(data))

    def _render_embed(self, data: dict, block: dict) -> str:
        return self._link_paragraph(data.get("url", ""))

    @staticmethod
    def _link_paragraph(url: str, label: str = "") -> str:
        """Render ``url`` as a paragraph-wrapped link, or nothing if empty."""
        if not url:
            return ""
        safe_url = html.escape(url)
        return f'<p><a href="{safe_url}">{html.escape(label) if label else safe_url}</a></p>'

    # ------------------------------------------------------------- list items

    def _render_list(self, items: list[dict], item_type: str, tag: str) -> str:
        lis = []
        for item in items:
            data = item.get(item_type, {})
            text = self._rich_text(data.get("rich_text", []))
            children_html = self.blocks_to_html(item.get("children", []))
            lis.append(f"<li>{text}{children_html}</li>")
        return f"<{tag}>{''.join(lis)}</{tag}>"

    # ----------------------------------------------------------- rich-text helpers

    def _rich_text(self, rich_text_list: list[dict]) -> str:
        """Convert a Notion rich_text array to an HTML string with inline formatting."""
        parts = []
        for span in rich_text_list:
            span_type = span.get("type", "text")
            if span_type == "text":
                content = span.get("text", {})
                raw = content.get("content", "")
                link = content.get("link")
                text = html.escape(raw)
                text = self._apply_annotations(text, span.get("annotations", {}))
                if link:
                    href = html.escape(link.get("url", ""))
                    text = f'<a href="{href}">{text}</a>'
                parts.append(text)
            elif span_type == "equation":
                expr = html.escape(span.get("equation", {}).get("expression", ""))
                parts.append(f"<code>{expr}</code>")
            elif span_type == "mention":
                # Render mentions as plain text
                plain = span.get("plain_text", "")
                parts.append(html.escape(plain))
        return "".join(parts)

    def _plain_text(self, rich_text_list: list[dict]) -> str:
        """Extract plain text without any HTML formatting."""
        return "".join(span.get("plain_text", "") for span in rich_text_list)

    def _apply_annotations(self, text: str, annotations: dict) -> str:
        if annotations.get("code"):
            text = f"<code>{text}</code>"
        if annotations.get("bold"):
            text = f"<strong>{text}</strong>"
        if annotations.get("italic"):
            text = f"<em>{text}</em>"
        if annotations.get("strikethrough"):
            text = f"<s>{text}</s>"
        if annotations.get("underline"):
            text = f"<u>{text}</u>"
        color = annotations.get("color", "default")
        if color and color != "default":
            bg = color.endswith("_background")
            style_color = color.replace("_background", "")
            if bg:
                text = f'<span style="background-color:{html.escape(style_color)}">{text}</span>'
            else:
                text = f'<span style="color:{html.escape(style_color)}">{text}</span>'
        return text

    def _extract_file_url(self, data: dict) -> str:
        """Extract URL from an external or Notion-hosted file object."""
        file_type = data.get("type", "")
        if file_type == "external":
            return data.get("external", {}).get("url", "")
        if file_type == "file":
            return data.get("file", {}).get("url", "")
        return ""

    # ----------------------------------------------------------------- page title

    def extract_title(self, page: dict) -> str:
        """Extract the title from a Notion page object."""
        props = page.get("properties", {})
        for prop in props.values():
            if prop.get("type") == "title":
                return self._plain_text(prop.get("title", []))
        return "Untitled"

    def extract_icon(self, page: dict) -> str:
        """Extract the page icon (emoji only) for Odoo article icon field."""
        icon = page.get("icon", {})
        if icon and icon.get("type") == "emoji":
            return icon.get("emoji", "")
        return ""

    # ------------------------------------------------------------- properties

    def extract_properties(self, page: dict) -> dict[str, str]:
        """Extract non-title page properties as ``{name: display value}``.

        Supported property types: select, multi_select, status, date,
        checkbox, number, url, email, phone_number, rich_text, people,
        created_time, last_edited_time. Empty values are omitted.
        """
        result: dict[str, str] = {}
        for name, prop in page.get("properties", {}).items():
            value = self._property_value(prop)
            if value:
                result[name] = value
        return result

    def _property_value(self, prop: dict) -> str:
        """Render a single Notion property object as a plain string ('' = skip)."""
        prop_type = prop.get("type", "")
        data = prop.get(prop_type)
        if prop_type == "title" or data in (None, "", []):
            return ""
        if prop_type in ("select", "status"):
            return data.get("name", "")
        if prop_type == "multi_select":
            return ", ".join(opt.get("name", "") for opt in data)
        if prop_type == "date":
            start = data.get("start", "")
            end = data.get("end")
            return f"{start} → {end}" if end else start
        if prop_type == "checkbox":
            return "✓" if data else "✗"
        if prop_type == "number":
            return str(data)
        if prop_type in ("url", "email", "phone_number", "created_time", "last_edited_time"):
            return str(data)
        if prop_type == "rich_text":
            return self._plain_text(data)
        if prop_type == "people":
            return ", ".join(p.get("name", "") for p in data if p.get("name"))
        logger.debug("Unhandled property type: %s", prop_type)
        return ""

    def extract_database_title(self, database: dict) -> str:
        """Extract the title from a Notion database object."""
        return self._plain_text(database.get("title", [])) or "Untitled"

    def simple_table(self, header: list[str], rows: list[list[str]]) -> str:
        """Render a generic HTML table with a header row (all cells escaped)."""
        head = "".join(f"<th>{html.escape(cell)}</th>" for cell in header)
        body_rows = "".join(
            "<tr>" + "".join(f"<td>{html.escape(cell)}</td>" for cell in row) + "</tr>"
            for row in rows
        )
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body_rows}</tbody></table>"

    def properties_to_html(self, properties: dict[str, str]) -> str:
        """Render extracted page properties as an HTML metadata table."""
        if not properties:
            return ""
        rows = "".join(
            f"<tr><th>{html.escape(name)}</th><td>{html.escape(value)}</td></tr>"
            for name, value in properties.items()
        )
        return f'<table class="notion-properties"><tbody>{rows}</tbody></table>'
