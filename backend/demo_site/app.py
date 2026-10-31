"""Demo client website: "Lone Star Comfort HVAC".

Plays the role of a client's WordPress site in the proof of concept:
- Public pages that the platform crawls (seeded with real SEO problems).
- A signed REST API that mimics the WordPress plugin the platform would install
  (FDD M10 / TDD section 9). Only signed requests can change content.
- Dev-only endpoints to reset the site and to inject a fault, so the
  post-deploy verification and automatic rollback can be demonstrated.

Run:  uvicorn demo_site.app:app --port 8001   (from the backend folder)
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import html
import json
import math
import os
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response

SEED_PATH = Path(__file__).with_name("seed.json")
STATE_PATH = Path(os.environ.get("DEMO_SITE_STATE", Path(__file__).with_name("site_state.json")))
SECRET = os.environ.get("DEMO_SITE_SECRET", "local-dev-secret-change-me")
MAX_CLOCK_SKEW_S = 300

EDITABLE_FIELDS = {"title", "meta_description", "h1", "canonical", "noindex", "in_sitemap", "schema_jsonld", "body_html"}


class SiteStore:
    """Thread-safe JSON-file store standing in for the WordPress database."""

    def __init__(self, seed_path: Path, state_path: Path | None) -> None:
        self._seed_path = seed_path
        self._state_path = state_path
        self._lock = threading.Lock()
        self.fault_mode = False
        self._seen_nonces: dict[str, float] = {}
        if state_path and state_path.exists():
            self.state = json.loads(state_path.read_text(encoding="utf-8"))
        else:
            self.reset()

    def reset(self) -> None:
        with self._lock:
            self.state = json.loads(self._seed_path.read_text(encoding="utf-8"))
            for page in self.state["pages"]:
                page["broken"] = False
            self.fault_mode = False
            self._save()

    def _save(self) -> None:
        if self._state_path:
            self._state_path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    def page(self, path: str) -> dict[str, Any] | None:
        return next((p for p in self.state["pages"] if p["path"] == path), None)

    def update_field(self, path: str, field: str, value: Any, image_src: str | None = None) -> dict[str, Any]:
        with self._lock:
            page = self.page(path)
            if page is None:
                raise KeyError(path)
            if field == "image_alt":
                img = next((i for i in page["images"] if i["src"] == image_src), None)
                if img is None:
                    raise KeyError(image_src)
                before = img["alt"]
                img["alt"] = value
            elif field in EDITABLE_FIELDS:
                before = page[field]
                page[field] = value
            else:
                raise ValueError(f"field not editable: {field}")
            # Fault injection is one-shot: the next write breaks the page (like a plugin conflict);
            # any later write (e.g. the platform's automatic rollback) restores it.
            page["broken"] = self.fault_mode
            self.fault_mode = False
            self._save()
            return {"path": path, "field": field, "before": before, "after": value}

    def set_redirect(self, source: str, target: str | None) -> dict[str, Any]:
        with self._lock:
            before = self.state["redirects"].get(source)
            if target is None:
                self.state["redirects"].pop(source, None)
            else:
                self.state["redirects"][source] = target
            self._save()
            return {"source": source, "before": before, "after": target}

    def set_robots(self, content: str) -> dict[str, Any]:
        with self._lock:
            before = self.state["robots_txt"]
            self.state["robots_txt"] = content
            self._save()
            return {"before": before, "after": content}

    def check_nonce(self, nonce: str, timestamp: float) -> bool:
        """Remember each nonce until its timestamp can no longer pass the freshness check.
        (Kept in memory: a real plugin stores them in the WordPress database so restarts can't enable replays.)"""
        now = time.time()
        with self._lock:
            for n, expires in list(self._seen_nonces.items()):
                if now > expires:
                    del self._seen_nonces[n]
            if nonce in self._seen_nonces:
                return False
            self._seen_nonces[nonce] = timestamp + MAX_CLOCK_SKEW_S
            return True


def sign(secret: str, timestamp: str, nonce: str, method: str, path: str, body: bytes) -> str:
    """HMAC-SHA256 over timestamp.nonce.METHOD.path.body (same function the platform adapter uses)."""
    msg = b".".join([timestamp.encode(), nonce.encode(), method.upper().encode(), path.encode(), body])
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def create_app(state_path: Path | None = STATE_PATH, secret: str = SECRET) -> FastAPI:
    store = SiteStore(SEED_PATH, state_path)
    app = FastAPI(title="Demo client site (Lone Star Comfort HVAC)", docs_url="/__docs")
    app.state.store = store

    async def verify_signature(request: Request) -> bytes:
        body = await request.body()
        ts = request.headers.get("x-seo-timestamp", "")
        nonce = request.headers.get("x-seo-nonce", "")
        sig = request.headers.get("x-seo-signature", "")
        try:
            ts_value = float(ts)
        except ValueError:
            raise HTTPException(401, "missing or bad timestamp")
        if not math.isfinite(ts_value) or abs(time.time() - ts_value) > MAX_CLOCK_SKEW_S:
            raise HTTPException(401, "stale or invalid timestamp")
        expected = sign(secret, ts, nonce, request.method, request.url.path, body)
        if not nonce or not hmac.compare_digest(expected, sig):
            raise HTTPException(401, "bad signature")
        if not store.check_nonce(nonce, ts_value):
            raise HTTPException(401, "replayed request")
        return body

    # ---------- signed "plugin" API (what the platform's adapter calls) ----------
    api = "/wp-json/seo-poc/v1"

    @app.get(api + "/pages")
    async def list_pages(request: Request) -> JSONResponse:
        await verify_signature(request)
        pages = [{k: v for k, v in p.items() if k != "body_html"} for p in store.state["pages"]]
        return JSONResponse({"pages": pages, "redirects": store.state["redirects"], "robots_txt": store.state["robots_txt"]})

    @app.post(api + "/update")
    async def update(request: Request) -> JSONResponse:
        body = json.loads(await verify_signature(request) or b"{}")
        try:
            result = store.update_field(body["path"], body["field"], body["value"], body.get("image_src"))
        except KeyError as exc:
            raise HTTPException(404, f"not found: {exc}")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse(result)

    @app.post(api + "/redirects")
    async def redirects(request: Request) -> JSONResponse:
        body = json.loads(await verify_signature(request) or b"{}")
        return JSONResponse(store.set_redirect(body["source"], body.get("target")))

    @app.post(api + "/robots")
    async def robots_update(request: Request) -> JSONResponse:
        body = json.loads(await verify_signature(request) or b"{}")
        return JSONResponse(store.set_robots(body["content"]))

    # ---------- dev-only controls (would not exist on a real site) ----------
    @app.post("/__demo/reset")
    async def demo_reset() -> dict[str, Any]:
        store.reset()
        return {"ok": True}

    @app.post("/__demo/fault")
    async def demo_fault(request: Request) -> dict[str, Any]:
        body = await request.json()
        store.fault_mode = bool(body.get("on"))
        return {"fault_mode": store.fault_mode}

    @app.get("/__demo/state")
    async def demo_state() -> dict[str, Any]:
        return {"fault_mode": store.fault_mode, "state": store.state}

    # ---------- public website ----------
    @app.get("/robots.txt", response_class=PlainTextResponse)
    async def robots(request: Request) -> str:
        base = str(request.base_url).rstrip("/")
        return store.state["robots_txt"].rstrip("\n") + f"\n\nSitemap: {base}/sitemap.xml\n"

    @app.get("/sitemap.xml")
    async def sitemap(request: Request) -> Response:
        base = str(request.base_url).rstrip("/")
        urls = "".join(
            f"<url><loc>{base}{html.escape(p['path'])}</loc></url>"
            for p in store.state["pages"]
            if p["in_sitemap"]
        )
        xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
        return Response(xml, media_type="application/xml")

    @app.get("/img/{name}")
    async def image(name: str) -> Response:
        label = html.escape(name.rsplit(".", 1)[0])
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="320">'
            '<rect width="100%" height="100%" fill="#dfe7ef"/>'
            f'<text x="50%" y="50%" text-anchor="middle" font-family="sans-serif" font-size="28" fill="#456">{label}</text></svg>'
        )
        return Response(svg, media_type="image/svg+xml")

    @app.get("/{path:path}")
    async def page(path: str, request: Request) -> Response:
        url_path = "/" + path if not path.startswith("/") else path
        if url_path != "/" and url_path.endswith("/"):
            url_path = url_path.rstrip("/")
        redirects_map = store.state["redirects"]
        if url_path in redirects_map:
            return RedirectResponse(redirects_map[url_path], status_code=301)
        p = store.page(url_path)
        if p is None:
            return HTMLResponse(render_not_found(store.state["business"]), status_code=404)
        if p.get("broken"):
            return HTMLResponse("<h1>Internal Server Error</h1>", status_code=500)
        return HTMLResponse(render_page(p, store.state, str(request.base_url).rstrip("/")))

    return app


