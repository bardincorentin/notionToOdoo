"""Odoo JSON-RPC clients for Knowledge articles.

:class:`OdooClient` targets Odoo 16/17 (``knowledge.article``);
:class:`OdooDocumentPageClient` targets Odoo 15 (``document.page``).
"""

import base64
import logging
import time
import uuid
from typing import Any

import requests

logger = logging.getLogger(__name__)


class OdooAuthError(Exception):
    """Raised when authentication with Odoo fails."""


class OdooAPIError(Exception):
    """Raised when an Odoo JSON-RPC call returns an error."""

    def __init__(self, message: str, data: dict | None = None):
        self.data = data or {}
        super().__init__(message)


class OdooClient:
    """JSON-RPC client for Odoo.

    Authenticates once using ``/web/session/authenticate`` and then reuses
    the session cookie for subsequent calls.

    Compatible with Odoo 16 and 17 (Knowledge module: ``knowledge.article``).
    Subclasses can target other article-like models by overriding the class
    attributes ``MODEL``, ``BODY_FIELD``, ``SUPPORTS_ICON`` and
    ``SUPPORTS_PUBLISH`` (see :class:`OdooDocumentPageClient`).

    Args:
        url: Base URL of the Odoo instance, e.g. ``https://mycompany.odoo.com``.
        database: Name of the Odoo database.
        username: Login e-mail or username.
        password: Account password.
        timeout: HTTP request timeout in seconds.
    """

    MODEL = "knowledge.article"
    BODY_FIELD = "body"
    SUPPORTS_ICON = True
    SUPPORTS_PUBLISH = True

    def __init__(
        self,
        url: str,
        database: str,
        username: str,
        password: str,
        timeout: int = 30,
        max_retries: int = 3,
    ):
        self._url = url.rstrip("/")
        self._database = database
        self._timeout = timeout
        self._max_retries = max_retries
        self._uid: int | None = None

        self._session = requests.Session()
        self._session.headers["Content-Type"] = "application/json"

        self._authenticate(username, password)

    # --------------------------------------------------------- authentication

    def _authenticate(self, username: str, password: str) -> None:
        payload = self._build_payload(
            {
                "db": self._database,
                "login": username,
                "password": password,
            }
        )
        response = self._session.post(
            f"{self._url}/web/session/authenticate",
            json=payload,
            timeout=self._timeout,
        )
        response.raise_for_status()
        result = response.json()
        error = result.get("error")
        if error:
            raise OdooAuthError(
                f"Odoo authentication failed: {error.get('message', error)}"
            )
        uid = result.get("result", {}).get("uid")
        if not uid:
            raise OdooAuthError("Authentication succeeded but no uid returned — check credentials")
        self._uid = uid
        logger.info("Authenticated with Odoo as uid=%s", self._uid)

    # ------------------------------------------------------------ JSON-RPC helpers

    @staticmethod
    def _build_payload(params: dict) -> dict:
        return {
            "jsonrpc": "2.0",
            "method": "call",
            "id": str(uuid.uuid4()),
            "params": params,
        }

    def _call_kw(self, model: str, method: str, args: list, kwargs: dict | None = None) -> Any:
        """Execute a model method via ``/web/dataset/call_kw``.

        Retries up to ``max_retries`` times on ``ConnectionError`` and 5xx
        responses, using exponential backoff (2, 4, 8 … seconds).
        """
        payload = self._build_payload(
            {
                "model": model,
                "method": method,
                "args": args,
                "kwargs": kwargs or {},
            }
        )
        url = f"{self._url}/web/dataset/call_kw"
        for attempt in range(self._max_retries + 1):
            try:
                response = self._session.post(url, json=payload, timeout=self._timeout)
            except requests.ConnectionError:
                if attempt < self._max_retries:
                    wait = 2 ** attempt
                    logger.warning("Odoo connection error, retrying in %ss…", wait)
                    time.sleep(wait)
                    continue
                raise

            if response.status_code >= 500:
                if attempt < self._max_retries:
                    wait = 2 ** attempt
                    logger.warning(
                        "Odoo server error %s, retrying in %ss…", response.status_code, wait
                    )
                    time.sleep(wait)
                # Retries exhausted: fall through to the final "Max retries exceeded".
                continue

            response.raise_for_status()
            result = response.json()
            error = result.get("error")
            if error:
                raise OdooAPIError(
                    error.get("message", str(error)),
                    error.get("data"),
                )
            return result.get("result")

        raise OdooAPIError("Max retries exceeded")

    # -------------------------------------------------------- knowledge.article CRUD

    def create_article(
        self,
        name: str,
        body: str,
        parent_id: int | None = None,
        icon: str = "",
        is_published: bool = False,
    ) -> int:
        """Create a new Knowledge article.

        Returns:
            The ID of the newly created ``knowledge.article`` record.
        """
        vals: dict[str, Any] = {
            "name": name,
            self.BODY_FIELD: body,
        }
        if parent_id is not None:
            vals["parent_id"] = parent_id
        if icon and self.SUPPORTS_ICON:
            vals["icon"] = icon
        if is_published and self.SUPPORTS_PUBLISH:
            vals["is_published"] = True

        article_id = self._call_kw(self.MODEL, "create", [vals])
        logger.info("Created %s id=%s  name=%r", self.MODEL, article_id, name)
        return article_id

    def update_article(
        self,
        article_id: int,
        name: str | None = None,
        body: str | None = None,
        icon: str | None = None,
    ) -> bool:
        """Update an existing article. Only non-None fields are written."""
        vals: dict[str, Any] = {}
        if name is not None:
            vals["name"] = name
        if body is not None:
            vals[self.BODY_FIELD] = body
        if icon is not None and self.SUPPORTS_ICON:
            vals["icon"] = icon
        if not vals:
            return True
        result = self._call_kw(self.MODEL, "write", [[article_id], vals])
        logger.info("Updated %s id=%s", self.MODEL, article_id)
        return bool(result)

    def search_articles(
        self, domain: list | None = None, fields: list[str] | None = None
    ) -> list[dict]:
        """Search articles and return a list of records."""
        return self._call_kw(
            self.MODEL,
            "search_read",
            [domain or []],
            {"fields": fields or ["id", "name"], "limit": 0},
        )

    def article_exists(self, article_id: int) -> bool:
        """Return True if an article with the given ID still exists in Odoo."""
        results = self.search_articles(domain=[["id", "=", article_id]], fields=["id"])
        return bool(results)

    def find_article_by_name(self, name: str, parent_id: int | None = None) -> int | None:
        """Return the id of the first article with the given name (and optional parent), or None."""
        domain: list = [["name", "=", name]]
        if parent_id is not None:
            domain.append(["parent_id", "=", parent_id])
        results = self.search_articles(domain=domain, fields=["id"])
        return results[0]["id"] if results else None

    def upsert_article(
        self,
        name: str,
        body: str,
        parent_id: int | None = None,
        icon: str = "",
        is_published: bool = False,
    ) -> tuple[int, bool]:
        """Create or update an article by name (within the same parent).

        Returns:
            (article_id, created) — created is True if the article was new.
        """
        # (name, parent_id) is the natural key (see DECISIONS.md D-004): the
        # Notion page ID is not stored in Odoo, so name matching is what makes
        # repeated syncs idempotent.
        existing_id = self.find_article_by_name(name, parent_id)
        if existing_id is not None:
            self.update_article(existing_id, name=name, body=body, icon=icon or None)
            return existing_id, False
        article_id = self.create_article(
            name=name,
            body=body,
            parent_id=parent_id,
            icon=icon,
            is_published=is_published,
        )
        return article_id, True

    def create_attachment(self, name: str, raw: bytes, mimetype: str = "") -> int:
        """Upload a file as a public ``ir.attachment`` and return its ID.

        Public attachments are served without authentication at
        ``/web/image/<id>``, which lets article bodies reference them.
        """
        vals: dict[str, Any] = {
            "name": name,
            "datas": base64.b64encode(raw).decode("ascii"),
            "public": True,
        }
        if mimetype:
            vals["mimetype"] = mimetype
        attachment_id = self._call_kw("ir.attachment", "create", [vals])
        logger.info("Created ir.attachment id=%s  name=%r (%d bytes)", attachment_id, name, len(raw))
        return attachment_id

    def check_knowledge_module(self) -> bool:
        """Return True if the article model (``MODEL``) is available on this Odoo instance."""
        try:
            self._call_kw(self.MODEL, "search_read", [[]], {"fields": ["id"], "limit": 1})
            return True
        except OdooAPIError as exc:
            logger.warning("%s not available: %s", self.MODEL, exc)
            return False


class OdooDocumentPageClient(OdooClient):
    """JSON-RPC client for Odoo 15 instances, targeting ``document.page``.

    Odoo 15 predates the Knowledge app; the community ``document_page``
    module stores articles in ``document.page`` with the HTML body in
    ``content`` and no icon/publish fields.
    """

    MODEL = "document.page"
    BODY_FIELD = "content"
    SUPPORTS_ICON = False
    SUPPORTS_PUBLISH = False
