"""HTTP API and portal (run: uvicorn seo_platform.api:app --port 8000 from the backend folder).

Every route declares what it needs with `require("<action>")` (see permissions.py). People sign in with a
session cookie; every request that changes something also sends the session's CSRF token in X-CSRF-Token.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

from . import changes as change_svc
from . import billing, maintenance, mailer, services, team, visibility
from .adapters import google
from .adapters.llm import get_writer
from .adapters.site_wp import AdapterError, WordPressAdapter
from .auth import google_signin, sessions, tokens
from .auth import routes as auth_routes
from .auth.service import AuthError
from .config import settings
from .db import ClientRepo, Database, now
from .fixes import propose_for_finding
from .net import BlockedHostError, make_client
from .permissions import ACTIONS, CHANGE_ACTIONS, STATUS_ALLOWS, Access, require
from .plans import PLANS

log = logging.getLogger("seo_platform")
STATIC_DIR = Path(__file__).with_name("static")
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_EXEMPT = {"/api/billing/webhook"}

DEMO_CLIENT = {
    "name": "Lone Star Comfort HVAC", "city": "Austin", "region": "TX", "phone": "(512) 555-0142",
    "street": "4100 Burnet Rd", "postal_code": "78756",
    "services": ["AC repair", "furnace repair", "emergency HVAC repair", "HVAC maintenance"],
    "competitors": ["Capital City Air", "Hill Country Heating & Air", "BlueBonnet Comfort Pros"],
}


class GradeIn(BaseModel):
    url: HttpUrl
    email: str | None = Field(None, max_length=254)
    business_name: str | None = Field(None, max_length=200)
    city: str | None = Field(None, max_length=120)


class ClientIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    city: str = Field("", max_length=120)
    region: str = Field("", max_length=120)
    phone: str = Field("", max_length=40)
    street: str = Field("", max_length=200)
    postal_code: str = Field("", max_length=20)
    services: list[str] = Field([], max_length=50)
    competitors: list[str] = Field([], max_length=50)
    site_url: HttpUrl
    cms: Literal["wordpress", "shopify", "github", "other"] = "wordpress"
    site_secret: str = Field("", max_length=200)


class SettingsIn(BaseModel):
    auto_approve_low: bool | None = None
    freeze_deploys: bool | None = None
    require_mfa: bool | None = None


class BulkIn(BaseModel):
    action: Literal["submit", "approve", "deploy"]
    risk: Literal["low", "medium", "high", "any"] = "any"


class FaultIn(BaseModel):
    on: bool


class GoogleSelectIn(BaseModel):
    gsc_site: str | None = Field(None, max_length=500)
    ga4_property: str | None = Field(None, max_length=100)


class InviteIn(BaseModel):
    email: str = Field(max_length=254)
    can_approve: bool = False


class MemberIn(BaseModel):
    can_approve: bool


class TransferIn(BaseModel):
    user_id: int


class CheckoutIn(BaseModel):
    plan: str = Field(max_length=40)
    business_name: str = Field(max_length=200)


class PageSpeedIn(BaseModel):
    url: HttpUrl | None = None
    strategy: Literal["mobile", "desktop"] = "mobile"


def seed_demo(db: Database) -> None:
    if db.list_clients():
        return
    cid = db.create_client(**DEMO_CLIENT, monthly_budget_usd=settings.default_monthly_budget_usd)
    db.insert("sites", {"client_id": cid, "base_url": settings.demo_site_url, "cms": "wordpress",
                        "adapter_secret": settings.demo_site_secret, "created_at": now()})
    db.log(cid, "system", "client.created", f"client:{cid}", {"seed": True})


async def _send_mail_forever(database: Database) -> None:
    """Drain the email outbox every few seconds. Failures are logged and retried by the outbox itself."""
    while True:
        try:
            await asyncio.to_thread(mailer.send_pending, database)
        except Exception:  # keep the loop alive; the row records what went wrong
            log.exception("sending queued email failed")
        await asyncio.sleep(5)


async def _maintain_forever(database: Database) -> None:
    """Hourly housekeeping (production runs `python -m seo_platform maintenance` on a scheduler instead)."""
    while True:
        try:
            await asyncio.to_thread(maintenance.run, database)
        except Exception:
            log.exception("maintenance failed")
        await asyncio.sleep(3600)


def _set_state_cookie(response: Response, state: str) -> None:
    response.set_cookie(google.STATE_COOKIE, state, max_age=google.STATE_TTL_SECONDS, httponly=True, samesite="lax",
                        path="/api/", secure=settings.is_production or settings.app_base_url.startswith("https://"))


def create_app(db: Database | None = None) -> FastAPI:
    database = db or Database(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if settings.is_test:
            seed_demo(database)  # development seeds through `python -m seo_platform seed --demo` (start.bat)
        tasks = [] if settings.is_test else [asyncio.create_task(_send_mail_forever(database)),
                                             asyncio.create_task(_maintain_forever(database))]
        yield
        for task in tasks:
            task.cancel()

    app = FastAPI(title=settings.app_name, lifespan=lifespan,
                  docs_url=None if settings.is_production else "/docs", redoc_url=None,
                  openapi_url=None if settings.is_production else "/openapi.json")
    app.state.db = database
    app.include_router(auth_routes.router, dependencies=[Depends(require("public"))])

    # ---------- CSRF ----------
    @app.middleware("http")
    async def csrf(request: Request, call_next: Callable[[Request], Awaitable[Any]]) -> Any:
        """Changes need the session's CSRF token; without a session they must at least be JSON, which a
        cross-site form can't send."""
        path = request.url.path
        if request.method in UNSAFE and path.startswith("/api/") and path not in CSRF_EXEMPT:
            principal = await asyncio.to_thread(auth_routes.current_principal, request)
            sent = request.headers.get("x-csrf-token", "")
            if principal is not None and not tokens.same(sent, principal.csrf_token):
                return JSONResponse({"detail": "Your session needs refreshing. Reload the page and try again."}, 403)
            has_body = int(request.headers.get("content-length") or 0) > 0
            if has_body and not request.headers.get("content-type", "").startswith("application/json"):
                return JSONResponse({"detail": "Send JSON."}, 415)
        return await call_next(request)

    # ---------- error mapping ----------
    @app.exception_handler(AuthError)
    async def auth_error(_: Request, exc: AuthError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.exception_handler(billing.BillingError)
    async def billing_error(_: Request, exc: billing.BillingError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.exception_handler(LookupError)
    async def not_found(_: Request, exc: LookupError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(PermissionError)
    async def forbidden(_: Request, exc: PermissionError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=403)

    @app.exception_handler(change_svc.TransitionError)
    async def conflict(_: Request, exc: change_svc.TransitionError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(AdapterError)
    async def bad_gateway(_: Request, exc: AdapterError) -> JSONResponse:
        return JSONResponse({"detail": f"The client's website returned an error: {exc}"}, status_code=502)

    @app.exception_handler(BlockedHostError)
    async def blocked(_: Request, exc: BlockedHostError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(google.GoogleError)
    async def google_error(_: Request, exc: google.GoogleError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    # ---------- helpers ----------
    def repo(a: Access) -> ClientRepo:
        assert a.repo is not None
        return a.repo

    def adapter_for(r: ClientRepo) -> WordPressAdapter:
        site = r.site()
        if site["cms"] != "wordpress":
            raise HTTPException(400, f"Direct changes to {site['cms']} sites aren't supported yet. Recommendations only.")
        return WordPressAdapter(site["base_url"], site["adapter_secret"])

    # ---------- public ----------
    @app.get("/api/health")
    def health(a: Access = Depends(require("public"))) -> dict[str, Any]:
        return {"ok": True}

    @app.get("/api/auth/permissions")
    def permissions_table(a: Access = Depends(require("public"))) -> dict[str, Any]:
        return {"actions": {k: sorted(v) for k, v in ACTIONS.items()}, "change_actions": CHANGE_ACTIONS,
                "status_allows": {k: (sorted(v) if v is not None else None) for k, v in STATUS_ALLOWS.items()}}

    @app.post("/api/grader")
    async def grader(body: GradeIn, a: Access = Depends(require("public"))) -> dict[str, Any]:
        return await services.grade(database, str(body.url).rstrip("/"), body.email, body.business_name, body.city,
                                    user_id=a.user_id)

    # ---------- agency (admin) ----------
    @app.get("/api/leads")
    def leads(a: Access = Depends(require("admin"))) -> list[dict[str, Any]]:
        return database.query("SELECT id, url, email, business_name, city, score, created_at FROM leads ORDER BY id DESC")

    @app.get("/api/clients")
    def list_clients(a: Access = Depends(require("admin"))) -> list[dict[str, Any]]:
        out = []
        for cl in database.list_clients():
            r = ClientRepo(database, cl["id"])
            crawl = r.latest_crawl()
            out.append({**cl, "health_score": crawl["health_score"] if crawl else None,
                        "waiting_on_client": len(r.list("change_requests", "status = 'awaiting_client'"))})
        return out

    @app.post("/api/clients", status_code=201)
    def create_client(body: ClientIn, a: Access = Depends(require("admin"))) -> dict[str, Any]:
        data = body.model_dump()
        site_url, cms, secret = str(data.pop("site_url")).rstrip("/"), data.pop("cms"), data.pop("site_secret")
        with database.transaction():
            cid = database.create_client(**data, monthly_budget_usd=settings.default_monthly_budget_usd)
            r = database.for_client(cid)
            r.insert("sites", {"base_url": site_url, "cms": cms, "adapter_secret": secret or None, "created_at": now()})
            r.log(a.actor, "client.created", f"client:{cid}", actor_user_id=a.user_id)
        return r.client()

    @app.get("/api/ops/usage")
    def usage(a: Access = Depends(require("admin"))) -> list[dict[str, Any]]:
        return database.query("SELECT client_id, vendor, SUM(qty) AS qty, ROUND(SUM(cost_usd), 4) AS cost_usd "
                              "FROM usage_events GROUP BY client_id, vendor ORDER BY client_id, cost_usd DESC")

    # ---------- one client ----------
    @app.get("/api/clients/{client_id}")
    def get_client(client_id: int, a: Access = Depends(require("client.view"))) -> dict[str, Any]:
        return {**services.summary(repo(a)), "my_role": a.role,
                "can": sorted(action for action in ACTIONS if a.can(action))}

    @app.patch("/api/clients/{client_id}/settings")
    def update_settings(client_id: int, body: SettingsIn, a: Access = Depends(require("client.settings"))) -> dict[str, Any]:
        r = repo(a)
        changes = {k: v for k, v in body.model_dump().items() if v is not None}
        if "auto_approve_low" in changes and a.role == "admin":
            raise PermissionError("Only the client can turn on auto-approval of low-risk changes.")
        if changes.get("require_mfa") and a.role != "admin" and not (a.principal and a.principal.totp_enabled):
            raise PermissionError("Turn on two-step login for yourself first, so you don't lock yourself out.")
        if changes:
            r.update_client(**changes)
            r.log(a.actor, "settings.updated", f"client:{client_id}", changes, actor_user_id=a.user_id)
        return r.client()

    @app.post("/api/clients/{client_id}/audits")
    async def run_audit(client_id: int, a: Access = Depends(require("work.run"))) -> dict[str, Any]:
        try:
            return await services.run_audit(repo(a), a.actor)
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"The audit could not reach the website: {exc}")

    @app.get("/api/clients/{client_id}/findings")
    def findings(client_id: int, status: str | None = None, a: Access = Depends(require("client.view"))) -> list[dict[str, Any]]:
        r = repo(a)
        rows = r.list("findings", "status = ?", (status,)) if status else r.list("findings")
        return sorted(rows, key=lambda f: (services.SEVERITY_ORDER.get(f["severity"], 9), -(f["impact"] or 0), f["id"]))

    @app.get("/api/clients/{client_id}/pages")
    def pages(client_id: int, a: Access = Depends(require("client.view"))) -> list[dict[str, Any]]:
        r = repo(a)
        crawl = r.latest_crawl()
        return r.list("pages", "crawl_id = ?", (crawl["id"],)) if crawl else []

    @app.post("/api/clients/{client_id}/findings/{finding_id}/propose")
    async def propose(client_id: int, finding_id: int, a: Access = Depends(require("work.run"))) -> dict[str, Any]:
        r = repo(a)
        finding = r.get("findings", finding_id)
        if finding is None:
            raise LookupError(f"Finding {finding_id} was not found for this client.")
        return {"created": await propose_for_finding(r, finding, get_writer(), adapter_for(r), a.actor)}

    @app.post("/api/clients/{client_id}/changes/propose-all")
    async def propose_all(client_id: int, a: Access = Depends(require("work.run"))) -> dict[str, Any]:
        r = repo(a)
        adapter, writer, created = adapter_for(r), get_writer(), []
        for f in r.list("findings", "status = 'open' AND fix_type IS NOT NULL"):
            created += await propose_for_finding(r, f, writer, adapter, a.actor)
        return {"created": created}

    # ---------- change requests ----------
    @app.get("/api/clients/{client_id}/changes")
    def list_changes(client_id: int, a: Access = Depends(require("client.view"))) -> list[dict[str, Any]]:
        return repo(a).list("change_requests", order="id DESC")

    async def _apply(r: ClientRepo, a: Access, change_id: int, action: str) -> dict[str, Any]:
        a.check(CHANGE_ACTIONS[action])
        if action == "deploy":
            return await change_svc.deploy_change(r, change_id, a.actor, a.change_role, adapter_for(r))
        if action == "rollback":
            return await change_svc.rollback_change(r, change_id, a.actor, a.change_role, adapter_for(r))
        return change_svc.transition(r, change_id, action, a.actor, a.change_role)

    @app.post("/api/clients/{client_id}/changes/bulk")
    async def bulk(client_id: int, body: BulkIn, a: Access = Depends(require("client.view"))) -> dict[str, Any]:
        r = repo(a)
        a.check(CHANGE_ACTIONS[body.action])
        source = {"submit": "draft", "approve": "awaiting_client", "deploy": "approved"}[body.action]
        rows = r.list("change_requests", "status = ?", (source,))
        if body.risk != "any":
            rows = [row for row in rows if row["risk"] == body.risk]
        results = []
        for row in rows:
            out = await _apply(r, a, row["id"], body.action)
            results.append({"id": out["id"], "status": out["status"]})
        return {"results": results}

    @app.post("/api/clients/{client_id}/changes/{change_id}/{action}")
    async def change_action(client_id: int, change_id: int,
                            action: Literal["submit", "approve", "reject", "discard", "deploy", "rollback"],
                            a: Access = Depends(require("client.view"))) -> dict[str, Any]:
        return await _apply(repo(a), a, change_id, action)

    # ---------- AI visibility ----------
    @app.post("/api/clients/{client_id}/visibility/run")
    def run_visibility(client_id: int, a: Access = Depends(require("work.run"))) -> dict[str, Any]:
        r = repo(a)
        if r.month_spend() >= r.client()["monthly_budget_usd"]:
            r.alert("warning", "Monthly budget reached; AI-visibility sampling paused.")
            raise HTTPException(402, "This client has reached its monthly running-cost cap. Raise the cap or wait until next month.")
        return visibility.run_sample(r, a.actor)

    @app.get("/api/clients/{client_id}/visibility")
    def get_visibility(client_id: int, a: Access = Depends(require("client.view"))) -> dict[str, Any]:
        return visibility.metrics(repo(a))

    @app.get("/api/clients/{client_id}/visibility/answers")
    def answers(client_id: int, a: Access = Depends(require("client.view"))) -> list[dict[str, Any]]:
        r = repo(a)
        last = r.list("ai_observations", order="run_no DESC")
        if not last:
            return []
        prompts = {p["id"]: p["text"] for p in r.list("prompts")}
        rows = r.list("ai_observations", "run_no = ?", (last[0]["run_no"],))
        return [{**row, "prompt": prompts.get(row["prompt_id"], "")} for row in rows]

    # ---------- Google: sign-in, connection (OAuth), Search Console, GA4, PageSpeed ----------
    @app.get("/api/auth/google/start")
    def google_signin_start(a: Access = Depends(require("public"))) -> RedirectResponse:
        url, state = google.start_signin(database)
        response = RedirectResponse(url, status_code=303)
        _set_state_cookie(response, state)
        return response

    @app.post("/api/auth/google/link")
    def google_link(body: auth_routes.TokenIn, a: Access = Depends(require("public"))) -> dict[str, str]:
        google_signin.confirm_link(database, body.token)
        return {"detail": "Google sign-in is now linked to your account."}

    @app.get("/api/oauth/google/callback")
    async def google_callback(request: Request, state: str = "", code: str | None = None, error: str | None = None,
                              a: Access = Depends(require("public"))) -> RedirectResponse:
        # Google redirects the browser here. The one-time state, matched against the cookie set when this browser
        # started, identifies the request.
        pending = google.take_state(database, state, request.cookies.get(google.STATE_COOKIE))
        if pending["purpose"] == "signin":
            outcome, raw = await google_signin.finish_signin(database, pending, code, error,
                                                             auth_routes.client_ip(request), auth_routes.user_agent(request))
            target = {"signed_in": "/?signin=ok#/", "mfa": "/?signin=mfa#/login"}.get(outcome, f"/?signin={outcome}#/login")
            response = RedirectResponse(target, status_code=303)
            if raw:
                if a.principal:
                    sessions.end(database, a.principal.session_hash)
                user = database.one("SELECT u.is_admin FROM sessions s JOIN users u ON u.id = s.user_id "
                                    "WHERE s.id_hash = ?", (tokens.digest(raw),))
                response.set_cookie(value=raw, **sessions.cookie_args(bool(user and user["is_admin"])))
        else:
            client_id, outcome = await google.finish_connect(database, pending, code, error)
            response = RedirectResponse(f"/?google={outcome}#/clients/{client_id}/google", status_code=303)
        response.delete_cookie(google.STATE_COOKIE, path="/api/")
        return response

    @app.get("/api/clients/{client_id}/connections/google")
    def google_status(client_id: int, a: Access = Depends(require("client.view"))) -> dict[str, Any]:
        return google.status(repo(a))

    @app.post("/api/clients/{client_id}/connections/google/start")
    def google_start(client_id: int, response: Response, a: Access = Depends(require("google.manage"))) -> dict[str, str]:
        url, state = google.start_connect(database, client_id, a.actor)
        _set_state_cookie(response, state)
        return {"auth_url": url}

    @app.get("/api/clients/{client_id}/connections/google/properties")
    async def google_properties(client_id: int, a: Access = Depends(require("google.manage"))) -> dict[str, Any]:
        return await google.list_properties(repo(a))

    @app.patch("/api/clients/{client_id}/connections/google")
    async def google_select(client_id: int, body: GoogleSelectIn, a: Access = Depends(require("google.manage"))) -> dict[str, Any]:
        return await google.select(repo(a), a.actor, body.gsc_site, body.ga4_property)

    @app.delete("/api/clients/{client_id}/connections/google")
    async def google_disconnect(client_id: int, a: Access = Depends(require("google.manage"))) -> dict[str, Any]:
        return await google.disconnect(repo(a), a.actor)

    @app.get("/api/clients/{client_id}/google/search-console")
    async def google_search_console(client_id: int, days: int = 28, a: Access = Depends(require("client.view"))) -> dict[str, Any]:
        return await google.search_console_report(repo(a), max(1, min(days, 480)))

    @app.get("/api/clients/{client_id}/google/analytics")
    async def google_analytics(client_id: int, days: int = 28, a: Access = Depends(require("client.view"))) -> dict[str, Any]:
        return await google.analytics_report(repo(a), max(1, min(days, 480)))

    @app.post("/api/clients/{client_id}/google/pagespeed")
    async def google_pagespeed(client_id: int, body: PageSpeedIn, a: Access = Depends(require("work.run"))) -> dict[str, Any]:
        return await google.pagespeed(repo(a), str(body.url) if body.url else None, body.strategy)

    # ---------- billing ----------
    @app.get("/api/plans")
    def plans(a: Access = Depends(require("public"))) -> list[dict[str, Any]]:
        return [p.public() for p in PLANS.values()]

    @app.post("/api/billing/checkout")
    def checkout(body: CheckoutIn, a: Access = Depends(require("billing.buy"))) -> dict[str, str]:
        return {"url": billing.start_checkout(database, a, body.plan, body.business_name)}

    @app.post("/api/billing/webhook")
    async def stripe_webhook(request: Request, a: Access = Depends(require("public"))) -> dict[str, str]:
        # Verified by Stripe's signature, not by a session (it is exempt from the CSRF check).
        event = billing.parse_event(await request.body(), request.headers.get("stripe-signature"))
        return {"result": await asyncio.to_thread(billing.handle_event, database, event)}

    @app.get("/api/clients/{client_id}/billing")
    def billing_summary(client_id: int, a: Access = Depends(require("billing.manage"))) -> dict[str, Any]:
        return billing.summary(database, client_id)

    @app.post("/api/clients/{client_id}/billing/portal")
    def billing_portal(client_id: int, a: Access = Depends(require("billing.manage"))) -> dict[str, str]:
        return {"url": billing.portal_url(database, a)}

    @app.post("/api/admin/clients/{client_id}/activate")
    def activate(client_id: int, a: Access = Depends(require("admin"))) -> dict[str, Any]:
        billing.activate_manually(database, a, client_id)
        return database.get_client(client_id) or {}

    # ---------- team ----------
    @app.get("/api/clients/{client_id}/team")
    def team_list(client_id: int, a: Access = Depends(require("client.view"))) -> dict[str, Any]:
        return team.listing(database, client_id)

    @app.post("/api/clients/{client_id}/team/invites", status_code=201)
    def team_invite(client_id: int, body: InviteIn, a: Access = Depends(require("team.manage"))) -> dict[str, Any]:
        return team.invite(database, a, body.email, body.can_approve)

    @app.delete("/api/clients/{client_id}/team/invites/{invite_id}")
    def team_cancel_invite(client_id: int, invite_id: int, a: Access = Depends(require("team.manage"))) -> dict[str, bool]:
        team.cancel_invite(database, a, invite_id)
        return {"ok": True}

    @app.patch("/api/clients/{client_id}/team/{user_id}")
    def team_update(client_id: int, user_id: int, body: MemberIn, a: Access = Depends(require("team.manage"))) -> dict[str, bool]:
        team.set_can_approve(database, a, user_id, body.can_approve)
        return {"ok": True}

    @app.delete("/api/clients/{client_id}/team/{user_id}")
    def team_remove(client_id: int, user_id: int, a: Access = Depends(require("team.manage"))) -> dict[str, bool]:
        team.remove(database, a, user_id)
        return {"ok": True}

    @app.post("/api/clients/{client_id}/team/transfer")
    def team_transfer(client_id: int, body: TransferIn, a: Access = Depends(require("team.manage"))) -> dict[str, bool]:
        team.transfer(database, a, body.user_id)
        return {"ok": True}

    @app.post("/api/invites/accept")
    def invite_accept(body: auth_routes.TokenIn, a: Access = Depends(require("account"))) -> dict[str, int]:
        return {"client_id": team.accept(database, a, body.token)}

    # ---------- reporting, log, export ----------
    @app.get("/api/clients/{client_id}/report", response_class=HTMLResponse)
    async def report(client_id: int, a: Access = Depends(require("client.view"))) -> str:
        return await services.report_html(repo(a), get_writer())

    @app.get("/api/clients/{client_id}/audit-log")
    def audit_log(client_id: int, a: Access = Depends(require("client.view"))) -> list[dict[str, Any]]:
        return repo(a).list("audit_events", order="id DESC")[:200]

    @app.post("/api/clients/{client_id}/alerts/{alert_id}/ack")
    def ack(client_id: int, alert_id: int, a: Access = Depends(require("client.view"))) -> dict[str, bool]:
        r = repo(a)
        if r.get("alerts", alert_id) is None:
            raise LookupError(f"Alert {alert_id} was not found.")
        r.update("alerts", alert_id, acknowledged=True)
        return {"ok": True}

    @app.get("/api/clients/{client_id}/export")
    def export(client_id: int, a: Access = Depends(require("client.export"))) -> dict[str, Any]:
        r = repo(a)
        r.log(a.actor, "data.exported", f"client:{client_id}", actor_user_id=a.user_id)
        return {"client": r.client(), "exported_at": now(),
                "sites": [r.public_site()],
                **{t: r.list(t) for t in ("findings", "change_requests", "prompts", "ai_observations",
                                          "audit_events", "usage_events")}}

    # ---------- demo controls (development only) ----------
    if not settings.is_production:
        @app.post("/api/demo/reset")
        async def demo_reset(a: Access = Depends(require("admin"))) -> dict[str, Any]:
            async with make_client() as client:
                try:
                    await client.post(settings.demo_site_url + "/__demo/reset")
                except httpx.HTTPError:
                    raise HTTPException(502, f"The demo website is not running at {settings.demo_site_url}. Start it with start.bat and try again.")
            database.wipe()
            seed_demo(database)
            return {"ok": True}

        @app.post("/api/demo/fault")
        async def demo_fault(body: FaultIn, a: Access = Depends(require("admin"))) -> dict[str, Any]:
            async with make_client() as client:
                resp = await client.post(settings.demo_site_url + "/__demo/fault", json={"on": body.on})
            return resp.json()

    if STATIC_DIR.joinpath("index.html").exists():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="portal")
    else:
        @app.get("/", response_class=HTMLResponse)
        def no_portal() -> str:
            return ("<h1>SEOSys API is running</h1><p>The portal has not been built yet. "
                    "Run <code>npm install && npm run build</code> in the frontend folder.</p>")
    return app


app = create_app()
