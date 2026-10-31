"""Google connector: OAuth connect flow, Search Console, GA4 and PageSpeed Insights.

Google is replaced by `FakeGoogle`, an in-process stand-in for its HTTP APIs, so these
tests never hit the network. The live check against real Google is run by hand
(see notes: End-to-End Test Plan).
"""
import json
from dataclasses import replace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from seo_platform import net
from seo_platform.adapters import google

from .conftest import CLIENT, STAFF

SITE = "https://www.lonestarcomfort.example/"


class FakeGoogle:
    """Answers the Google endpoints the connector uses and records every request."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.token_calls = 0
        self.refresh_fails = False
        self.access_token = "access-1"
        self.psi = _psi_body  # tests swap this to shape the PageSpeed answer

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host, path = request.url.host, request.url.path
        if host == "oauth2.googleapis.com" and path == "/token":
            form = parse_qs(request.content.decode())
            self.token_calls += 1
            if form["grant_type"] == ["refresh_token"]:
                if self.refresh_fails:
                    return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
                self.access_token = f"access-{self.token_calls}"
                return httpx.Response(200, json={"access_token": self.access_token, "expires_in": 3599, "token_type": "Bearer"})
            if form["code"] != ["good-code"] or not form["code_verifier"][0]:
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Bad Request"})
            return httpx.Response(200, json={
                "access_token": self.access_token, "refresh_token": "refresh-1", "expires_in": 3599,
                "scope": " ".join(google.SCOPES), "token_type": "Bearer", "id_token": _id_token("owner@lonestar.example")})
        if host == "oauth2.googleapis.com" and path == "/revoke":
            return httpx.Response(200)
        if request.headers.get("Authorization", "").startswith("Bearer") and request.headers["Authorization"] != f"Bearer {self.access_token}":
            return httpx.Response(401, json={"error": {"code": 401, "message": "Invalid credentials"}})
        if host == "www.googleapis.com" and path == "/webmasters/v3/sites":
            return httpx.Response(200, json={"siteEntry": [
                {"siteUrl": SITE, "permissionLevel": "siteFullUser"},
                {"siteUrl": "sc-domain:other.example", "permissionLevel": "siteUnverifiedUser"}]})
        if host == "www.googleapis.com" and path.endswith("/searchAnalytics/query"):
            body = json.loads(request.content)
            if body.get("dimensions") == ["query"]:
                rows = [{"keys": ["ac repair austin"], "clicks": 40, "impressions": 900, "ctr": 0.0444, "position": 6.2},
                        {"keys": ["furnace repair"], "clicks": 10, "impressions": 600, "ctr": 0.0167, "position": 11.8}]
            elif body.get("dimensions") == ["page"]:
                rows = [{"keys": [SITE + "ac-repair"], "clicks": 45, "impressions": 1200, "ctr": 0.0375, "position": 7.1}]
            else:
                rows = [{"clicks": 50, "impressions": 1500, "ctr": 0.0333, "position": 8.4}]
            return httpx.Response(200, json={"rows": rows})
        if host == "analyticsadmin.googleapis.com" and path == "/v1beta/accountSummaries":
            return httpx.Response(200, json={"accountSummaries": [{"displayName": "Lone Star", "propertySummaries": [
                {"property": "properties/123456789", "displayName": "lonestarcomfort.example"}]}]})
        if host == "analyticsdata.googleapis.com" and path == "/v1beta/properties/123456789:runReport":
            body = json.loads(request.content)
            if body.get("dimensions"):
                return httpx.Response(200, json={"rows": [
                    {"dimensionValues": [{"value": "/ac-repair"}], "metricValues": [{"value": "320"}, {"value": "250"}, {"value": "12"}]}]})
            return httpx.Response(200, json={"rows": [
                {"metricValues": [{"value": "1000"}, {"value": "800"}, {"value": "30"}]}]})
        if host == "www.googleapis.com" and path == "/pagespeedonline/v5/runPagespeed":
            return httpx.Response(200, json=self.psi(request.url.params["url"]))
        return httpx.Response(404, json={"error": {"code": 404, "message": f"no fake for {host}{path}"}})


def _id_token(email: str) -> str:
    import base64
    payload = base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


def _psi_body(url: str) -> dict:
    return {
        "id": url,
        "loadingExperience": {"overall_category": "AVERAGE", "metrics": {
            "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 2900, "category": "AVERAGE"},
            "INTERACTION_TO_NEXT_PAINT": {"percentile": 180, "category": "FAST"},
            "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 5, "category": "FAST"}}},
        "lighthouseResult": {"categories": {"performance": {"score": 0.72}}, "audits": {
            "largest-contentful-paint": {"numericValue": 3100.5},
            "cumulative-layout-shift": {"numericValue": 0.04},
            "total-blocking-time": {"numericValue": 210.0}}},
    }


class Router(httpx.AsyncBaseTransport):
    """Sends Google hosts to FakeGoogle and everything else to the demo site."""

    def __init__(self, fake: FakeGoogle, other: httpx.AsyncBaseTransport) -> None:
        self.fake, self.other = fake, other

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.host.endswith("googleapis.com"):
            return self.fake.handle(request)
        return await self.other.handle_async_request(request)


@pytest.fixture()
def fake(demo):
    fake = FakeGoogle()
    original = net.transport_factory
    net.transport_factory = lambda: Router(fake, httpx.ASGITransport(app=demo))
    yield fake
    net.transport_factory = original


def start_connect(api, headers=CLIENT):
    r = api.post("/api/clients/1/connections/google/start", headers=headers)
    assert r.status_code == 200, r.text
    return parse_qs(urlparse(r.json()["auth_url"]).query)


def connect(api):
    q = start_connect(api)
    r = api.get(f"/api/oauth/google/callback?code=good-code&state={q['state'][0]}", follow_redirects=False)
    assert r.status_code == 303, r.text
    return r


def connected(api, fake, gsc=True, ga4=True):
    connect(api)
    body = {}
    if gsc:
        body["gsc_site"] = SITE
    if ga4:
        body["ga4_property"] = "properties/123456789"
    r = api.patch("/api/clients/1/connections/google", json=body, headers=STAFF)
    assert r.status_code == 200, r.text
    return r.json()


# ---------- connect flow ----------

def test_start_builds_google_consent_url(api, fake):
    q = start_connect(api)
    assert q["client_id"] == ["test-client.apps.googleusercontent.com"]
    assert q["redirect_uri"] == ["http://localhost:8000/api/oauth/google/callback"]
    assert q["response_type"] == ["code"] and q["access_type"] == ["offline"]
    assert "https://www.googleapis.com/auth/webmasters.readonly" in q["scope"][0].split()
    assert "https://www.googleapis.com/auth/analytics.readonly" in q["scope"][0].split()
    assert q["code_challenge_method"] == ["S256"] and q["code_challenge"][0] and q["state"][0]


def test_start_needs_a_signed_in_role(api, fake):
    assert api.post("/api/clients/1/connections/google/start").status_code == 401


def test_callback_stores_connection_and_never_returns_tokens(api, fake):
    r = connect(api)
    assert r.headers["location"] == "/?google=connected#/clients/1/google"
    status = api.get("/api/clients/1/connections/google", headers=CLIENT).json()
    assert status["status"] == "connected" and status["account_email"] == "owner@lonestar.example"
    for body in (json.dumps(status), api.get("/api/clients/1/export", headers=STAFF).text,
                 api.get("/api/clients/1/audit-log", headers=STAFF).text):
        assert "refresh-1" not in body and "access-1" not in body
    actions = [e["action"] for e in api.get("/api/clients/1/audit-log", headers=STAFF).json()]
    assert "google.connected" in actions


def test_callback_rejects_unknown_or_reused_state(api, fake):
    q = start_connect(api)
    assert api.get("/api/oauth/google/callback?code=good-code&state=forged", follow_redirects=False).status_code == 400
    assert api.get(f"/api/oauth/google/callback?code=good-code&state={q['state'][0]}", follow_redirects=False).status_code == 303
    assert api.get(f"/api/oauth/google/callback?code=good-code&state={q['state'][0]}", follow_redirects=False).status_code == 400
    assert fake.token_calls == 1


def test_callback_when_owner_declines(api, fake):
    q = start_connect(api)
    r = api.get(f"/api/oauth/google/callback?error=access_denied&state={q['state'][0]}", follow_redirects=False)
    assert r.headers["location"] == "/?google=declined#/clients/1/google"
    assert api.get("/api/clients/1/connections/google", headers=CLIENT).json()["status"] == "not_connected"
    assert fake.token_calls == 0


def test_callback_when_google_rejects_the_code(api, fake):
    q = start_connect(api)
    r = api.get(f"/api/oauth/google/callback?code=bad-code&state={q['state'][0]}", follow_redirects=False)
    assert r.headers["location"] == "/?google=failed#/clients/1/google"
    assert api.get("/api/clients/1/connections/google", headers=CLIENT).json()["status"] == "not_connected"


def test_start_explains_missing_setup(api, fake, monkeypatch):
    monkeypatch.setattr(google, "settings", replace(google.settings, google_client_id=""))
    r = api.post("/api/clients/1/connections/google/start", headers=CLIENT)
    assert r.status_code == 503 and "GOOGLE_OAUTH_CLIENT_ID" in r.json()["detail"]


# ---------- choosing what to read ----------

def test_lists_search_console_sites_and_ga4_properties(api, fake):
    connect(api)
    props = api.get("/api/clients/1/connections/google/properties", headers=STAFF).json()
    assert [s["site_url"] for s in props["gsc_sites"]] == [SITE, "sc-domain:other.example"]
    assert props["gsc_sites"][1]["verified"] is False
    assert props["ga4_properties"] == [{"property": "properties/123456789", "name": "lonestarcomfort.example", "account": "Lone Star"}]


def test_selecting_a_site_the_account_cannot_read_is_refused(api, fake):
    connect(api)
    r = api.patch("/api/clients/1/connections/google", json={"gsc_site": "https://not-theirs.example/"}, headers=STAFF)
    assert r.status_code == 400
    r = api.patch("/api/clients/1/connections/google", json={"ga4_property": "properties/999"}, headers=STAFF)
    assert r.status_code == 400


# ---------- reading data ----------

def test_search_console_report(api, fake):
    connected(api, fake)
    r = api.get("/api/clients/1/google/search-console?days=28", headers=CLIENT)
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["site"] == SITE and rep["totals"]["clicks"] == 50 and rep["totals"]["impressions"] == 1500
    assert rep["queries"][0] == {"key": "ac repair austin", "clicks": 40, "impressions": 900, "ctr": 0.0444, "position": 6.2}
    assert rep["pages"][0]["key"] == SITE + "ac-repair"
    # queries in positions 5-20 are the "striking distance" list (FDD FR-5.3)
    assert [q["key"] for q in rep["striking_distance"]] == ["ac repair austin", "furnace repair"]
    sent = [q for q in fake.requests if q.url.path.endswith("/searchAnalytics/query")]
    assert sent and all(q.headers["Authorization"] == "Bearer access-1" for q in sent)
    assert "https%3A%2F%2Fwww.lonestarcomfort.example%2F" in str(sent[0].url)
    usage = api.get("/api/ops/usage", headers=STAFF).json()
    assert any(u["vendor"] == "google_search_console" for u in usage)


def test_report_without_a_selected_site_explains_next_step(api, fake):
    connect(api)
    r = api.get("/api/clients/1/google/search-console", headers=CLIENT)
    assert r.status_code == 409 and "Search Console" in r.json()["detail"]


def test_report_when_not_connected(api, fake):
    r = api.get("/api/clients/1/google/search-console", headers=CLIENT)
    assert r.status_code == 409 and "Connect Google" in r.json()["detail"]


def test_analytics_report(api, fake):
    connected(api, fake)
    rep = api.get("/api/clients/1/google/analytics?days=28", headers=CLIENT).json()
    assert rep["property"] == "properties/123456789"
    assert rep["totals"] == {"sessions": 1000, "users": 800, "key_events": 30}
    assert rep["landing_pages"] == [{"page": "/ac-repair", "sessions": 320, "users": 250, "key_events": 12}]


def test_expired_access_token_is_refreshed_and_saved(api, fake):
    connected(api, fake)
    db = api.app.state.db
    db.execute("UPDATE connections SET expires_at = '2000-01-01T00:00:00+00:00'")
    fake.access_token = "access-new"
    assert api.get("/api/clients/1/google/search-console", headers=CLIENT).status_code == 200
    row = db.one("SELECT access_token, expires_at FROM connections")
    assert row["access_token"].startswith("access-") and row["expires_at"] > "2001"
    assert fake.token_calls == 2


def test_revoked_refresh_token_marks_connection_expired(api, fake):
    connected(api, fake)
    api.app.state.db.execute("UPDATE connections SET expires_at = '2000-01-01T00:00:00+00:00'")
    fake.refresh_fails = True
    r = api.get("/api/clients/1/google/search-console", headers=CLIENT)
    assert r.status_code == 409 and "reconnect" in r.json()["detail"].lower()
    assert api.get("/api/clients/1/connections/google", headers=CLIENT).json()["status"] == "expired"
    alerts = api.get("/api/clients/1", headers=STAFF).json()["alerts"]
    assert any("Google" in a["message"] for a in alerts)


def test_disconnect_revokes_at_google_and_forgets_tokens(api, fake):
    connected(api, fake)
    assert api.delete("/api/clients/1/connections/google", headers=CLIENT).status_code == 200
    assert any(q.url.path == "/revoke" for q in fake.requests)
    assert api.get("/api/clients/1/connections/google", headers=CLIENT).json()["status"] == "not_connected"
    assert api.app.state.db.one("SELECT COUNT(*) AS n FROM connections WHERE refresh_token IS NOT NULL")["n"] == 0


def test_connection_is_scoped_to_its_client(api, fake):
    connected(api, fake)
    api.post("/api/clients", json={"name": "Second Co", "site_url": "https://second.example"}, headers=STAFF)
    assert api.get("/api/clients/2/connections/google", headers=STAFF).json()["status"] == "not_connected"
    assert api.get("/api/clients/2/google/search-console", headers=STAFF).status_code == 409


# ---------- PageSpeed Insights ----------

def test_pagespeed_for_a_public_url(api, fake):
    r = api.post("/api/clients/1/google/pagespeed", json={"url": "https://example.com/", "strategy": "mobile"}, headers=STAFF)
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["url"] == "https://example.com/" and rep["performance_score"] == 72
    assert rep["field"]["lcp_ms"] == {"value": 2900, "rating": "average"}
    assert rep["field"]["cls"] == {"value": 0.05, "rating": "fast"}
    assert rep["lab"] == {"lcp_ms": 3100, "cls": 0.04, "tbt_ms": 210}
    sent = next(q for q in fake.requests if q.url.path.endswith("runPagespeed"))
    assert sent.url.params["key"] == "test-psi-key" and sent.url.params["strategy"] == "mobile"
    assert any(u["vendor"] == "google_pagespeed" for u in api.get("/api/ops/usage", headers=STAFF).json())


def test_pagespeed_says_whether_visitor_data_is_for_the_page_or_whole_site(api, fake):
    rep = api.post("/api/clients/1/google/pagespeed", json={"url": "https://example.com/"}, headers=STAFF).json()
    assert rep["field_scope"] == "page"

    def fallback(url):  # Google's shape when the page has too few visits: the origin's data, flagged
        body = _psi_body(url)
        body["loadingExperience"]["origin_fallback"] = True
        return body

    fake.psi = fallback
    rep = api.post("/api/clients/1/google/pagespeed", json={"url": "https://example.com/quiet-page"}, headers=STAFF).json()
    assert rep["field_scope"] == "website" and rep["field"]["lcp_ms"]["value"] == 2900


def test_pagespeed_with_no_visitor_data_at_all(api, fake):
    def none(url):
        body = _psi_body(url)
        body["loadingExperience"] = {"id": url}
        return body

    fake.psi = none
    rep = api.post("/api/clients/1/google/pagespeed", json={"url": "https://example.com/new"}, headers=STAFF).json()
    assert rep["field"] == {} and rep["field_scope"] is None and rep["performance_score"] == 72


def test_pagespeed_defaults_to_the_client_site_and_explains_localhost(api, fake):
    r = api.post("/api/clients/1/google/pagespeed", json={}, headers=STAFF)
    assert r.status_code == 400 and "public" in r.json()["detail"]


def test_pagespeed_is_staff_only(api, fake):
    assert api.post("/api/clients/1/google/pagespeed", json={"url": "https://example.com/"}, headers=CLIENT).status_code == 403


def test_pagespeed_without_key_explains_setup(api, fake, monkeypatch):
    monkeypatch.setattr(google, "settings", replace(google.settings, pagespeed_api_key=""))
    r = api.post("/api/clients/1/google/pagespeed", json={"url": "https://example.com/"}, headers=STAFF)
    assert r.status_code == 503 and "GOOGLE_PAGESPEED_API_KEY" in r.json()["detail"]
