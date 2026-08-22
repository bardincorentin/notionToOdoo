"""Unit tests for NotionClient — all HTTP calls are mocked with responses."""

import pytest
import responses as resp_lib

from src.notion.client import NOTION_BASE_URL, NotionAPIError, NotionClient

BASE = NOTION_BASE_URL


@pytest.fixture
def client() -> NotionClient:
    return NotionClient(token="secret_test_token")


# ---------------------------------------------------------------- constructor

class TestInit:
    def test_requires_token(self):
        with pytest.raises(ValueError):
            NotionClient(token="")

    def test_sets_headers(self, client):
        headers = client._session.headers
        assert "Bearer secret_test_token" in headers.get("Authorization", "")
        assert headers.get("Notion-Version")


# ---------------------------------------------------------------- get_page

class TestGetPage:
    @resp_lib.activate
    def test_returns_page(self, client):
        resp_lib.add(
            resp_lib.GET,
            f"{BASE}/pages/abc123",
            json={"object": "page", "id": "abc123"},
            status=200,
        )
        page = client.get_page("abc123")
        assert page["id"] == "abc123"

    @resp_lib.activate
    def test_raises_on_error(self, client):
        resp_lib.add(
            resp_lib.GET,
            f"{BASE}/pages/bad",
            json={"message": "Not found"},
            status=404,
        )
        with pytest.raises(NotionAPIError) as exc_info:
            client.get_page("bad")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------- get_block_children

class TestGetBlockChildren:
    @resp_lib.activate
    def test_single_page(self, client):
        resp_lib.add(
            resp_lib.GET,
            f"{BASE}/blocks/page1/children",
            json={
                "results": [
                    {"id": "b1", "type": "paragraph", "has_children": False, "paragraph": {}}
                ],
                "has_more": False,
                "next_cursor": None,
            },
            status=200,
        )
        blocks = client.get_block_children("page1")
        assert len(blocks) == 1
        assert blocks[0]["id"] == "b1"
        assert blocks[0]["children"] == []

    @resp_lib.activate
    def test_pagination(self, client):
        resp_lib.add(
            resp_lib.GET,
            f"{BASE}/blocks/page1/children",
            json={
                "results": [{"id": "b1", "type": "paragraph", "has_children": False, "paragraph": {}}],
                "has_more": True,
                "next_cursor": "cursor1",
            },
            status=200,
        )
        resp_lib.add(
            resp_lib.GET,
            f"{BASE}/blocks/page1/children",
            json={
                "results": [{"id": "b2", "type": "paragraph", "has_children": False, "paragraph": {}}],
                "has_more": False,
                "next_cursor": None,
            },
            status=200,
        )
        blocks = client.get_block_children("page1")
        assert len(blocks) == 2

    @resp_lib.activate
    def test_fetches_nested_children(self, client):
        # Parent block that has children
        resp_lib.add(
            resp_lib.GET,
            f"{BASE}/blocks/page1/children",
            json={
                "results": [
                    {"id": "parent_b", "type": "toggle", "has_children": True, "toggle": {}}
                ],
                "has_more": False,
                "next_cursor": None,
            },
            status=200,
        )
        # Children of parent_b
        resp_lib.add(
            resp_lib.GET,
            f"{BASE}/blocks/parent_b/children",
            json={
                "results": [
                    {"id": "child_b", "type": "paragraph", "has_children": False, "paragraph": {}}
                ],
                "has_more": False,
                "next_cursor": None,
            },
            status=200,
        )
        blocks = client.get_block_children("page1")
        assert blocks[0]["children"][0]["id"] == "child_b"


# ---------------------------------------------------------------- query_database

class TestQueryDatabase:
    @resp_lib.activate
    def test_returns_pages(self, client):
        resp_lib.add(
            resp_lib.POST,
            f"{BASE}/databases/db1/query",
            json={
                "results": [{"id": "p1"}, {"id": "p2"}],
                "has_more": False,
                "next_cursor": None,
            },
            status=200,
        )
        pages = client.query_database("db1")
        assert len(pages) == 2


# ---------------------------------------------------------------- rate limiting

class TestRateLimiting:
    @resp_lib.activate
    def test_retries_on_429(self, client):
        resp_lib.add(
            resp_lib.GET,
            f"{BASE}/pages/page1",
            headers={"Retry-After": "0"},
            status=429,
        )
        resp_lib.add(
            resp_lib.GET,
            f"{BASE}/pages/page1",
            json={"id": "page1"},
            status=200,
        )
        page = client.get_page("page1")
        assert page["id"] == "page1"

    @resp_lib.activate
    def test_raises_after_max_retries(self, client):
        for _ in range(4):  # max_retries=3 + 1 initial
            resp_lib.add(
                resp_lib.GET,
                f"{BASE}/pages/page1",
                headers={"Retry-After": "0"},
                status=429,
            )
        with pytest.raises(NotionAPIError):
            client.get_page("page1")


# ---------------------------------------------------------------- get_database

class TestGetDatabase:
    @resp_lib.activate
    def test_returns_database(self, client):
        resp_lib.add(
            resp_lib.GET,
            f"{BASE}/databases/db1",
            json={"object": "database", "id": "db1", "title": [{"plain_text": "Tasks"}]},
            status=200,
        )
        database = client.get_database("db1")
        assert database["id"] == "db1"

    @resp_lib.activate
    def test_error_raises(self, client):
        resp_lib.add(
            resp_lib.GET,
            f"{BASE}/databases/db1",
            json={"message": "Not found"},
            status=404,
        )
        with pytest.raises(NotionAPIError):
            client.get_database("db1")
