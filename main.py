#!/usr/bin/env python3
"""CLI entry-point for notionToOdoo.

Usage examples:

    # Sync a single Notion page
    python main.py page <NOTION_PAGE_ID>

    # Sync an entire Notion database
    python main.py database <NOTION_DATABASE_ID>

    # Sync all pages accessible to the integration (optional search query)
    python main.py search
    python main.py search "my keyword"

All connection parameters are read from environment variables (see .env.example).
"""

import argparse
import json
import logging
import os
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime

from dotenv import load_dotenv

from src.i18n import _
from src.notion.client import NotionAPIError, NotionClient
from src.odoo.client import OdooAPIError, OdooAuthError, OdooClient, OdooDocumentPageClient
from src.rehost import ImageRehoster
from src.report import write_report
from src.store import DEFAULT_STORE_PATH, ArticleStore
from src.sync import SyncEngine, SyncStats

load_dotenv()


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects (for Datadog, CloudWatch…)."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def _setup_logging(verbose: bool, log_format: str = "text") -> None:
    level = logging.DEBUG if verbose else logging.INFO
    if log_format == "json":
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logging.basicConfig(level=level, handlers=[handler], force=True)
        return
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )


def _parse_since(value: str) -> datetime:
    """Parse an ISO date/datetime string into an aware UTC datetime."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid date {value!r} — use ISO 8601, e.g. 2024-01-31 or 2024-01-31T12:00:00Z"
        ) from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        print(_("ERROR: environment variable '{name}' is not set.", name=name), file=sys.stderr)
        sys.exit(1)
    return value


def _watch_loop(
    run_pass: Callable[[datetime | None], object],
    interval: int,
    initial_since: "datetime | None" = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Poll forever: run a sync pass, then only re-sync pages edited since it.

    Each pass records its own start time and hands it to the next one as the
    ``--since`` cutoff, so a watch acts like a webhook substitute: the first
    pass does a full (or ``--since``-bounded) sync, later passes only touch
    pages modified in the meantime. Stops when interrupted (Ctrl+C).
    """
    since = initial_since
    while True:
        pass_started = datetime.now(UTC)
        run_pass(since)
        since = pass_started
        sleep(interval)


