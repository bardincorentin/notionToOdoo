"""Notion API client — wraps the official REST API v1."""

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

NOTION_BASE_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
DEFAULT_PAGE_SIZE = 100


class NotionAPIError(Exception):
    """Raised when the Notion API returns an error."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"Notion API error {status_code}: {message}")


class NotionClient:
    """HTTP client for the Notion REST API.

    Args:
        token: Notion integration secret token.
        timeout: Request timeout in seconds.
        max_retries: Maximum number of retries on 429 / 5xx errors.
    """

    def __init__(self, token: str, timeout: int = 30, max_retries: int = 3):
        if not token:
            raise ValueError("Notion integration token is required")
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            }
        )
        self._timeout = timeout
        self._max_retries = max_retries

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
    ) -> Any:
        url = f"{NOTION_BASE_URL}{path}"
        for attempt in range(self._max_retries + 1):
            try:
                response = self._session.request(
                    method, url, params=params, json=json, timeout=self._timeout
                )
            except requests.ConnectionError:
                if attempt < self._max_retries:
                    wait = 2 ** attempt
                    logger.warning("Connection error, retrying in %ss…", wait)
                    time.sleep(wait)
                    continue
                raise

            # Rate limiting: Notion sends a Retry-After header on 429; honour it
            # instead of the exponential backoff used for connection/5xx errors.
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 2 ** attempt))
                logger.warning("Rate limited by Notion API, waiting %ss…", retry_after)
                time.sleep(retry_after)
                continue

            if response.status_code >= 500 and attempt < self._max_retries:
                wait = 2 ** attempt
                logger.warning("Server error %s, retrying in %ss…", response.status_code, wait)
                time.sleep(wait)
                continue

            if not response.ok:
                data = response.json() if response.content else {}
                raise NotionAPIError(
                    response.status_code,
                    data.get("message", response.text),
                )

            return response.json()

        raise NotionAPIError(500, "Max retries exceeded")

    # ------------------------------------------------------------------ pages

    def get_page(self, page_id: str) -> dict:
        """Fetch page metadata (not the content blocks)."""
        return self._request("GET", f"/pages/{page_id}")

    # ----------------------------------------------------------------- blocks

    def get_block_children(self, block_id: str) -> list[dict]:
        """Recursively fetch all children blocks of a block/page."""
        blocks: list[dict] = []
        cursor: str | None = None

        # The Notion API caps each response at 100 results, so cursor-based
        # pagination is required to fetch everything.
        while True:
            params: dict = {"page_size": DEFAULT_PAGE_SIZE}
            if cursor:
                params["start_cursor"] = cursor

            data = self._request("GET", f"/blocks/{block_id}/children", params=params)
            blocks.extend(data.get("results", []))

            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

        # Recursively fetch children of blocks that have children
        for block in blocks:
            if block.get("has_children"):
                block["children"] = self.get_block_children(block["id"])
            else:
                block["children"] = []

        return blocks

    # --------------------------------------------------------------- databases

    def get_database(self, database_id: str) -> dict:
        """Fetch database metadata (title, properties schema)."""
        return self._request("GET", f"/databases/{database_id}")

    def query_database(
        self, database_id: str, filter_obj: dict | None = None, sorts: list | None = None
    ) -> list[dict]:
        """Return all pages in a Notion database."""
        pages: list[dict] = []
        cursor: str | None = None

        body: dict = {"page_size": DEFAULT_PAGE_SIZE}
        if filter_obj:
            body["filter"] = filter_obj
        if sorts:
            body["sorts"] = sorts

        while True:
            if cursor:
                body["start_cursor"] = cursor

            data = self._request("POST", f"/databases/{database_id}/query", json=body)
            pages.extend(data.get("results", []))

            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

        return pages

    def search(self, query: str = "", *, object_type: str = "page") -> list[dict]:
        """Search across all pages/databases accessible to the integration."""
        results: list[dict] = []
        cursor: str | None = None

        while True:
            body: dict = {
                "query": query,
                "filter": {"object": object_type},
                "page_size": DEFAULT_PAGE_SIZE,
            }
            if cursor:
                body["start_cursor"] = cursor

            data = self._request("POST", "/search", json=body)
            results.extend(data.get("results", []))

            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

        return results
