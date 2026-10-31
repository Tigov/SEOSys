"""Google connector (TDD section 4): OAuth sign-in, Search Console, GA4 and PageSpeed Insights.

The client signs in with their own Google account and grants read-only scopes; no passwords
(FR-4.2). Tokens stay server-side in the `connections` table and are never returned by the API.
Production envelope-encrypts them (TDD section 10); the PoC keeps them in the local SQLite file,
which lives outside OneDrive. PageSpeed Insights uses the agency's API key, not the client's account.
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import logging
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlencode, urlparse

import httpx

from ..config import settings
from ..db import ClientRepo, Database, now
from ..net import make_client

log = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GSC_API = "https://www.googleapis.com/webmasters/v3"
GA4_ADMIN_API = "https://analyticsadmin.googleapis.com/v1beta"
GA4_DATA_API = "https://analyticsdata.googleapis.com/v1beta"
PSI_API = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

SCOPES = ("openid", "email",
          "https://www.googleapis.com/auth/webmasters.readonly",
          "https://www.googleapis.com/auth/analytics.readonly")
STATE_TTL_SECONDS = 600
REFRESH_MARGIN = timedelta(seconds=60)
TOP_ROWS = 25


class GoogleError(Exception):
    """A problem the portal can show as is. `status` is the HTTP status the API returns."""

    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


def _require_oauth_config() -> None:
    missing = [name for name, value in (("GOOGLE_OAUTH_CLIENT_ID", settings.google_client_id),
                                        ("GOOGLE_OAUTH_CLIENT_SECRET", settings.google_client_secret)) if not value]
    if missing:
        raise GoogleError(f"Google sign-in is not set up on this server. Add {' and '.join(missing)} to the .env file "
                          "and restart.", 503)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _google_message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return f"HTTP {resp.status_code}"
    err = body.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or f"HTTP {resp.status_code}")
    return str(body.get("error_description") or err or f"HTTP {resp.status_code}")


async def _send(method: str, url: str, *, timeout: float = 30, **kwargs: Any) -> httpx.Response:
    try:
        async with make_client(timeout=timeout) as client:
            return await client.request(method, url, **kwargs)
    except httpx.HTTPError as exc:
        # The exception text can contain the request URL (and the PageSpeed key), so it is not shown.
        log.warning("Google request failed: %s", type(exc).__name__)
        raise GoogleError("Google could not be reached. Check the internet connection and try again.") from exc


# ---------- connect flow ----------

def start_connect(db: Database, client_id: int, actor: str) -> str:
    """Create a one-time sign-in handshake and return the Google consent page URL."""
    _require_oauth_config()
    db.for_client(client_id)  # 404 for an unknown client
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    db.save_oauth_state(state=state, client_id=client_id, provider="google", actor=actor, code_verifier=verifier)
    params = {
        "client_id": settings.google_client_id, "redirect_uri": settings.google_redirect_uri,
        "response_type": "code", "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent",
        "include_granted_scopes": "true", "state": state,
        "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _email_from_id_token(id_token: str | None) -> str:
    # The ID token comes straight from Google's token endpoint over TLS, so its payload is read without
    # checking the signature (Google's guidance for tokens received this way).
    if not id_token or id_token.count(".") != 2:
        return ""
    payload = id_token.split(".")[1]
    try:
        return str(json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get("email", ""))
    except ValueError:
        return ""


def _expiry(tokens: dict[str, Any]) -> str:
    seconds = int(tokens.get("expires_in", 3600))
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


async def _token_request(form: dict[str, str]) -> httpx.Response:
    return await _send("POST", TOKEN_URL, data={"client_id": settings.google_client_id,
                                                "client_secret": settings.google_client_secret, **form})


def _connection(repo: ClientRepo) -> dict[str, Any] | None:
    rows = repo.list("connections", "provider = 'google'")
    return rows[0] if rows else None


async def finish_connect(db: Database, state: str, code: str | None, error: str | None) -> tuple[int, str]:
    """Handle Google's redirect back. Returns (client_id, outcome) where outcome is connected, declined or failed."""
    pending = db.take_oauth_state(state, STATE_TTL_SECONDS) if state else None
    if pending is None:
        raise GoogleError("This Google sign-in link has expired or was already used. Start again from the portal.", 400)
    client_id, actor = int(pending["client_id"]), pending["actor"]
    repo = db.for_client(client_id)
    if error or not code:
        repo.log(actor, "google.declined", f"client:{client_id}", {"reason": error or "no code"})
        return client_id, "declined"
    resp = await _token_request({"grant_type": "authorization_code", "code": code,
                                 "code_verifier": pending["code_verifier"], "redirect_uri": settings.google_redirect_uri})
    if resp.status_code != 200:
        repo.log(actor, "google.connect_failed", f"client:{client_id}", {"reason": _google_message(resp)})
        return client_id, "failed"
    tokens = resp.json()
    values = {"status": "connected", "account_email": _email_from_id_token(tokens.get("id_token")),
              "scopes": str(tokens.get("scope", "")).split(), "access_token": tokens["access_token"],
              "expires_at": _expiry(tokens), "updated_at": now()}
    existing = _connection(repo)
    refresh = tokens.get("refresh_token") or (existing or {}).get("refresh_token")
    if existing:
        repo.update("connections", existing["id"], **values, refresh_token=refresh)
    else:
        repo.insert("connections", {"provider": "google", **values, "refresh_token": refresh, "created_at": now()})
    repo.log(actor, "google.connected", f"client:{client_id}",
             {"account": values["account_email"], "scopes": values["scopes"]})
    return client_id, "connected"