NAV = [("/", "Home"), ("/services/ac-repair", "AC Repair"), ("/services/furnace-repair", "Furnace Repair"),
       ("/emergency-hvac", "Emergency"), ("/about", "About"), ("/contact", "Contact")]


def render_page(p: dict[str, Any], state: dict[str, Any], base: str) -> str:
    biz = state["business"]
    e = html.escape
    head = [f"<title>{e(p['title'])}</title>", '<meta name="viewport" content="width=device-width, initial-scale=1">']
    if p["meta_description"]:
        head.append(f'<meta name="description" content="{e(p["meta_description"])}">')
    if p["noindex"]:
        head.append('<meta name="robots" content="noindex, follow">')
    if p["canonical"]:
        head.append(f'<link rel="canonical" href="{e(base + p["canonical"])}">')
    if p["schema_jsonld"]:
        # Defence in depth: never let stored JSON close the script tag.
        safe = p["schema_jsonld"].replace("<", "\\u003c").replace(">", "\\u003e")
        head.append(f'<script type="application/ld+json">{safe}</script>')
    nav = "".join(f'<a href="{href}">{label}</a>' for href, label in NAV)
    imgs = "".join(f'<img src="{e(i["src"])}" alt="{e(i["alt"])}" width="640" height="320">' for i in p["images"])
    h1 = f"<h1>{e(p['h1'])}</h1>" if p["h1"] else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">{''.join(head)}
<style>body{{font-family:Georgia,serif;max-width:760px;margin:0 auto;padding:0 20px;color:#1d2a35;line-height:1.6}}
header{{display:flex;gap:16px;flex-wrap:wrap;padding:18px 0;border-bottom:3px solid #c0392b}}header strong{{margin-right:auto}}
a{{color:#9b2c1f}}img{{max-width:100%;height:auto;margin:12px 0;border-radius:6px}}footer{{margin:40px 0;font-size:14px;color:#556}}</style>
</head><body><header><strong>{e(biz['name'])}</strong>{nav}</header><main>{h1}{imgs}{p['body_html']}</main>
<footer>{e(biz['name'])} · {e(biz['street'])}, {e(biz['city'])}, {e(biz['region'])} {e(biz['postal_code'])} · {e(biz['phone'])}</footer>
</body></html>"""


def render_not_found(biz: dict[str, Any]) -> str:
    return f"<!doctype html><html><head><title>Page not found | {html.escape(biz['name'])}</title></head><body><h1>Page not found</h1></body></html>"


app = create_app()
