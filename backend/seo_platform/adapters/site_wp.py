"""WordPress-style deployment adapter (FDD FR-10.4, TDD section 9).

Talks to the companion plugin's REST API with HMAC-signed requests. Locally
the "plugin" is the demo site's /wp-json/seosys/v1 API. The same interface
(`apply`, `revert`, `current_value`) would be implemented by the Shopify app
and the GitHub App adapters.
"""
from __future__ import annotations

import json
import secrets
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from ..net import make_client

API_PREFIX = "/wp-json/seosys/v1"


def sign(secret: str, timestamp: str, nonce: str, method: str, path: str, body: bytes) -> str:
    """HMAC-SHA256 over timestamp.nonce.METHOD.path.body; binds the signature to one exact request."""
    import hashlib
    import hmac

    msg = b".".join([timestamp.encode(), nonce.encode(), method.upper().encode(), path.encode(), body])
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


class AdapterError(RuntimeError):
    pass


class WordPressAdapter:
    def __init__(self, base_url: str, secret: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.secret = secret

    def _headers(self, method: str, path: str, body: bytes) -> dict[str, str]:
        ts, nonce = str(time.time()), secrets.token_hex(12)
        return {"x-seo-timestamp": ts, "x-seo-nonce": nonce,
                "x-seo-signature": sign(self.secret, ts, nonce, method, path, body),
                "content-type": "application/json"}

    async def _call(self, method: str, endpoint: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps(payload).encode() if payload is not None else b""
        async with make_client() as client:
            try:
                url = self.base_url + API_PREFIX + endpoint
                resp = await client.request(method, url, content=body,
                                            headers=self._headers(method, urlparse(url).path, body))
            except httpx.HTTPError as exc:
                raise AdapterError(f"the website could not be reached ({exc})") from exc
        if resp.status_code >= 400:
            raise AdapterError(f"the plugin answered with HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except ValueError as exc:
            raise AdapterError(f"the plugin sent an unreadable answer (HTTP {resp.status_code})") from exc

    async def state(self) -> dict[str, Any]:
        return await self._call("GET", "/pages")

    async def current_value(self, change_type: str, target: dict[str, Any]) -> Any:
        st = await self.state()
        if change_type == "redirect":
            return st["redirects"].get(target["source"])
        if change_type == "robots_txt":
            return st["robots_txt"]
        page = next((p for p in st["pages"] if p["path"] == target["path"]), None)
        if page is None:
            raise AdapterError(f"the plugin does not manage the page {target['path']}")
        if change_type == "image_alt":
            img = next((i for i in page["images"] if i["src"] == target["image_src"]), None)
            if img is None:
                raise AdapterError(f"the image {target['image_src']} is no longer on the page")
            return img["alt"]
        return page[target["field"]]

    async def write(self, change_type: str, target: dict[str, Any], value: Any) -> dict[str, Any]:
        if change_type == "redirect":
            return await self._call("POST", "/redirects", {"source": target["source"], "target": value})
        if change_type == "robots_txt":
            return await self._call("POST", "/robots", {"content": value})
        if change_type == "image_alt":
            return await self._call("POST", "/update", {"path": target["path"], "field": "image_alt",
                                                        "image_src": target["image_src"], "value": value})
        return await self._call("POST", "/update", {"path": target["path"], "field": target["field"], "value": value})
