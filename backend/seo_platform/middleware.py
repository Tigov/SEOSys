"""Response hardening and request logging.

Every response gets security headers; every request gets an id (echoed in X-Request-ID and on every log line) and
one structured log line. Cookies, tokens and request bodies are never logged.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from contextvars import ContextVar
from typing import Any, Awaitable, Callable

from fastapi import Request, Response

from .config import settings

request_id: ContextVar[str] = ContextVar("request_id", default="-")

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; "
       "object-src 'none'")
HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {"at": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"), "level": record.levelname.lower(),
                                 "logger": record.name, "message": record.getMessage(), "request_id": request_id.get()}
        entry.update(getattr(record, "fields", {}))
        if record.exc_info:
            entry["error"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("seo_platform")
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    root.propagate = False


access_log = logging.getLogger("seo_platform.http")


async def harden(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    rid = request.headers.get("x-request-id", "")
    rid = rid if rid and len(rid) <= 64 and rid.replace("-", "").isalnum() else uuid.uuid4().hex
    token = request_id.set(rid)
    started = time.perf_counter()
    try:
        response = await call_next(request)
        for name, value in HEADERS.items():
            response.headers.setdefault(name, value)
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        path = request.url.path
        if path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        elif path.startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"  # names change with content
        else:
            response.headers["Cache-Control"] = "no-cache"  # the page itself, so a new build is picked up at once
        response.headers["X-Request-ID"] = rid
        access_log.info("request", extra={"fields": {
            "method": request.method, "path": path, "status": response.status_code,
            "ms": round((time.perf_counter() - started) * 1000, 1)}})
        return response
    finally:
        request_id.reset(token)
