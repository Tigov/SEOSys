"""Change Request state machine, deployment, verification and rollback (FDD M10, TDD section 9).

draft --submit--> awaiting_client --approve--> approved --deploy--> deploying --> verifying --> live
                  (auto-approved when risk is low and the client opted in)                    or -> rolled_back (checks failed)
Only `deploy_change` and `rollback_change` ever write to a client site.
"""
from __future__ import annotations

import json
from typing import Any

from .adapters.site_wp import AdapterError, WordPressAdapter  # noqa: F401
from .crawler import blocked_ai_bots, fetch_page, fetch_text, parse_sitemap
from .db import ClientRepo, now
from .net import make_client

ROLE_ACTIONS = {
    "submit": {"staff"}, "discard": {"staff"}, "deploy": {"staff"},
    "approve": {"client"}, "reject": {"client"}, "rollback": {"staff", "client"},
}
TRANSITIONS = {
    "submit": ({"draft"}, "awaiting_client"),
    "discard": ({"draft", "blocked_policy", "awaiting_client", "rejected"}, "discarded"),
    "approve": ({"awaiting_client"}, "approved"),
    "reject": ({"awaiting_client"}, "rejected"),
}


class TransitionError(ValueError):
    pass


PAST = {"submit": "sent for approval", "approve": "approved", "reject": "rejected", "discard": "discarded"}


def _load(repo: ClientRepo, cr_id: int) -> dict[str, Any]:
    cr = repo.get("change_requests", cr_id)
    if cr is None:
        raise LookupError(f"Change #{cr_id} was not found for this client.")
    return cr


def _set(repo: ClientRepo, cr: dict[str, Any], actor: str, action: str, status: str, **extra: Any) -> dict[str, Any]:
    repo.update("change_requests", cr["id"], status=status, updated_at=now(), **extra)
    repo.log(actor, f"change.{action}", f"change:{cr['id']}", {"from": cr["status"], "to": status})
    return _load(repo, cr["id"])


def check_role(action: str, role: str) -> None:
    if role not in ROLE_ACTIONS.get(action, set()):
        raise PermissionError(f"The {'strategist' if role == 'staff' else 'client owner'} cannot {action} changes. " + ("Switch to Client owner to approve or reject." if action in ("approve", "reject") else "Switch to Strategist to do this."))


def transition(repo: ClientRepo, cr_id: int, action: str, actor: str, role: str) -> dict[str, Any]:
    check_role(action, role)
    cr = _load(repo, cr_id)
    allowed_from, to = TRANSITIONS[action]
    if cr["status"] not in allowed_from:
        raise TransitionError(f"Change #{cr['id']} cannot be {PAST.get(action, action)} because it is {cr['status'].replace('_', ' ')}.")
    extra: dict[str, Any] = {}
    if action == "submit" and cr["risk"] == "low" and repo.client()["auto_approve_low"]:
        to, extra["approved_by"] = "approved", "auto: client allows low-risk changes"
    if action == "approve":
        extra["approved_by"] = actor
    return _set(repo, cr, actor, action, to, **extra)


async def verify(repo: ClientRepo, cr: dict[str, Any], base_url: str) -> dict[str, Any]:
    """Recrawl what the change touched and compare with what we expected (FDD FR-10.5)."""
    target, after = cr["target"], json.loads(cr["after_value"])
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    async with make_client() as client:
        if cr["type"] == "redirect":
            facts = await fetch_page(client, base_url + target["source"])
            hops = facts.redirect_chain
            check("single_hop", len(hops) == 1, "One redirect" if len(hops) == 1 else f"{len(hops)} redirects in a row")
            check("lands_on_target", facts.final_url.endswith(after) or facts.final_url.rstrip("/") == base_url + after.rstrip("/"),
                  f"Ends at {facts.final_url}")
            check("target_ok", facts.status == 200, f"HTTP {facts.status}")
        elif cr["type"] == "robots_txt":
            text = await fetch_text(client, base_url + "/robots.txt")
            still_blocked = blocked_ai_bots(text, base_url)
            check("ai_crawlers_allowed", not still_blocked, "None blocked" if not still_blocked else f"Still blocked: {', '.join(still_blocked)}")
            home = await fetch_page(client, base_url + "/")
            check("homepage_ok", home.status == 200, f"HTTP {home.status}")
        else:
            path = target["path"]
            facts = await fetch_page(client, base_url + path)
            check("page_loads", facts.status == 200, f"HTTP {facts.status}")
            field = target.get("field", "image_alt")
            if facts.status == 200:
                if field == "title":
                    check("title_applied", facts.title == after, facts.title)
                elif field == "meta_description":
                    check("description_applied", facts.meta_description == after, facts.meta_description)
                elif field == "h1":
                    check("h1_applied", after in facts.h1s, ", ".join(facts.h1s) or "No heading found")
                elif field == "canonical":
                    check("canonical_applied", facts.canonical.endswith(after), facts.canonical)
                elif field == "noindex":
                    check("indexability_applied", facts.noindex == after, "Hidden from Google" if facts.noindex else "Visible to Google")
                elif field == "schema_jsonld":
                    want = json.loads(after).get("@type")
                    check("schema_present", want in facts.jsonld_types, ", ".join(t for t in facts.jsonld_types if t) or "None found")
                elif field == "image_alt":
                    img = next((i for i in facts.images if i["src"] == target["image_src"]), None)
                    check("alt_applied", bool(img and img["alt"] == after), f"Alt text: {img['alt']}" if img and img["alt"] else "No alt text found")
                elif field == "in_sitemap":
                    urls = parse_sitemap(await fetch_text(client, base_url + "/sitemap.xml"))
                    check("sitemap_updated", (base_url + path in urls) == after, f"{len(urls)} pages listed")
                if field != "noindex":
                    crawl = repo.latest_crawl()
                    prior = repo.list("pages", "crawl_id = ? AND path = ?", (crawl["id"], path)) if crawl else []
                    if prior:
                        same = facts.noindex == bool(prior[0]["noindex"])
                        check("indexability_unchanged", same,
                              ("Still hidden from Google" if facts.noindex else "Still visible to Google") if same
                              else ("Now hidden from Google" if facts.noindex else "Now visible to Google"))
    return {"passed": all(c["passed"] for c in checks), "checks": checks, "at": now()}


