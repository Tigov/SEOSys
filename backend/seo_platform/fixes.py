"""Fix generator (TDD section 7 "Fix Generator", FDD FR-10.1/10.2).

Turns an evidence-backed finding into one or more Change Requests with the
current value read from the site (before), a proposed value (after), a risk
level, and policy flags. Nothing is deployed here.
"""
from __future__ import annotations

import difflib
import json
from typing import Any

from .adapters.llm import Writer
from .adapters.site_wp import WordPressAdapter
from .crawler import AI_BOTS
from .db import ClientRepo, now
from .policy import lint

# Risk per FDD FR-10.2: Low = meta/alt/schema on one page; Medium = content edits;
# High = redirects, robots.txt, canonicals, sitemap, indexability.
RISK = {"title": "low", "meta_description": "low", "image_alt": "low", "schema_jsonld": "low", "h1": "medium",
        "canonical": "high", "noindex": "high", "in_sitemap": "high", "redirect": "high", "robots_txt": "high"}
OPEN_STATUSES = ("draft", "awaiting_client", "approved", "deploying", "verifying", "blocked_policy")
MAX_CHARS = {"title": 60, "meta_description": 155, "h1": 70, "alt": 100}


def _page_ctx(page: dict[str, Any] | None, client: dict[str, Any], path: str) -> dict[str, Any]:
    business = {k: client.get(k) for k in ("name", "city", "region", "phone")}
    if page is None:
        return {"business": business, "path": path}
    return {"business": business, "path": path, "title": page["title"], "h1": (page["h1s"] or [""])[0]}


def local_business_schema(client: dict[str, Any], base_url: str) -> str:
    data = {
        "@context": "https://schema.org", "@type": "HVACBusiness", "name": client["name"], "url": base_url + "/",
        "telephone": client.get("phone") or "", "areaServed": client.get("city") or "",
        "address": {"@type": "PostalAddress", "streetAddress": client.get("street") or "",
                    "addressLocality": client.get("city") or "", "addressRegion": client.get("region") or "",
                    "postalCode": client.get("postal_code") or "", "addressCountry": "US"},
    }
    # Escape characters that could close the <script> tag if a business name contains markup.
    text = json.dumps(data, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def robots_without_ai_blocks(robots_txt: str) -> str:
    """Drop user-agent groups that target only AI crawlers; keep every other rule and Sitemap lines.

    robots.txt groups are one or more User-agent lines followed by rule lines. Directives that are not
    part of a group (Sitemap, Host) are kept as they are.
    """
    ai = {b.lower() for b in AI_BOTS}
    groups: list[dict[str, list[str]]] = []
    standalone: list[str] = []
    current: dict[str, list[str]] | None = None
    for raw in robots_txt.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        key_l = key.lower()
        if key_l == "user-agent":
            if current is None or current["rules"]:
                current = {"agents": [], "rules": []}
                groups.append(current)
            current["agents"].append(value)
        elif key_l in ("sitemap", "host"):
            standalone.append(f"{key}: {value}")
        elif current is not None:
            current["rules"].append(f"{key}: {value}")
    kept = [g for g in groups if not all(a.lower() in ai for a in g["agents"])]
    blocks = ["\n".join([*(f"User-agent: {a}" for a in g["agents"]), *g["rules"]]) for g in kept]
    text = "\n\n".join(blocks) or "User-agent: *\nDisallow:"
    if standalone:
        text += "\n\n" + "\n".join(standalone)
    return text + "\n"


def best_redirect_target(broken_path: str, good_paths: list[str]) -> str:
    match = difflib.get_close_matches(broken_path, good_paths, n=1, cutoff=0.3)
    return match[0] if match else "/"


async def propose_for_finding(repo: ClientRepo, finding: dict[str, Any], writer: Writer,
                              adapter: WordPressAdapter, actor: str) -> list[int]:
    client = repo.client()
    site = repo.site()
    fix_type = finding["fix_type"]
    if not fix_type:
        return []
    crawl = repo.latest_crawl()
    pages = {p["path"]: p for p in repo.list("pages", "crawl_id = ?", (crawl["id"],))} if crawl else {}
    good_paths = [p for p, row in pages.items() if row["status"] == 200 and not row["redirect_chain"]]
    ev = finding["evidence"]
    specs: list[tuple[str, dict[str, Any], Any, str]] = []  # (type, target, after, reason)

    if fix_type in ("title", "meta_description", "h1", "canonical", "noindex", "in_sitemap", "schema_jsonld"):
        paths = ev.get("paths") or [_path(u) for u in finding["urls"]] or ["/"]
        for path in paths:
            page = pages.get(path)
            ctx = _page_ctx(page, client, path)
            if fix_type in ("title", "meta_description", "h1"):
                after, usage = await writer.write(fix_type, ctx, MAX_CHARS[fix_type])
                repo.meter(writer.name, "llm_call", 1, usage["cost_usd"])
            elif fix_type == "canonical":
                after = path
            elif fix_type == "noindex":
                after = False
            elif fix_type == "in_sitemap":
                after = True
            else:
                after = local_business_schema(client, site["base_url"].rstrip("/"))
            specs.append(("page_field", {"path": path, "field": fix_type}, after, finding["title"]))
    elif fix_type == "image_alt":
        path = _path(finding["urls"][0])
        ctx = {**_page_ctx(pages.get(path), client, path), "image_src": ev["image_src"]}
        after, usage = await writer.write("alt", ctx, MAX_CHARS["alt"])
        repo.meter(writer.name, "llm_call", 1, usage["cost_usd"])
        specs.append(("image_alt", {"path": path, "image_src": ev["image_src"]}, after, finding["title"]))
    elif fix_type == "redirect":
        source = _path(finding["urls"][0])
        if finding["rule_id"] == "redirect_chain":
            after = _path(ev["hops"][-1])
            source = _path(ev["hops"][0])
        else:
            after = best_redirect_target(source, good_paths)
        specs.append(("redirect", {"source": source}, after, finding["title"]))
    elif fix_type == "robots_txt":
        current = await adapter.current_value("robots_txt", {})
        specs.append(("robots_txt", {}, robots_without_ai_blocks(current), finding["title"]))

    created: list[int] = []
    for change_type, target, after, reason in specs:
        risk_key = target.get("field") or change_type
        if _has_open_change(repo, change_type, target):
            continue
        before = await adapter.current_value(change_type, target)
        if before == after:
            continue
        flags = lint(after) if isinstance(after, str) and change_type != "robots_txt" else []
        status = "blocked_policy" if flags else "draft"
        cr_id = repo.insert("change_requests", {
            "site_id": site["id"], "finding_id": finding["id"], "type": change_type, "target": target,
            "before_value": json.dumps(before), "after_value": json.dumps(after), "risk": RISK[risk_key],
            "status": status, "reason": reason, "author": actor, "policy_flags": flags,
            "created_at": now(), "updated_at": now(),
        })
        repo.log(actor, "change.proposed", f"change:{cr_id}", {"type": change_type, "target": target, "risk": RISK[risk_key],
                                                              "policy_flags": flags})
        created.append(cr_id)
    return created


def _path(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).path or "/"


def _has_open_change(repo: ClientRepo, change_type: str, target: dict[str, Any]) -> bool:
    marks = ",".join("?" for _ in OPEN_STATUSES)
    rows = repo.list("change_requests", f"type = ? AND status IN ({marks})", (change_type, *OPEN_STATUSES))
    return any(r["target"] == target for r in rows)