def status(repo: ClientRepo) -> dict[str, Any]:
    """Connection state safe to show anyone who can see the client. Tokens are never included."""
    conn = _connection(repo) or {}
    return {"provider": "google", "status": conn.get("status") or "not_connected",
            "account_email": conn.get("account_email") or None, "scopes": conn.get("scopes") or [],
            "gsc_site": conn.get("gsc_site"), "ga4_property": conn.get("ga4_property"),
            "connected_at": conn.get("created_at"), "updated_at": conn.get("updated_at"),
            "oauth_configured": bool(settings.google_client_id and settings.google_client_secret),
            "pagespeed_configured": bool(settings.pagespeed_api_key)}


async def disconnect(repo: ClientRepo, actor: str) -> dict[str, Any]:
    conn = _connection(repo)
    if conn and conn.get("refresh_token"):
        resp = await _send("POST", REVOKE_URL, data={"token": conn["refresh_token"]})
        if resp.status_code != 200:
            log.warning("Google revoke returned %s; forgetting the tokens anyway", resp.status_code)
    if conn:
        repo.update("connections", conn["id"], status="not_connected", access_token=None, refresh_token=None,
                    expires_at=None, updated_at=now())
        repo.log(actor, "google.disconnected", f"client:{repo.client_id}")
    return status(repo)


# ---------- authorised calls ----------