def _build_clients(
    dry_run: bool, odoo_version: str = "17"
) -> tuple["NotionClient", "OdooClient | None"]:
    notion_timeout = int(os.getenv("NOTION_TIMEOUT", "30"))
    notion = NotionClient(token=_require_env("NOTION_TOKEN"), timeout=notion_timeout)

    if dry_run:
        return notion, None

    client_cls = OdooDocumentPageClient if odoo_version == "15" else OdooClient
    odoo_timeout = int(os.getenv("ODOO_TIMEOUT", "30"))
    odoo = client_cls(
        url=_require_env("ODOO_URL"),
        database=_require_env("ODOO_DB"),
        username=_require_env("ODOO_USER"),
        password=_require_env("ODOO_PASSWORD"),
        timeout=odoo_timeout,
    )

    if not odoo.check_knowledge_module():
        print(
            _(
                "ERROR: The article model ({model}) is not available on your Odoo instance. "
                "Please install the corresponding module first "
                "(Knowledge for Odoo 16/17, document_page for Odoo 15).",
                model=client_cls.MODEL,
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    return notion, odoo


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export Notion pages to Odoo Knowledge articles."
    )
    parser.add_argument(
        "mode",
        choices=["page", "database", "search"],
        help="Sync mode",
    )
    parser.add_argument(
        "target",
        nargs="?",
        default="",
        help=(
            "Notion page/database ID (required for 'page' and 'database' modes), "
            "or search query (optional for 'search' mode)."
        ),
    )
    parser.add_argument(
        "--parent-id",
        type=int,
        default=None,
        help="Odoo article ID to use as parent for imported articles.",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Mark imported articles as published.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse Notion content without writing to Odoo.",
    )
    parser.add_argument(
        "--since",
        type=_parse_since,
        default=None,
        metavar="DATE",
        help=(
            "Only sync pages modified on or after this ISO 8601 date/datetime "
            "(e.g. 2024-01-31 or 2024-01-31T12:00:00Z)."
        ),
    )
    parser.add_argument(
        "--include-properties",
        action="store_true",
        help="Prepend Notion page properties (tags, dates, status…) to the article body.",
    )
    parser.add_argument(
        "--store-path",
        default=os.getenv("SYNC_STORE_PATH", DEFAULT_STORE_PATH),
        help=(
            "Path of the SQLite file mapping Notion page IDs to Odoo article IDs "
            f"(default: {DEFAULT_STORE_PATH}, env: SYNC_STORE_PATH)."
        ),
    )
    parser.add_argument(
        "--odoo-version",
        choices=["15", "16", "17"],
        default=os.getenv("ODOO_VERSION", "17"),
        help=(
            "Target Odoo version. 16/17 use knowledge.article; "
            "15 uses the legacy document.page model (default: 17, env: ODOO_VERSION)."
        ),
    )
    parser.add_argument(
        "--report",
        default=None,
        metavar="FILE",
        help="Write an HTML report of the sync run to this file (e.g. sync-report.html).",
    )
    parser.add_argument(
        "--as-table",
        action="store_true",
        help=(
            "For 'database' mode: sync the database as a single summary article "
            "containing an HTML table (one row per page) instead of one article per page."
        ),
    )
    parser.add_argument(
        "--watch",
        type=int,
        default=None,
        metavar="SECONDS",
        help=(
            "Keep running and re-sync every SECONDS, only touching pages modified "
            "since the previous pass (polling alternative to Notion webhooks)."
        ),
    )
    parser.add_argument(
        "--rehost-images",
        action="store_true",
        help=(
            "Download Notion-hosted images (whose URLs expire after ~1 hour) and "
            "re-upload them as Odoo attachments."
        ),
    )
    parser.add_argument(
        "--log-format",
        choices=["text", "json"],
        default="text",
        help="Log output format (default: text).",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )

    args = parser.parse_args()
    _setup_logging(args.verbose, args.log_format)

    if args.mode in ("page", "database") and not args.target:
        parser.error(_("mode '{mode}' requires a target ID", mode=args.mode))

    if args.as_table and args.mode != "database":
        parser.error("--as-table is only valid in 'database' mode")

    if args.watch is not None and args.watch <= 0:
        parser.error("--watch requires a positive number of seconds")

    # Override parent_id from env if not provided on CLI
    parent_id = args.parent_id or (
        int(os.getenv("ODOO_PARENT_ARTICLE_ID", "0")) or None
    )

    try:
        notion, odoo = _build_clients(args.dry_run, args.odoo_version)
    except (NotionAPIError, OdooAuthError) as exc:
        print(_("ERROR: {error}", error=exc), file=sys.stderr)
        sys.exit(1)

    store = None if args.dry_run else ArticleStore(args.store_path)
    rehoster = ImageRehoster(odoo) if (args.rehost_images and odoo is not None) else None

    def _run_pass(since: "datetime | None") -> "SyncStats":
        engine = SyncEngine(
            notion,
            odoo,  # type: ignore[arg-type]
            odoo_parent_id=parent_id,
            publish=args.publish,
            dry_run=args.dry_run,
            store=store,
            since=since,
            include_properties=args.include_properties,
            rehoster=rehoster,
        )
        if args.mode == "page":
            stats = engine.sync_page(args.target)
        elif args.mode == "database":
            stats = (
                engine.sync_database_as_table(args.target)
                if args.as_table
                else engine.sync_database(args.target)
            )
        else:
            stats = engine.sync_search(args.target)

        if args.report:
            write_report(stats, args.report)
        print(stats.report())
        return stats

    try:
        if args.watch is not None:
            print(
                _("Watching for changes every {interval}s (press Ctrl+C to stop).",
                  interval=args.watch)
            )
            _watch_loop(_run_pass, args.watch, args.since)
            return  # pragma: no cover (the watch loop only exits via signals)
        stats = _run_pass(args.since)
    except KeyboardInterrupt:
        print(_("Stopped watching."))
        sys.exit(0)
    except (NotionAPIError, OdooAPIError) as exc:
        print(_("ERROR: {error}", error=exc), file=sys.stderr)
        sys.exit(1)
    finally:
        if store is not None:
            store.close()

    sys.exit(1 if stats.errors else 0)


if __name__ == "__main__":
    main()