async def deploy_change(repo: ClientRepo, cr_id: int, actor: str, role: str, adapter: WordPressAdapter) -> dict[str, Any]:
    check_role("deploy", role)
    cr = _load(repo, cr_id)
    if repo.client()["freeze_deploys"]:
        raise TransitionError("Deployments are frozen for this client. Turn off the freeze switch on the Overview tab to deploy.")
    if cr["status"] != "approved":
        raise TransitionError(f"Only approved changes can be deployed. Change #{cr_id} is {cr['status'].replace('_', ' ')}.")
    # Claim the change atomically so a double-click or a parallel bulk deploy cannot write twice.
    if not repo.claim("change_requests", cr_id, "approved", "deploying", updated_at=now()):
        raise TransitionError("This change is already being deployed.")
    repo.log(actor, "change.deploy", f"change:{cr_id}", {"from": "approved", "to": "deploying"})
    cr = _load(repo, cr_id)
    base_url = repo.site()["base_url"].rstrip("/")
    before, after = json.loads(cr["before_value"]), json.loads(cr["after_value"])

    try:
        current = await adapter.current_value(cr["type"], cr["target"])
    except Exception as exc:  # nothing was written yet
        return _set(repo, cr, actor, "deploy_failed", "failed", deploy_result={"error": f"Could not read the current page from the site: {exc}"})
    if current != before:
        return _set(repo, cr, actor, "deploy_conflict", "failed",
                    deploy_result={"error": "The page changed on the site after this fix was drafted. Draft the fix again so it starts from the current version.",
                                   "expected_before": before, "found": current})

    written = False
    try:
        result = await adapter.write(cr["type"], cr["target"], after)
        written = True
        cr = _set(repo, cr, actor, "verify", "verifying", deploy_result={"site_response": result, "applied_at": now()})
        verification = await verify(repo, cr, base_url)
    except Exception as exc:  # any failure after a possible write must not leave the site half-changed
        verification = {"passed": False, "checks": [{"name": "deploy_completed", "passed": False,
                                                     "detail": f"{type(exc).__name__}: {exc}"}], "at": now()}
        if not written:
            return _set(repo, cr, actor, "deploy_failed", "failed", deploy_result={"error": str(exc)},
                        verification=verification)

    if verification["passed"]:
        if cr["finding_id"]:
            repo.update("findings", cr["finding_id"], status="fix_deployed")
        return _set(repo, cr, actor, "live", "live", verification=verification)

    # Automatic rollback (FDD FR-10.5, NFR-12)
    try:
        await adapter.write(cr["type"], cr["target"], before)
        rollback = "previous version restored"
    except Exception as exc:
        rollback = f"rollback failed ({exc})"
    failed = [c["name"] for c in verification["checks"] if not c["passed"]]
    repo.alert("critical", f"Change #{cr['id']} failed its live checks, so the previous version was restored automatically." if rollback == "previous version restored" else f"Change #{cr['id']} failed its live checks and could not be rolled back. Fix it by hand now: {rollback}.")
    return _set(repo, cr, "system", "auto_rollback", "rolled_back",
                verification={**verification, "rollback": rollback})


async def rollback_change(repo: ClientRepo, cr_id: int, actor: str, role: str, adapter: WordPressAdapter) -> dict[str, Any]:
    check_role("rollback", role)
    cr = _load(repo, cr_id)
    if cr["status"] != "live":
        raise TransitionError("Only live changes can be rolled back.")
    try:
        await adapter.write(cr["type"], cr["target"], json.loads(cr["before_value"]))
    except AdapterError as exc:
        raise TransitionError(f"The rollback failed: {exc}") from exc
    if cr["finding_id"]:
        repo.update("findings", cr["finding_id"], status="open")
    return _set(repo, cr, actor, "rollback", "rolled_back")
