# Technical Decisions

## D-001 — Python + requests (not the official Notion SDK)

**Decision:** Use `requests` directly rather than the community Notion SDK (`notion-client`).

**Rationale:**
- The official Notion SDK adds an abstraction layer that makes testing harder.
- The Notion REST API is stable and well-documented — a thin wrapper is easier to maintain.
- Fewer transitive dependencies reduces the attack surface.

---

## D-002 — JSON-RPC for Odoo (not XML-RPC)

**Decision:** Use Odoo's JSON-RPC endpoint (`/web/dataset/call_kw`) with session-cookie auth.

**Rationale:**
- JSON-RPC is the same protocol used by the Odoo web UI — more stable than XML-RPC.
- Session-cookie auth avoids sending credentials on every request.
- Works with Odoo 16 and 17 (the versions that include the Knowledge module).

---

## D-003 — HTML as the target format for Odoo Knowledge body

**Decision:** Convert Notion blocks to HTML, not Markdown.

**Rationale:**
- Odoo's Knowledge editor (`knowledge.article.body`) is an OWL / Odoo Editor field that stores HTML.
- Markdown would require a second conversion step and could lose formatting.

---

## D-004 — Upsert strategy based on article name + parent

**Decision:** Use `(name, parent_id)` as the natural key when deciding to create vs. update.

**Rationale:**
- Notion pages do not have a stable identifier on the Odoo side.
- Storing the Notion page ID as a custom Odoo field would require a custom module — out of scope.
- Name + parent is a reasonable heuristic for idempotent syncs.

**Trade-off:** If two Notion pages share the same title under the same parent, only one Odoo article is kept (the existing one is updated). This is documented in the README.

**Superseded by D-006:** the SQLite mapping store is now the default; pages absent from the store fall back to the name-based upsert (transparent migration) and their resulting ID is recorded.

---

## D-006 — SQLite sidecar for Notion → Odoo ID mapping

**Decision:** Persist `notion_page_id → odoo_article_id` in a local SQLite file (`.notion_odoo_map.db`, configurable via `--store-path` / `SYNC_STORE_PATH`) and use it to decide create vs. update.

**Rationale:**
- Eliminates the title-collision and rename problems of the name-based heuristic (D-004).
- SQLite is in the standard library: no new dependencies, no Odoo custom module required.
- The mapping is validated against Odoo on each run; stale entries (deleted articles) are dropped and the article is recreated.

**Trade-off:** The mapping file must be kept between runs (e.g. mounted as a volume when running in Docker). Losing it falls back to creating new articles.

---

## D-007 — Polling instead of Notion webhooks for change detection

**Decision:** Implement automatic re-sync with a polling loop (`--watch SECONDS`) filtering on `last_edited_time`, not Notion webhooks.

**Rationale:**
- Notion webhooks require a publicly reachable HTTPS endpoint and a subscription managed in the integration settings, a poor fit for a local CLI.
- Polling reuses the existing `--since` filtering and works anywhere the CLI runs, including Docker.

**Trade-off:** Change detection latency is bounded by the polling interval, and each pass costs a few Notion API calls even when nothing changed.

---

## D-005 — Recursive child page sync

**Decision:** When a Notion page contains `child_page` blocks, sync them as children of the parent Odoo article.

**Rationale:**
- Preserves the hierarchical structure of Notion workspaces in Odoo's article tree.
- Keeps the data model intuitive without needing a manual mapping.
