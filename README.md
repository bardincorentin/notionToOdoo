# notionToOdoo

Python CLI tool that exports **Notion pages and databases** to **Odoo Knowledge** articles (`knowledge.article`) via REST/JSON-RPC APIs.

```
Notion Space  ──(API REST)──▶  notionToOdoo  ──(JSON-RPC)──▶  Odoo Knowledge
```

## Features

- Sync a single Notion page (and all its child pages recursively)
- Sync an entire Notion database (one article per row)
- Sync a database as a single summary table (`--as-table`)
- Search-based sync across all accessible pages
- **Idempotent**: persistent SQLite mapping of `notion_page_id → odoo_article_id`
- Re-host Notion-hosted images (URLs expire after ~1 hour) as permanent Odoo attachments
- Incremental sync via `--since DATE` or polling via `--watch SECONDS`
- HTML report generation (`--report FILE`)
- Structured JSON logging (`--log-format json`)
- French/English CLI i18n based on `LANG`

## Installation

```bash
git clone https://github.com/bardincorentin/notionToOdoo.git
cd notionToOdoo
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

```bash
cp .env.example .env
```

| Variable | Required | Description |
|---|---|---|
| `NOTION_TOKEN` | Yes | Notion integration secret (`secret_...`) |
| `ODOO_URL` | Yes | Base URL of the Odoo instance |
| `ODOO_DB` | Yes | Odoo database name |
| `ODOO_USER` | Yes | Odoo login e-mail |
| `ODOO_PASSWORD` | Yes | Odoo account password |
| `ODOO_PARENT_ARTICLE_ID` | No | Parent article ID for imported articles |
| `ODOO_VERSION` | No | `15`, `16`, or `17` (default: `17`) |
| `NOTION_TIMEOUT` | No | Notion API timeout in seconds (default: `30`) |
| `ODOO_TIMEOUT` | No | Odoo API timeout in seconds (default: `30`) |

> `.env` is in `.gitignore` and must never be committed.

## Usage

```bash
# Sync a single Notion page (and its children)
python main.py page <PAGE_ID>

# Sync an entire Notion database
python main.py database <DATABASE_ID>

# Search and sync all matching pages
python main.py search "my keyword"

# Options
python main.py page <ID> --publish          # mark articles as published
python main.py page <ID> --dry-run          # parse without writing to Odoo
python main.py page <ID> --rehost-images    # re-upload Notion images to Odoo
python main.py page <ID> --report report.html  # generate HTML report
python main.py page <ID> --since 2024-01-31  # only sync modified pages
python main.py page <ID> --watch 300        # poll every 5 minutes for changes
python main.py database <ID> --as-table     # single summary table article
```

## Docker

```bash
cp .env.example .env
docker build -t notion-to-odoo .
docker run --rm --env-file .env notion-to-odoo page <PAGE_ID>
```

## Supported Notion blocks

Paragraph, headings (1–3), bullet lists, numbered lists, to-dos, toggles, code blocks, quotes, dividers, images, tables, callouts, bookmarks, equations, videos, embeds, files, PDFs.

## Supported Odoo versions

| Version | Model | Notes |
|---|---|---|
| 16 / 17 (default) | `knowledge.article` | Full support: body, icon, publication |
| 15 (`--odoo-version 15`) | `document.page` | HTML body in `content` field; no icon or publication support |

## Testing

```bash
pip install -r requirements-dev.txt
pytest
pytest --cov=src --cov-report=term-missing
```

## Security

See [`SECURITY.md`](SECURITY.md) for vulnerability reporting and secrets handling.

## License

MIT