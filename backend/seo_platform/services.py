"""Use cases that combine modules: running an audit, grading a lead, building reports."""
from __future__ import annotations

import html
from collections import Counter
from typing import Any

from .adapters.llm import Writer
from .crawler import crawl
from .db import ClientRepo, Database, now
from .policy import lint
from .rules import health_score, run_rules
from .visibility import metrics as visibility_metrics

CRAWL_COST_PER_PAGE_USD = 0.0005  # compute estimate for metering
FIELD_LABELS = {"title": "Page title", "meta_description": "Meta description", "h1": "Main heading", "canonical": "Canonical tag",
                "noindex": "Google indexing", "in_sitemap": "XML sitemap", "schema_jsonld": "Business schema"}


def change_label(c: dict[str, Any]) -> str:
    if c["type"] == "page_field":
        return FIELD_LABELS.get(c["target"].get("field", ""), "Page setting")
    return {"image_alt": "Image alt text", "redirect": "Redirect", "robots_txt": "robots.txt"}.get(c["type"], c["type"])


def _count(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


async def run_audit(repo: ClientRepo, actor: str, kind: str = "audit") -> dict[str, Any]:
    site = repo.site()
    crawl_id = repo.insert("crawls", {"site_id": site["id"], "kind": kind, "started_at": now()})
    result = await crawl(site["base_url"])
    page_rows = []
    for facts in result.pages:
        row = facts.to_row()
        repo.insert("pages", {**row, "crawl_id": crawl_id})
        page_rows.append(row)
    findings = run_rules(page_rows, result.ai_bots_blocked, result.sitemap_urls)
    score = health_score(findings)

    existing = {f["fingerprint"]: f for f in repo.list("findings", "status != 'resolved'")}
    seen = set()
    for f in findings:
        seen.add(f["fingerprint"])
        if f["fingerprint"] in existing:
            old = existing[f["fingerprint"]]
            status = "open" if old["status"] == "fix_deployed" else old["status"]  # fix did not hold
            repo.update("findings", old["id"], crawl_id=crawl_id, evidence=f["evidence"], urls=f["urls"],
                        title=f["title"], last_seen=now(), status=status)
        else:
            repo.insert("findings", {**f, "crawl_id": crawl_id, "status": "open", "first_seen": now(), "last_seen": now()})
    resolved = 0
    for fp, old in existing.items():
        if fp not in seen:
            repo.update("findings", old["id"], status="resolved", resolved_at=now())
            resolved += 1
    repo.update("crawls", crawl_id, finished_at=now(), pages_crawled=len(page_rows), health_score=score,
                robots_txt=result.robots_txt, ai_bots_blocked=result.ai_bots_blocked, sitemap_urls=result.sitemap_urls)
    repo.meter("Site crawling (compute)", "page", len(page_rows), len(page_rows) * CRAWL_COST_PER_PAGE_USD)
    repo.log(actor, "audit.completed", f"crawl:{crawl_id}", {"pages": len(page_rows), "findings": len(findings),
                                                             "resolved": resolved, "health_score": score})
    return {"crawl_id": crawl_id, "pages": len(page_rows), "findings": len(findings), "resolved": resolved, "health_score": score}


async def grade(db: Database, url: str, email: str | None, business_name: str | None, city: str | None,
                user_id: int | None = None) -> dict[str, Any]:
    """Free grader (FDD M1): a quick, read-only crawl with no account or access needed."""
    result = await crawl(url, max_pages=15)
    rows = [p.to_row() for p in result.pages]
    findings = run_rules(rows, result.ai_bots_blocked, result.sitemap_urls)
    by_rule = Counter(f["rule_id"] for f in findings)
    tech_rules = {"broken_link", "redirect_chain", "noindex_important", "not_in_sitemap", "missing_sitemap", "missing_canonical"}
    onpage_rules = {"missing_title", "title_too_long", "duplicate_title", "missing_meta_description", "missing_h1",
                    "multiple_h1", "img_missing_alt", "thin_content"}
    ai_rules = {"ai_crawlers_blocked", "missing_local_business_schema"}

    def section(rules: set[str]) -> int:
        return health_score([f for f in findings if f["rule_id"] in rules])

    top = sorted(findings, key=lambda f: (SEVERITY_ORDER[f["severity"]], -f["impact"]))[:6]
    out = {
        "url": url, "pages_checked": len(rows), "score": health_score(findings),
        "sections": {"Technical health": section(tech_rules), "On-page basics": section(onpage_rules),
                     "AI and local readiness": section(ai_rules)},
        "issue_counts": dict(by_rule),
        "top_issues": [{"severity": f["severity"], "title": f["title"], "fix_hint": f["fix_hint"]} for f in top],
    }
    db.insert("leads", {"url": url, "email": email, "business_name": business_name, "city": city,
                        "score": out["score"], "result": out, "user_id": user_id, "created_at": now()})
    db.log(None, "grader", "grader.run", url, {"score": out["score"], "lead": bool(email)})
    return out


def summary(repo: ClientRepo) -> dict[str, Any]:
    client = repo.client()
    crawl = repo.latest_crawl()
    findings = repo.list("findings", "status != 'resolved'")
    changes = repo.list("change_requests")
    status_counts = Counter(c["status"] for c in changes)
    sev_counts = Counter(f["severity"] for f in findings if f["status"] == "open")
    history = [{"crawl_id": c["id"], "at": c["finished_at"], "health_score": c["health_score"]}
               for c in repo.list("crawls", "kind = 'audit' AND finished_at IS NOT NULL")]
    vis = visibility_metrics(repo)
    return {
        "client": client, "site": repo.public_site() if repo.list("sites") else None,
        "health_score": crawl["health_score"] if crawl else None, "last_audit": crawl["finished_at"] if crawl else None,
        "pages_crawled": crawl["pages_crawled"] if crawl else 0, "health_history": history,
        "open_findings": dict(sev_counts), "open_critical_high": sev_counts["critical"] + sev_counts["high"],
        "changes": dict(status_counts), "waiting_on_client": status_counts["awaiting_client"],
        "visibility": vis["latest"], "spend_this_month_usd": round(repo.month_spend(), 4),
        "budget_usd": client["monthly_budget_usd"],
        "alerts": repo.list("alerts", "NOT acknowledged", order="id DESC"),
    }


async def report_html(repo: ClientRepo, writer: Writer) -> str:
    """Monthly client report (FDD FR-11.2). The summary paragraph is drafted by the writer and policy-linted."""
    s = summary(repo)
    vis = visibility_metrics(repo)
    live = repo.list("change_requests", "status = 'live'", order="updated_at DESC")
    waiting = repo.list("change_requests", "status = 'awaiting_client'")
    open_f = sorted(repo.list("findings", "status = 'open'"), key=lambda f: (SEVERITY_ORDER[f["severity"]], -f["impact"]))
    m = {"changes_live": len(live), "health_score": s["health_score"], "open_critical_high": s["open_critical_high"],
         "mention_rate_pct": vis["latest"]["mention_rate"] if vis["latest"] else 0}
    text, usage = await writer.write("report_summary", {"business": {"name": s["client"]["name"]}, "metrics": m}, 700)
    repo.meter(writer.name, "llm_call", 1, usage["cost_usd"])
    if lint(text):
        text = "(Summary withheld: the draft failed the policy check and needs a strategist's rewrite.)"
    e = html.escape
    rows_live = "".join(f"<tr><td>#{c['id']}</td><td>{e(change_label(c))}</td><td>{e(c['target'].get('path') or c['target'].get('source') or '/robots.txt')}</td><td>{e((c['updated_at'] or '')[:10])}</td></tr>" for c in live) or "<tr><td colspan=4>None yet</td></tr>"
    rows_open = "".join(f"<tr><td>{e(f['severity'])}</td><td>{e(f['title'])}</td><td>{e(f['fix_hint'] or '')}</td></tr>" for f in open_f[:12]) or "<tr><td colspan=3>None</td></tr>"
    engines = "".join(f"<tr><td>{e(r['engine'])}</td><td>{r['mention_rate']}%</td></tr>" for r in vis["by_engine"]) or "<tr><td colspan=2>Not sampled yet</td></tr>"
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Monthly report · {e(s['client']['name'])}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:820px;margin:40px auto;padding:0 24px;color:#1b1f23}}
h1{{font-size:26px;margin-bottom:4px}}.muted{{color:#667}}table{{border-collapse:collapse;width:100%;margin:8px 0 24px}}
td,th{{border-bottom:1px solid #e3e6ea;padding:7px 8px;text-align:left;font-size:14px;vertical-align:top}}
.kpis{{display:flex;gap:16px;margin:20px 0}}.kpi{{border:1px solid #e3e6ea;border-radius:10px;padding:12px 16px;flex:1}}
.kpi b{{display:block;font-size:24px}}.note{{background:#fff7e6;border:1px solid #f0d9a8;padding:10px 12px;border-radius:8px;font-size:13px}}</style></head>
<body><h1>Monthly SEO report: {e(s['client']['name'])}</h1><div class="muted">Prepared {e(now()[:10])} for {e(s['site']['base_url'])}</div>
<div class="kpis"><div class="kpi"><b>{s['health_score'] if s['health_score'] is not None else '–'} / 100</b>Site health</div>
<div class="kpi"><b>{len(live)}</b>Changes shipped</div><div class="kpi"><b>{s['open_critical_high']}</b>High-priority items open</div>
<div class="kpi"><b>{m['mention_rate_pct']}%</b>AI answers that mention you</div></div>
<h2>Summary</h2><p>{e(text)}</p>
<h2>Changes made to your site</h2><table><tr><th>Change</th><th>What</th><th>Page</th><th>Date</th></tr>{rows_live}</table>
<h2>Waiting for your approval</h2><p>{_count(len(waiting), "change")} waiting in the portal. Nothing changes on your site until you approve.</p>
<h2>Open issues, most important first</h2><table><tr><th>Severity</th><th>Issue</th><th>Recommended fix</th></tr>{rows_open}</table>
<h2>AI visibility by engine</h2><table><tr><th>Engine</th><th>Mention rate</th></tr>{engines}</table>
<p class="note">AI-visibility figures in this proof of concept come from <b>simulated</b> engines. Rankings and AI answers change over time, and no one can guarantee placement.</p>
</body></html>"""