class GoogleSession:
    """Calls Google as the client's connected account, refreshing the access token when it runs out."""

    def __init__(self, repo: ClientRepo) -> None:
        conn = _connection(repo)
        if conn is None or conn["status"] == "not_connected":
            raise GoogleError("Google is not connected for this client yet. Use Connect Google first.", 409)
        if conn["status"] == "expired":
            raise GoogleError("The Google connection has expired. Ask the owner to reconnect Google.", 409)
        self.repo, self.conn = repo, conn

    async def _refresh(self) -> str:
        resp = await _token_request({"grant_type": "refresh_token", "refresh_token": self.conn["refresh_token"] or ""})
        if resp.status_code != 200:
            reason = _google_message(resp)
            self.repo.update("connections", self.conn["id"], status="expired", access_token=None, updated_at=now())
            self.repo.alert("warning", "Google access stopped working, so Search Console and Analytics data can't be "
                                       "read. Ask the owner to reconnect Google.")
            self.repo.log("system", "google.expired", f"client:{self.repo.client_id}", {"reason": reason})
            raise GoogleError("The Google connection has expired. Ask the owner to reconnect Google.", 409)
        tokens = resp.json()
        self.conn.update(access_token=tokens["access_token"], expires_at=_expiry(tokens))
        self.repo.update("connections", self.conn["id"], access_token=tokens["access_token"],
                         expires_at=self.conn["expires_at"], updated_at=now())
        return tokens["access_token"]

    async def _token(self) -> str:
        expires = self.conn.get("expires_at")
        if not self.conn.get("access_token") or not expires or \
                datetime.fromisoformat(expires) - REFRESH_MARGIN <= datetime.now(timezone.utc):
            return await self._refresh()
        return self.conn["access_token"]

    async def call(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        token = await self._token()
        resp = await _send(method, url, headers={"Authorization": f"Bearer {token}"}, **kwargs)
        if resp.status_code == 401:  # revoked early or clock skew: refresh once and retry
            resp = await _send(method, url, headers={"Authorization": f"Bearer {await self._refresh()}"}, **kwargs)
        if resp.status_code >= 400:
            raise GoogleError(f"Google returned an error: {_google_message(resp)}")
        return resp.json() if resp.content else {}


# ---------- choosing what to read ----------

async def list_properties(repo: ClientRepo) -> dict[str, Any]:
    session = GoogleSession(repo)
    sites = (await session.call("GET", f"{GSC_API}/sites")).get("siteEntry", [])
    out: dict[str, Any] = {
        "gsc_sites": [{"site_url": s["siteUrl"], "permission": s.get("permissionLevel", ""),
                       "verified": s.get("permissionLevel") != "siteUnverifiedUser"} for s in sites],
        "ga4_properties": [], "ga4_error": None,
    }
    try:
        accounts = (await session.call("GET", f"{GA4_ADMIN_API}/accountSummaries", params={"pageSize": 200}))
        out["ga4_properties"] = [{"property": p["property"], "name": p.get("displayName", ""), "account": a.get("displayName", "")}
                                 for a in accounts.get("accountSummaries", []) for p in a.get("propertySummaries", [])]
    except GoogleError as exc:
        # Most often the Google Analytics Admin API isn't turned on in the Cloud project.
        out["ga4_error"] = str(exc)
    return out


async def select(repo: ClientRepo, actor: str, gsc_site: str | None, ga4_property: str | None) -> dict[str, Any]:
    conn = GoogleSession(repo).conn
    props = await list_properties(repo)
    changes: dict[str, Any] = {}
    if gsc_site is not None:
        readable = {s["site_url"] for s in props["gsc_sites"] if s["verified"]}
        if gsc_site and gsc_site not in readable:
            raise GoogleError("This Google account can't read that Search Console property. Pick one from the list.", 400)
        changes["gsc_site"] = gsc_site or None
    if ga4_property is not None:
        known = {p["property"] for p in props["ga4_properties"]}
        allowed = ga4_property in known if known or not props["ga4_error"] else bool(re.fullmatch(r"properties/\d+", ga4_property))
        if ga4_property and not allowed:
            raise GoogleError("This Google account can't read that Analytics property. Pick one from the list.", 400)
        changes["ga4_property"] = ga4_property or None
    if changes:
        repo.update("connections", conn["id"], **changes, updated_at=now())
        repo.log(actor, "google.properties_selected", f"client:{repo.client_id}", changes)
    return status(repo)


# ---------- reports ----------

def _window(days: int) -> tuple[str, str]:
    end = date.today() - timedelta(days=2)  # Search Console data lags by about two days
    return (end - timedelta(days=days - 1)).isoformat(), end.isoformat()


def _gsc_row(row: dict[str, Any]) -> dict[str, Any]:
    out = {"clicks": int(row.get("clicks", 0)), "impressions": int(row.get("impressions", 0)),
           "ctr": round(float(row.get("ctr", 0)), 4), "position": round(float(row.get("position", 0)), 1)}
    return {"key": row["keys"][0], **out} if row.get("keys") else out


async def search_console_report(repo: ClientRepo, days: int = 28) -> dict[str, Any]:
    session = GoogleSession(repo)
    site = session.conn.get("gsc_site")
    if not site:
        raise GoogleError("Choose which Search Console property to read first.", 409)
    start, end = _window(days)
    url = f"{GSC_API}/sites/{quote(site, safe='')}/searchAnalytics/query"

    async def query(dimensions: list[str]) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"startDate": start, "endDate": end, "rowLimit": TOP_ROWS}
        if dimensions:
            body["dimensions"] = dimensions
        return [_gsc_row(r) for r in (await session.call("POST", url, json=body)).get("rows", [])]

    totals, queries, pages = await query([]), await query(["query"]), await query(["page"])
    repo.meter("google_search_console", "query", 3, 0.0)
    striking = sorted((q for q in queries if 5 <= q["position"] <= 20), key=lambda q: -q["impressions"])
    return {"source": "Google Search Console", "site": site, "start": start, "end": end,
            "totals": totals[0] if totals else {"clicks": 0, "impressions": 0, "ctr": 0.0, "position": 0.0},
            "queries": queries, "pages": pages, "striking_distance": striking}


GA4_METRICS = (("sessions", "sessions"), ("totalUsers", "users"), ("keyEvents", "key_events"))


