"""Re-host expiring Notion-hosted images as Odoo attachments.

Notion serves workspace-uploaded files through signed S3 URLs that expire
after about one hour, so articles synced with those URLs lose their images.
:class:`ImageRehoster` downloads each Notion-hosted image referenced in an
article body and re-uploads it as a public ``ir.attachment``, rewriting the
``<img src>`` to the permanent ``/web/image/<id>`` Odoo URL. Images hosted
elsewhere (stable external URLs) are left untouched.
"""

import html
import logging
import posixpath
import re
from urllib.parse import unquote, urlparse

import requests

from .odoo.client import OdooClient

logger = logging.getLogger(__name__)

# Hosts whose URLs are signed and expire (Notion-managed storage).
EXPIRING_HOSTS = ("amazonaws.com", "file.notion.so", "notion-static.com")

_IMG_SRC_RE = re.compile(r'(<img[^>]*\bsrc=")([^"]+)(")')


def is_expiring_url(url: str) -> bool:
    """Return True for image URLs served from Notion's expiring storage."""
    host = urlparse(url).netloc.lower()
    return any(host == h or host.endswith(f".{h}") for h in EXPIRING_HOSTS)


class ImageRehoster:
    """Downloads Notion-hosted images and re-uploads them into Odoo.

    Args:
        odoo: Authenticated :class:`OdooClient` used to create attachments.
        timeout: HTTP timeout in seconds for image downloads.
    """

    def __init__(self, odoo: OdooClient, timeout: int = 30):
        self._odoo = odoo
        self._timeout = timeout
        self._session = requests.Session()

    def rehost(self, body_html: str, article_name: str = "") -> str:
        """Rewrite expiring ``<img src>`` URLs in ``body_html`` to Odoo attachments.

        Download or upload failures are logged and leave the original URL in
        place, so a broken image never fails the whole sync.
        """
        def _replace(match: re.Match) -> str:
            prefix, escaped_url, suffix = match.groups()
            url = html.unescape(escaped_url)
            if not is_expiring_url(url):
                return match.group(0)
            new_url = self._rehost_one(url, article_name)
            if new_url is None:
                return match.group(0)
            return f"{prefix}{html.escape(new_url)}{suffix}"

        return _IMG_SRC_RE.sub(_replace, body_html)

    def _rehost_one(self, url: str, article_name: str) -> str | None:
        """Download one image and upload it to Odoo; None on failure."""
        try:
            response = self._session.get(url, timeout=self._timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Could not download image %s: %s", url, exc)
            return None

        filename = self._filename_from_url(url) or "image"
        if article_name:
            filename = f"{article_name} - {filename}"
        mimetype = response.headers.get("Content-Type", "").split(";")[0].strip()

        try:
            attachment_id = self._odoo.create_attachment(filename, response.content, mimetype)
        except Exception as exc:
            logger.warning("Could not upload image %r to Odoo: %s", filename, exc)
            return None

        logger.debug("Re-hosted image %s → attachment %s", url, attachment_id)
        return f"/web/image/{attachment_id}"

    @staticmethod
    def _filename_from_url(url: str) -> str:
        return unquote(posixpath.basename(urlparse(url).path))
