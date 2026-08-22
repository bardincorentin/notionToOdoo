"""Unit tests for OdooClient — all HTTP calls mocked with responses."""

import pytest
import requests
import responses as resp_lib

from src.odoo.client import OdooAPIError, OdooAuthError, OdooClient, OdooDocumentPageClient

ODOO_URL = "https://odoo.example.com"
AUTH_URL = f"{ODOO_URL}/web/session/authenticate"
CALL_URL = f"{ODOO_URL}/web/dataset/call_kw"

AUTH_SUCCESS = {
    "jsonrpc": "2.0",
    "id": "1",
    "result": {"uid": 7, "name": "Test User", "username": "test@example.com"},
}
AUTH_FAIL = {
    "jsonrpc": "2.0",
    "id": "1",
    "error": {"message": "Access Denied", "data": {}},
}


def _call_result(result) -> dict:
    return {"jsonrpc": "2.0", "id": "1", "result": result}


def _call_error(message: str) -> dict:
    return {"jsonrpc": "2.0", "id": "1", "error": {"message": message, "data": {}}}


@pytest.fixture
@resp_lib.activate
def client() -> OdooClient:
    resp_lib.add(resp_lib.POST, AUTH_URL, json=AUTH_SUCCESS, status=200)
    return OdooClient(
        url=ODOO_URL,
        database="testdb",
        username="test@example.com",
        password="secret",
    )


# ---------------------------------------------------------------- auth

class TestAuthentication:
    @resp_lib.activate
    def test_success(self):
        resp_lib.add(resp_lib.POST, AUTH_URL, json=AUTH_SUCCESS, status=200)
        c = OdooClient(ODOO_URL, "db", "user", "pass")
        assert c._uid == 7

    @resp_lib.activate
    def test_failure_raises(self):
        resp_lib.add(resp_lib.POST, AUTH_URL, json=AUTH_FAIL, status=200)
        with pytest.raises(OdooAuthError):
            OdooClient(ODOO_URL, "db", "user", "wrong")

    @resp_lib.activate
    def test_no_uid_raises(self):
        resp_lib.add(
            resp_lib.POST, AUTH_URL,
            json={"jsonrpc": "2.0", "id": "1", "result": {}},
            status=200,
        )
        with pytest.raises(OdooAuthError):
            OdooClient(ODOO_URL, "db", "user", "pass")


# ---------------------------------------------------------------- create_article

class TestCreateArticle:
    @resp_lib.activate
    def test_returns_id(self, client):
        resp_lib.add(resp_lib.POST, CALL_URL, json=_call_result(42), status=200)
        article_id = client.create_article("My Article", "<p>body</p>")
        assert article_id == 42

    @resp_lib.activate
    def test_with_parent(self, client):
        resp_lib.add(resp_lib.POST, CALL_URL, json=_call_result(10), status=200)
        article_id = client.create_article("Child", "<p>x</p>", parent_id=5)
        assert article_id == 10
        call_body = resp_lib.calls[0].request.body
        import json
        body = json.loads(call_body)
        assert body["params"]["args"][0]["parent_id"] == 5

    @resp_lib.activate
    def test_api_error_raises(self, client):
        resp_lib.add(resp_lib.POST, CALL_URL, json=_call_error("Access Denied"), status=200)
        with pytest.raises(OdooAPIError):
            client.create_article("X", "<p>y</p>")


# ---------------------------------------------------------------- update_article

class TestUpdateArticle:
    @resp_lib.activate
    def test_updates_fields(self, client):
        resp_lib.add(resp_lib.POST, CALL_URL, json=_call_result(True), status=200)
        result = client.update_article(42, name="New Name", body="<p>new</p>")
        assert result is True

    def test_no_op_returns_true(self, client):
        # No request should be made if nothing to update
        result = client.update_article(42)
        assert result is True


# ---------------------------------------------------------------- search_articles

class TestSearchArticles:
    @resp_lib.activate
    def test_returns_list(self, client):
        resp_lib.add(
            resp_lib.POST, CALL_URL,
            json=_call_result([{"id": 1, "name": "Article A"}]),
            status=200,
        )
        results = client.search_articles()
        assert results[0]["id"] == 1


