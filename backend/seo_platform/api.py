"""HTTP API and static portal (run: uvicorn seo_platform.api:app --port 8000 from the backend folder).

Auth is out of scope for the PoC: the portal sends X-Role (staff | client) and
X-Actor headers so role rules can be exercised. Production uses Cognito JWTs
(TDD section 10).
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Literal

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

from . import changes as change_svc
from . import services, visibility
from .adapters import google
from .auth import routes as auth_routes
from .auth.service import AuthError
from . import mailer
from .adapters.llm import get_writer
from .adapters.site_wp import AdapterError, WordPressAdapter
from .config import settings
from .db import ClientRepo, Database, now
from .fixes import propose_for_finding
from .net import BlockedHostError, make_client

log = logging.getLogger("seo_platform")
STATIC_DIR = Path(__file__).with_name("static")

DEMO_CLIENT = {
    "name": "Lone Star Comfort HVAC", "city": "Austin", "region": "TX", "phone": "(512) 555-0142",
    "street": "4100 Burnet Rd", "postal_code": "78756",
    "services": ["AC repair", "furnace repair", "emergency HVAC repair", "HVAC maintenance"],
    "competitors": ["Capital City Air", "Hill Country Heating & Air", "BlueBonnet Comfort Pros"],
}


class Caller(BaseModel):
    role: Literal["staff", "client"]
    actor: str


class GradeIn(BaseModel):
    url: HttpUrl
    email: str | None = None
    business_name: str | None = None
    city: str | None = None


class ClientIn(BaseModel):
    name: str = Field(min_length=2)
    city: str = ""
    region: str = ""
    phone: str = ""
    street: str = ""
    postal_code: str = ""
    services: list[str] = []
    competitors: list[str] = []
    site_url: HttpUrl
    cms: Literal["wordpress", "shopify", "github", "other"] = "wordpress"
    site_secret: str = ""


class SettingsIn(BaseModel):
    auto_approve_low: bool | None = None
    freeze_deploys: bool | None = None


class BulkIn(BaseModel):
    action: Literal["submit", "approve", "deploy"]
    risk: Literal["low", "medium", "high", "any"] = "any"


class FaultIn(BaseModel):
    on: bool


class GoogleSelectIn(BaseModel):
    gsc_site: str | None = None
    ga4_property: str | None = None


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


def create_app(db: Database | None = None) -> FastAPI:
    database = db or Database(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if not settings.is_production:
            seed_demo(database)
        sender = None if settings.is_test else asyncio.create_task(_send_mail_forever(database))
        yield
        if sender:
            sender.cancel()

    app = FastAPI(title="SEO Platform PoC", lifespan=lifespan)
    app.state.db = database
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["*"], allow_headers=["*"])

    app.include_router(auth_routes.router)

    # ---------- error mapping ----------
    @app.exception_handler(AuthError)
    async def auth_error(_: Request, exc: AuthError) -> JSONResponse:
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

    # ---------- dependencies ----------

    def caller(x_role: str | None = Header(None), x_actor: str = Header("")) -> Caller:
        # Stand-in for real authentication (TDD section 10): a missing role is rejected, never assumed.
        if x_role not in ("staff", "client"):
            raise HTTPException(401, "Sign-in is missing. Send an X-Role header of staff or client.")
        return Caller(role=x_role, actor=x_actor or f"{x_role}:demo")  # type: ignore[arg-type]

    def repo_for(client_id: int) -> ClientRepo:
        return database.for_client(client_id)

    def staff_only(c: Caller) -> None:
        if c.role != "staff":
            raise PermissionError("Only the strategist can do this.")

    def adapter_for(repo: ClientRepo) -> WordPressAdapter:
        site = repo.site()
        if site["cms"] != "wordpress":
            raise HTTPException(400, f"Direct changes to {site['cms']} sites are not in this proof of concept yet. Recommendations only.")
        return WordPressAdapter(site["base_url"], site["adapter_secret"])

    # ---------- health / grader ----------
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "llm": get_writer().name, "demo_site": settings.demo_site_url}


    @app.post("/api/grader")
    async def grader(body: GradeIn) -> dict[str, Any]:
        return await services.grade(database, str(body.url).rstrip("/"), body.email, body.business_name, body.city)

    @app.get("/api/leads")
    def leads(c: Caller = Depends(caller)) -> list[dict[str, Any]]:
        staff_only(c)
        return database.query("SELECT id, url, email, business_name, city, score, created_at FROM leads ORDER BY id DESC")

    # ---------- clients ----------

    @app.get("/api/clients")
    def list_clients(c: Caller = Depends(caller)) -> list[dict[str, Any]]:
        staff_only(c)
        out = []
        for cl in database.list_clients():
            repo = ClientRepo(database, cl["id"])
            crawl = repo.latest_crawl()
            out.append({**cl, "health_score": crawl["health_score"] if crawl else None,
                        "waiting_on_client": len(repo.list("change_requests", "status = 'awaiting_client'"))})
        return out

    @app.post("/api/clients", status_code=201)
    def create_client(body: ClientIn, c: Caller = Depends(caller)) -> dict[str, Any]:
        staff_only(c)
        data = body.model_dump()
        site_url, cms, secret = str(data.pop("site_url")).rstrip("/"), data.pop("cms"), data.pop("site_secret")
        cid = database.create_client(**data, monthly_budget_usd=settings.default_monthly_budget_usd)
        repo = database.for_client(cid)
        repo.insert("sites", {"base_url": site_url, "cms": cms, "adapter_secret": secret, "created_at": now()})
        repo.log(c.actor, "client.created", f"client:{cid}")
        return repo.client()

    @app.get("/api/clients/{client_id}")
    def get_client(client_id: int, c: Caller = Depends(caller)) -> dict[str, Any]:
        return services.summary(repo_for(client_id))


    @app.patch("/api/clients/{client_id}/settings")
    def update_settings(client_id: int, body: SettingsIn, c: Caller = Depends(caller)) -> dict[str, Any]:
        repo = repo_for(client_id)
        changes = {k: int(v) for k, v in body.model_dump().items() if v is not None}
        if "auto_approve_low" in changes and c.role != "client":
            raise PermissionError("Only the client can turn on auto-approval of low-risk changes.")
        if changes:
            repo.update_client(**changes)
            repo.log(c.actor, "settings.updated", f"client:{client_id}", changes)
        return repo.client()

    # ---------- audit and findings ----------
    @app.post("/api/clients/{client_id}/audits")
    async def run_audit(client_id: int, c: Caller = Depends(caller)) -> dict[str, Any]:
        staff_only(c)
        try:
            return await services.run_audit(repo_for(client_id), c.actor)
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"The audit could not reach the website: {exc}")

    @app.get("/api/clients/{client_id}/findings")
    def findings(client_id: int, status: str | None = None, c: Caller = Depends(caller)) -> list[dict[str, Any]]:
        repo = repo_for(client_id)
        rows = repo.list("findings", "status = ?", (status,)) if status else repo.list("findings")
        return sorted(rows, key=lambda f: (services.SEVERITY_ORDER.get(f["severity"], 9), -(f["impact"] or 0), f["id"]))

    @app.get("/api/clients/{client_id}/pages")
    def pages(client_id: int, c: Caller = Depends(caller)) -> list[dict[str, Any]]:
        repo = repo_for(client_id)
        crawl = repo.latest_crawl()
        return repo.list("pages", "crawl_id = ?", (crawl["id"],)) if crawl else []

    @app.post("/api/clients/{client_id}/findings/{finding_id}/propose")
    async def propose(client_id: int, finding_id: int, c: Caller = Depends(caller)) -> dict[str, Any]:
        staff_only(c)
        repo = repo_for(client_id)
        finding = repo.get("findings", finding_id)
        if finding is None:
            raise LookupError(f"Finding {finding_id} was not found for this client.")
        ids = await propose_for_finding(repo, finding, get_writer(), adapter_for(repo), c.actor)
        return {"created": ids}

    @app.post("/api/clients/{client_id}/changes/propose-all")
    async def propose_all(client_id: int, c: Caller = Depends(caller)) -> dict[str, Any]:
        staff_only(c)
        repo = repo_for(client_id)
        adapter, writer, created = adapter_for(repo), get_writer(), []
        for f in repo.list("findings", "status = 'open' AND fix_type IS NOT NULL"):
            created += await propose_for_finding(repo, f, writer, adapter, c.actor)
        return {"created": created}

    # ---------- change requests ----------
    @app.get("/api/clients/{client_id}/changes")
    def list_changes(client_id: int, c: Caller = Depends(caller)) -> list[dict[str, Any]]:
        return repo_for(client_id).list("change_requests", order="id DESC")

    @app.post("/api/clients/{client_id}/changes/{change_id}/{action}")
    async def change_action(client_id: int, change_id: int,
                            action: Literal["submit", "approve", "reject", "discard", "deploy", "rollback"],
                            c: Caller = Depends(caller)) -> dict[str, Any]:
        repo = repo_for(client_id)
        if action == "deploy":
            return await change_svc.deploy_change(repo, change_id, c.actor, c.role, adapter_for(repo))
        if action == "rollback":
            return await change_svc.rollback_change(repo, change_id, c.actor, c.role, adapter_for(repo))
        return change_svc.transition(repo, change_id, action, c.actor, c.role)


    @app.post("/api/clients/{client_id}/changes/bulk")
    async def bulk(client_id: int, body: BulkIn, c: Caller = Depends(caller)) -> dict[str, Any]:
        repo = repo_for(client_id)
        source = {"submit": "draft", "approve": "awaiting_client", "deploy": "approved"}[body.action]
        rows = repo.list("change_requests", "status = ?", (source,))
        if body.risk != "any":
            rows = [r for r in rows if r["risk"] == body.risk]
        results = []
        for r in rows:
            if body.action == "deploy":
                out = await change_svc.deploy_change(repo, r["id"], c.actor, c.role, adapter_for(repo))
            else:
                out = change_svc.transition(repo, r["id"], body.action, c.actor, c.role)
            results.append({"id": out["id"], "status": out["status"]})
        return {"results": results}

    # ---------- AI visibility ----------
    @app.post("/api/clients/{client_id}/visibility/run")
    def run_visibility(client_id: int, c: Caller = Depends(caller)) -> dict[str, Any]:
        staff_only(c)
        repo = repo_for(client_id)
        if repo.month_spend() >= repo.client()["monthly_budget_usd"]:
            repo.alert("warning", "Monthly budget reached; AI-visibility sampling paused.")
            raise HTTPException(402, "This client has reached its monthly running-cost cap. Raise the cap or wait until next month.")
        return visibility.run_sample(repo, c.actor)

    @app.get("/api/clients/{client_id}/visibility")
    def get_visibility(client_id: int, c: Caller = Depends(caller)) -> dict[str, Any]:
        return visibility.metrics(repo_for(client_id))

    @app.get("/api/clients/{client_id}/visibility/answers")
    def answers(client_id: int, c: Caller = Depends(caller)) -> list[dict[str, Any]]:
        repo = repo_for(client_id)
        last = repo.list("ai_observations", order="run_no DESC")
        if not last:
            return []
        prompts = {p["id"]: p["text"] for p in repo.list("prompts")}
        rows = repo.list("ai_observations", "run_no = ?", (last[0]["run_no"],))
        return [{**r, "prompt": prompts.get(r["prompt_id"], "")} for r in rows]

    # ---------- Google: connection (OAuth), Search Console, GA4, PageSpeed ----------
    @app.get("/api/clients/{client_id}/connections/google")
    def google_status(client_id: int, c: Caller = Depends(caller)) -> dict[str, Any]:
        return google.status(repo_for(client_id))

    @app.post("/api/clients/{client_id}/connections/google/start")
    def google_start(client_id: int, c: Caller = Depends(caller)) -> dict[str, str]:
        return {"auth_url": google.start_connect(database, client_id, c.actor)}

    @app.get("/api/oauth/google/callback")
    async def google_callback(state: str = "", code: str | None = None, error: str | None = None) -> RedirectResponse:
        # Google redirects the browser here, so there are no role headers; the one-time state identifies the request.
        client_id, outcome = await google.finish_connect(database, state, code, error)
        return RedirectResponse(f"/?google={outcome}#/clients/{client_id}/google", status_code=303)

    @app.get("/api/clients/{client_id}/connections/google/properties")
    async def google_properties(client_id: int, c: Caller = Depends(caller)) -> dict[str, Any]:
        return await google.list_properties(repo_for(client_id))

    @app.patch("/api/clients/{client_id}/connections/google")
    async def google_select(client_id: int, body: GoogleSelectIn, c: Caller = Depends(caller)) -> dict[str, Any]:
        return await google.select(repo_for(client_id), c.actor, body.gsc_site, body.ga4_property)

    @app.delete("/api/clients/{client_id}/connections/google")
    async def google_disconnect(client_id: int, c: Caller = Depends(caller)) -> dict[str, Any]:
        return await google.disconnect(repo_for(client_id), c.actor)

    @app.get("/api/clients/{client_id}/google/search-console")
    async def google_search_console(client_id: int, days: int = 28, c: Caller = Depends(caller)) -> dict[str, Any]:
        return await google.search_console_report(repo_for(client_id), max(1, min(days, 480)))

    @app.get("/api/clients/{client_id}/google/analytics")
    async def google_analytics(client_id: int, days: int = 28, c: Caller = Depends(caller)) -> dict[str, Any]:
        return await google.analytics_report(repo_for(client_id), max(1, min(days, 480)))

    @app.post("/api/clients/{client_id}/google/pagespeed")
    async def google_pagespeed(client_id: int, body: PageSpeedIn, c: Caller = Depends(caller)) -> dict[str, Any]:
        staff_only(c)
        return await google.pagespeed(repo_for(client_id), str(body.url) if body.url else None, body.strategy)

    # ---------- reporting, log, export, ops ----------
    @app.get("/api/clients/{client_id}/report", response_class=HTMLResponse)
    async def report(client_id: int, c: Caller = Depends(caller)) -> str:
        return await services.report_html(repo_for(client_id), get_writer())

    @app.get("/api/clients/{client_id}/audit-log")
    def audit_log(client_id: int, c: Caller = Depends(caller)) -> list[dict[str, Any]]:
        return repo_for(client_id).list("audit_events", order="id DESC")[:200]

    @app.post("/api/clients/{client_id}/alerts/{alert_id}/ack")
    def ack(client_id: int, alert_id: int, c: Caller = Depends(caller)) -> dict[str, bool]:
        repo = repo_for(client_id)
        if repo.get("alerts", alert_id) is None:
            raise LookupError(f"Alert {alert_id} was not found.")
        repo.update("alerts", alert_id, acknowledged=1)
        return {"ok": True}

    @app.get("/api/clients/{client_id}/export")
    def export(client_id: int, c: Caller = Depends(caller)) -> dict[str, Any]:
        repo = repo_for(client_id)
        repo.log(c.actor, "data.exported", f"client:{client_id}")
        return {"client": repo.client(), "exported_at": now(),
                "sites": [repo.public_site()],
                **{t: repo.list(t) for t in ("findings", "change_requests", "prompts", "ai_observations",
                                             "audit_events", "usage_events")}}

    @app.get("/api/ops/usage")
    def usage(c: Caller = Depends(caller)) -> list[dict[str, Any]]:
        staff_only(c)
        return database.query("SELECT client_id, vendor, SUM(qty) AS qty, ROUND(SUM(cost_usd), 4) AS cost_usd "
                              "FROM usage_events GROUP BY client_id, vendor ORDER BY client_id, cost_usd DESC")

    # ---------- demo controls (local only) ----------
    @app.post("/api/demo/reset")
    async def demo_reset(c: Caller = Depends(caller)) -> dict[str, Any]:
        staff_only(c)
        async with make_client() as client:
            try:
                await client.post(settings.demo_site_url + "/__demo/reset")
            except httpx.HTTPError as exc:
                raise HTTPException(502, f"The demo website is not running at {settings.demo_site_url}. Start it with start.bat and try again.")
        database.wipe()
        seed_demo(database)
        return {"ok": True}


    @app.post("/api/demo/fault")
    async def demo_fault(body: FaultIn, c: Caller = Depends(caller)) -> dict[str, Any]:
        staff_only(c)
        async with make_client() as client:
            resp = await client.post(settings.demo_site_url + "/__demo/fault", json={"on": body.on})
        return resp.json()

    if STATIC_DIR.joinpath("index.html").exists():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="portal")
    else:
        @app.get("/", response_class=HTMLResponse)
        def no_portal() -> str:
            return ("<h1>SEO Platform API is running</h1><p>The portal has not been built yet. "
                    "Run <code>npm install && npm run build</code> in the frontend folder, or open "
                    "<a href='/docs'>/docs</a> for the API.</p>")
    return app


app = create_app()
