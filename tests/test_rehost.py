"""Unit tests for the image rehoster (downloads mocked with responses)."""

from unittest.mock import MagicMock

import responses as resp_lib

from src.rehost import ImageRehoster, is_expiring_url

NOTION_IMG = (
    "https://prod-files-secure.s3.us-west-2.amazonaws.com/abc/img.png"
    "?X-Amz-Signature=sig&X-Amz-Expires=3600"
)
EXTERNAL_IMG = "https://example.com/static/logo.png"


class TestIsExpiringUrl:
    def test_amazonaws_hosts_expire(self):
        assert is_expiring_url(NOTION_IMG) is True

    def test_file_notion_so_expires(self):
        assert is_expiring_url("https://file.notion.so/f/abc/img.png?id=1") is True

    def test_notion_static_expires(self):
        assert is_expiring_url("https://s3.notion-static.com/img.png") is True

    def test_external_hosts_do_not_expire(self):
        assert is_expiring_url(EXTERNAL_IMG) is False

    def test_lookalike_host_does_not_expire(self):
        assert is_expiring_url("https://notamazonaws.com/img.png") is False


class TestRehost:
    def _rehoster(self, attachment_id: int = 55) -> tuple[ImageRehoster, MagicMock]:
        odoo = MagicMock()
        odoo.create_attachment.return_value = attachment_id
        return ImageRehoster(odoo), odoo

    @resp_lib.activate
    def test_rewrites_notion_hosted_image(self):
        resp_lib.add(
            resp_lib.GET, NOTION_IMG, body=b"\x89PNG",
            status=200, content_type="image/png",
        )
        rehoster, odoo = self._rehoster()
        import html as html_lib
        body = f'<figure><img src="{html_lib.escape(NOTION_IMG)}" alt="x"/></figure>'
        result = rehoster.rehost(body, article_name="My Page")
        assert '<img src="/web/image/55" alt="x"/>' in result
        name, raw, mimetype = odoo.create_attachment.call_args.args
        assert name == "My Page - img.png"
        assert raw == b"\x89PNG"
        assert mimetype == "image/png"

    def test_external_image_left_untouched(self):
        rehoster, odoo = self._rehoster()
        body = f'<img src="{EXTERNAL_IMG}"/>'
        assert rehoster.rehost(body) == body
        odoo.create_attachment.assert_not_called()

    @resp_lib.activate
    def test_download_failure_keeps_original_url(self):
        resp_lib.add(resp_lib.GET, NOTION_IMG, status=403)
        rehoster, odoo = self._rehoster()
        import html as html_lib
        body = f'<img src="{html_lib.escape(NOTION_IMG)}"/>'
        assert rehoster.rehost(body) == body
        odoo.create_attachment.assert_not_called()

    @resp_lib.activate
    def test_upload_failure_keeps_original_url(self):
        resp_lib.add(resp_lib.GET, NOTION_IMG, body=b"x", status=200)
        rehoster, odoo = self._rehoster()
        odoo.create_attachment.side_effect = Exception("Odoo down")
        import html as html_lib
        body = f'<img src="{html_lib.escape(NOTION_IMG)}"/>'
        assert rehoster.rehost(body) == body

    @resp_lib.activate
    def test_multiple_images_rehosted_independently(self):
        resp_lib.add(resp_lib.GET, "https://file.notion.so/a.png", body=b"a", status=200)
        resp_lib.add(resp_lib.GET, "https://file.notion.so/b.png", body=b"b", status=200)
        rehoster, odoo = self._rehoster()
        odoo.create_attachment.side_effect = [1, 2]
        body = (
            '<img src="https://file.notion.so/a.png"/>'
            f'<img src="{EXTERNAL_IMG}"/>'
            '<img src="https://file.notion.so/b.png"/>'
        )
        result = rehoster.rehost(body)
        assert '<img src="/web/image/1"/>' in result
        assert '<img src="/web/image/2"/>' in result
        assert EXTERNAL_IMG in result

    def test_body_without_images_unchanged(self):
        rehoster, odoo = self._rehoster()
        body = "<p>Hello</p>"
        assert rehoster.rehost(body) == body