# ---------------------------------------------------------------- find_article_by_name

class TestFindArticleByName:
    @resp_lib.activate
    def test_found(self, client):
        resp_lib.add(
            resp_lib.POST, CALL_URL,
            json=_call_result([{"id": 5, "name": "Target"}]),
            status=200,
        )
        assert client.find_article_by_name("Target") == 5

    @resp_lib.activate
    def test_not_found(self, client):
        resp_lib.add(resp_lib.POST, CALL_URL, json=_call_result([]), status=200)
        assert client.find_article_by_name("Missing") is None


# ---------------------------------------------------------------- upsert_article

class TestUpsertArticle:
    @resp_lib.activate
    def test_creates_when_not_exists(self, client):
        # search returns nothing
        resp_lib.add(resp_lib.POST, CALL_URL, json=_call_result([]), status=200)
        # create returns id
        resp_lib.add(resp_lib.POST, CALL_URL, json=_call_result(99), status=200)
        article_id, created = client.upsert_article("New", "<p>body</p>")
        assert article_id == 99
        assert created is True

    @resp_lib.activate
    def test_updates_when_exists(self, client):
        # search returns existing
        resp_lib.add(
            resp_lib.POST, CALL_URL,
            json=_call_result([{"id": 7, "name": "Existing"}]),
            status=200,
        )
        # update returns True
        resp_lib.add(resp_lib.POST, CALL_URL, json=_call_result(True), status=200)
        article_id, created = client.upsert_article("Existing", "<p>updated</p>")
        assert article_id == 7
        assert created is False


# ---------------------------------------------------------------- check_knowledge_module

class TestCheckKnowledgeModule:
    @resp_lib.activate
    def test_available(self, client):
        resp_lib.add(resp_lib.POST, CALL_URL, json=_call_result([]), status=200)
        assert client.check_knowledge_module() is True

    @resp_lib.activate
    def test_not_available(self, client):
        resp_lib.add(resp_lib.POST, CALL_URL, json=_call_error("Model not found"), status=200)
        assert client.check_knowledge_module() is False


# ---------------------------------------------------------------- retry logic

class TestRetryLogic:
    """_call_kw must retry on ConnectionError and 5xx, with exponential backoff."""

    @resp_lib.activate
    def test_retries_on_connection_error(self):
        resp_lib.add(resp_lib.POST, AUTH_URL, json=AUTH_SUCCESS, status=200)
        client = OdooClient(ODOO_URL, "db", "user", "pass", max_retries=2)

        # First call raises ConnectionError, second succeeds
        resp_lib.add(resp_lib.POST, CALL_URL, body=requests.ConnectionError("boom"))
        resp_lib.add(resp_lib.POST, CALL_URL, json=_call_result(42), status=200)

        article_id = client.create_article("Test", "<p>body</p>")
        assert article_id == 42

    @resp_lib.activate
    def test_retries_on_5xx(self):
        resp_lib.add(resp_lib.POST, AUTH_URL, json=AUTH_SUCCESS, status=200)
        client = OdooClient(ODOO_URL, "db", "user", "pass", max_retries=2)

        resp_lib.add(resp_lib.POST, CALL_URL, status=502)
        resp_lib.add(resp_lib.POST, CALL_URL, json=_call_result(7), status=200)

        article_id = client.create_article("Test", "<p>body</p>")
        assert article_id == 7

    @resp_lib.activate
    def test_raises_after_max_retries_connection_error(self):
        resp_lib.add(resp_lib.POST, AUTH_URL, json=AUTH_SUCCESS, status=200)
        client = OdooClient(ODOO_URL, "db", "user", "pass", max_retries=1)

        # max_retries=1 → 2 attempts total, both fail
        for _ in range(2):
            resp_lib.add(resp_lib.POST, CALL_URL, body=requests.ConnectionError("doom"))

        with pytest.raises(requests.ConnectionError):
            client.create_article("Test", "<p>body</p>")

    @resp_lib.activate
    def test_raises_after_max_retries_5xx(self):
        resp_lib.add(resp_lib.POST, AUTH_URL, json=AUTH_SUCCESS, status=200)
        client = OdooClient(ODOO_URL, "db", "user", "pass", max_retries=1)

        # max_retries=1 → 2 attempts total, both 500
        resp_lib.add(resp_lib.POST, CALL_URL, status=500)
        resp_lib.add(resp_lib.POST, CALL_URL, status=500)

        with pytest.raises(OdooAPIError, match="Max retries exceeded"):
            client.create_article("Test", "<p>body</p>")