def _ga4_values(row: dict[str, Any]) -> dict[str, int]:
    vals = row.get("metricValues", [])
    return {label: int(float(vals[i]["value"])) if i < len(vals) else 0 for i, (_, label) in enumerate(GA4_METRICS)}


async def analytics_report(repo: ClientRepo, days: int = 28) -> dict[str, Any]:
    session = GoogleSession(repo)
    prop = session.conn.get("ga4_property")
    if not prop:
        raise GoogleError("Choose which Google Analytics property to read first.", 409)
    end = date.today() - timedelta(days=1)
    span = {"dateRanges": [{"startDate": (end - timedelta(days=days - 1)).isoformat(), "endDate": end.isoformat()}],
            "metrics": [{"name": name} for name, _ in GA4_METRICS]}
    url = f"{GA4_DATA_API}/{prop}:runReport"
    totals = (await session.call("POST", url, json=span)).get("rows", [])
    pages = (await session.call("POST", url, json={**span, "dimensions": [{"name": "landingPage"}], "limit": TOP_ROWS,
                                                   "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}]})).get("rows", [])
    repo.meter("google_analytics", "report", 2, 0.0)
    return {"source": "Google Analytics 4", "property": prop, "start": span["dateRanges"][0]["startDate"], "end": end.isoformat(),
            "totals": _ga4_values(totals[0]) if totals else {label: 0 for _, label in GA4_METRICS},
            "landing_pages": [{"page": r["dimensionValues"][0]["value"], **_ga4_values(r)} for r in pages]}


# ---------- PageSpeed Insights (agency API key) ----------

FIELD_METRICS = (("LARGEST_CONTENTFUL_PAINT_MS", "lcp_ms", 1), ("INTERACTION_TO_NEXT_PAINT", "inp_ms", 1),
                 ("CUMULATIVE_LAYOUT_SHIFT_SCORE", "cls", 100))


def _is_public_web_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not host or host == "localhost" or host.endswith(".localhost"):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "." in host
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved)


async def pagespeed(repo: ClientRepo, url: str | None, strategy: str = "mobile") -> dict[str, Any]:
    if not settings.pagespeed_api_key:
        raise GoogleError("PageSpeed Insights is not set up on this server. Add GOOGLE_PAGESPEED_API_KEY to the .env file "
                          "and restart.", 503)
    target = url or repo.site()["base_url"]
    if not _is_public_web_url(target):
        raise GoogleError(f"PageSpeed Insights runs on Google's servers, so it can only test a public website. "
                          f"{target} is not a public address.", 400)
    resp = await _send("GET", PSI_API, timeout=120, params={"url": target, "strategy": strategy, "category": "performance",
                                                            "key": settings.pagespeed_api_key})
    if resp.status_code != 200:
        raise GoogleError(f"PageSpeed Insights could not test {target}: {_google_message(resp)}")
    data = resp.json()
    repo.meter("google_pagespeed", "test", 1, 0.0)
    # Real-visitor data is for this page when Google has enough of it, otherwise for the whole website.
    experience = data.get("loadingExperience", {})
    if not experience.get("metrics") and data.get("originLoadingExperience", {}).get("metrics"):
        experience = {**data["originLoadingExperience"], "origin_fallback": True}
    field_raw = experience.get("metrics", {})
    field_scope = None if not field_raw else "website" if experience.get("origin_fallback") else "page"
    field = {label: {"value": round(m["percentile"] / div, 3) if div != 1 else int(m["percentile"]),
                     "rating": str(m.get("category", "")).lower()}
             for key, label, div in FIELD_METRICS if (m := field_raw.get(key))}
    audits = data.get("lighthouseResult", {}).get("audits", {})

    def lab(key: str, digits: int) -> float | int | None:
        val = audits.get(key, {}).get("numericValue")
        return None if val is None else (round(val) if digits == 0 else round(val, digits))

    score = data.get("lighthouseResult", {}).get("categories", {}).get("performance", {}).get("score")
    return {"source": "PageSpeed Insights", "url": target, "strategy": strategy,
            "performance_score": None if score is None else round(score * 100),
            "field": field, "field_scope": field_scope,
            "field_overall": str(experience.get("overall_category", "")).lower() or None,
            "lab": {"lcp_ms": lab("largest-contentful-paint", 0), "cls": lab("cumulative-layout-shift", 3),
                    "tbt_ms": lab("total-blocking-time", 0)},
            "tested_at": now()}
