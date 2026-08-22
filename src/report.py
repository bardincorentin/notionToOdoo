"""Generate a standalone HTML report of a sync run (``--report FILE``)."""

import html
import logging
from datetime import UTC, datetime

from .sync import SyncStats

logger = logging.getLogger(__name__)

_ACTION_LABELS = {
    "created": "Created",
    "updated": "Updated",
    "skipped": "Skipped",
    "error": "Error",
}

_STYLE = """
body { font-family: sans-serif; margin: 2rem auto; max-width: 60rem; color: #222; }
h1 { font-size: 1.4rem; }
table { border-collapse: collapse; width: 100%; margin-top: 1rem; }
th, td { border: 1px solid #ddd; padding: 0.4rem 0.6rem; text-align: left; }
th { background: #f5f5f5; }
.summary span { display: inline-block; margin-right: 1.5rem; }
.action-created { color: #1a7f37; }
.action-updated { color: #0969da; }
.action-skipped { color: #6e7781; }
.action-error { color: #cf222e; font-weight: bold; }
"""


def render_report(stats: SyncStats, generated_at: datetime | None = None) -> str:
    """Render a :class:`SyncStats` as a self-contained HTML document."""
    generated_at = generated_at or datetime.now(UTC)

    rows = []
    for item in stats.items:
        action = html.escape(_ACTION_LABELS.get(item.action, item.action))
        odoo_id = str(item.odoo_article_id) if item.odoo_article_id is not None else ""
        rows.append(
            "<tr>"
            f'<td class="action-{html.escape(item.action)}">{action}</td>'
            f"<td>{html.escape(item.title)}</td>"
            f"<td><code>{html.escape(item.notion_page_id)}</code></td>"
            f"<td>{html.escape(odoo_id)}</td>"
            f"<td>{html.escape(item.detail)}</td>"
            "</tr>"
        )
    table = (
        "<table><thead><tr>"
        "<th>Action</th><th>Title</th><th>Notion page</th><th>Odoo article</th><th>Detail</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        if rows
        else "<p>No pages were processed.</p>"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>notionToOdoo sync report</title>
<style>{_STYLE}</style>
</head>
<body>
<h1>notionToOdoo sync report</h1>
<p>Generated {html.escape(generated_at.isoformat(timespec="seconds"))}</p>
<div class="summary">
<span class="action-created">Created: {stats.created}</span>
<span class="action-updated">Updated: {stats.updated}</span>
<span class="action-skipped">Skipped: {stats.skipped}</span>
<span class="action-error">Errors: {stats.errors}</span>
</div>
{table}
</body>
</html>
"""


def write_report(stats: SyncStats, path: str) -> None:
    """Write the HTML report for ``stats`` to ``path``."""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render_report(stats))
    logger.info("Sync report written to %s", path)