# ---------------------------------------------------------------- create_attachment

class TestCreateAttachment:
    @resp_lib.activate
    def test_uploads_public_base64_attachment(self, client):
        resp_lib.add(resp_lib.POST, CALL_URL, json=_call_result(314), status=200)
        attachment_id = client.create_attachment("logo.png", b"\x89PNG", "image/png")
        assert attachment_id == 314

        import base64
        import json
        body = json.loads(resp_lib.calls[0].request.body)
        assert body["params"]["model"] == "ir.attachment"
        vals = body["params"]["args"][0]
        assert vals["name"] == "logo.png"
        assert vals["public"] is True
        assert vals["mimetype"] == "image/png"
        assert base64.b64decode(vals["datas"]) == b"\x89PNG"

    @resp_lib.activate
    def test_mimetype_omitted_when_unknown(self, client):
        resp_lib.add(resp_lib.POST, CALL_URL, json=_call_result(1), status=200)
        client.create_attachment("blob", b"data")
        import json
        vals = json.loads(resp_lib.calls[0].request.body)["params"]["args"][0]
        assert "mimetype" not in vals


# ---------------------------------------------------------------- Odoo 15 (document.page)

class TestOdooDocumentPageClient:
    @pytest.fixture
    @resp_lib.activate
    def legacy_client(self) -> OdooDocumentPageClient:
        resp_lib.add(resp_lib.POST, AUTH_URL, json=AUTH_SUCCESS, status=200)
        return OdooDocumentPageClient(
            url=ODOO_URL, database="testdb", username="u", password="p"
        )

    @resp_lib.activate
    def test_create_targets_document_page_with_content_field(self, legacy_client):
        resp_lib.add(resp_lib.POST, CALL_URL, json=_call_result(11), status=200)
        article_id = legacy_client.create_article(
            "Page", "<p>x</p>", icon="📄", is_published=True
        )
        assert article_id == 11

        import json
        body = json.loads(resp_lib.calls[0].request.body)
        assert body["params"]["model"] == "document.page"
        vals = body["params"]["args"][0]
        assert vals["content"] == "<p>x</p>"
        assert "body" not in vals
        # document.page has no icon / is_published fields
        assert "icon" not in vals
        assert "is_published" not in vals

    @resp_lib.activate
    def test_update_writes_content_field(self, legacy_client):
        resp_lib.add(resp_lib.POST, CALL_URL, json=_call_result(True), status=200)
        legacy_client.update_article(11, body="<p>new</p>", icon="📄")

        import json
        body = json.loads(resp_lib.calls[0].request.body)
        assert body["params"]["model"] == "document.page"
        vals = body["params"]["args"][1]
        assert vals == {"content": "<p>new</p>"}

    @resp_lib.activate
    def test_search_targets_document_page(self, legacy_client):
        resp_lib.add(resp_lib.POST, CALL_URL, json=_call_result([{"id": 3}]), status=200)
        assert legacy_client.find_article_by_name("Page") == 3

        import json
        body = json.loads(resp_lib.calls[0].request.body)
        assert body["params"]["model"] == "document.page"

    @resp_lib.activate
    def test_check_module_uses_document_page(self, legacy_client):
        resp_lib.add(resp_lib.POST, CALL_URL, json=_call_result([]), status=200)
        assert legacy_client.check_knowledge_module() is True

        import json
        body = json.loads(resp_lib.calls[0].request.body)
        assert body["params"]["model"] == "document.page"
