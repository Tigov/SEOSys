"""Rules engine (FDD FR-5.1, FR-5.4): turns crawl facts into findings with evidence.

Findings are produced only from observed data. An LLM may later explain or
prioritize them, but never invents one (TDD section 7, "evidence before narrative").
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

SEVERITY_WEIGHT = {"critical": 15, "high": 8, "medium": 4, "low": 2}
LOCAL_BUSINESS_TYPES = {"LocalBusiness", "HVACBusiness", "HomeAndConstructionBusiness", "Plumber", "Electrician"}
TITLE_MAX = 60
THIN_WORDS = 150


def page_name(path: str) -> str:
    return "the homepage" if path == "/" else path


def _finding(rule_id: str, severity: str, title: str, key: str, urls: list[str], evidence: dict[str, Any],
             effort: str, impact: int, fix_hint: str, fix_type: str | None) -> dict[str, Any]:
    return {"rule_id": rule_id, "severity": severity, "title": title, "fingerprint": f"{rule_id}|{key}",
            "urls": urls, "evidence": evidence, "effort": effort, "impact": impact, "fix_hint": fix_hint,
            "fix_type": fix_type}


def run_rules(pages: list[dict[str, Any]], ai_bots_blocked: list[str], sitemap_urls: list[str]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    inlinks: dict[str, set[str]] = defaultdict(set)
    for p in pages:
        for link in p["links"]:
            inlinks[link].add(p["path"])

    html_pages = [p for p in pages if p["status"] == 200 and not p["redirect_chain"]]
    indexable = [p for p in html_pages if not p["noindex"]]

    for p in pages:
        if p["status"] >= 400 or p["status"] == 0:
            sources = sorted(inlinks.get(p["url"], set()))
            findings.append(_finding(
                "broken_link", "high", f"Broken link to {page_name(p['path'])} (HTTP {p['status']})", p["path"], [p["url"]],
                {"status": p["status"], "linked_from": sources}, "S", 3,
                "Redirect the broken URL to the closest working page, or fix the links pointing to it.", "redirect"))
        if len(p["redirect_chain"]) >= 2:
            hops = [h["url"] for h in p["redirect_chain"]] + [p["final_url"]]
            findings.append(_finding(
                "redirect_chain", "medium", f"{len(p['redirect_chain'])} redirects in a row from {page_name(p['path'])}",
                p["path"], [p["url"]], {"hops": hops}, "S", 2,
                "Point the first redirect straight at the final URL.", "redirect"))

    for p in html_pages:
        if p["noindex"] and (p["in_sitemap"] or len(inlinks.get(p["url"], ())) >= 2):
            findings.append(_finding(
                "noindex_important", "critical", f"Important page {page_name(p['path'])} is hidden from Google",
                p["path"], [p["url"]], {"in_sitemap": bool(p["in_sitemap"]), "internal_links_in": len(inlinks.get(p["url"], ()))},
                "S", 5, "Remove the noindex directive so the page can appear in search.", "noindex"))

    for p in indexable:
        if not p["title"]:
            findings.append(_finding("missing_title", "high", f"Missing title on {page_name(p['path'])}", p["path"], [p["url"]],
                                     {"title": ""}, "S", 4, "Write a unique, descriptive title under 60 characters.", "title"))
        elif len(p["title"]) > TITLE_MAX:
            findings.append(_finding("title_too_long", "low", f"Title too long on {page_name(p['path'])} ({len(p['title'])} characters)",
                                     p["path"], [p["url"]], {"title": p["title"], "length": len(p["title"])}, "S", 2,
                                     "Shorten the title to under 60 characters so it is not cut off.", "title"))
        if not p["meta_description"]:
            findings.append(_finding("missing_meta_description", "medium", f"Missing meta description on {page_name(p['path'])}",
                                     p["path"], [p["url"]], {"meta_description": ""}, "S", 3,
                                     "Add a 120–155 character description that sells the click.", "meta_description"))
        if not p["h1s"]:
            findings.append(_finding("missing_h1", "medium", f"Missing H1 heading on {page_name(p['path'])}", p["path"], [p["url"]],
                                     {"h1_count": 0}, "S", 2, "Add one H1 that states what the page is about.", "h1"))
        elif len(p["h1s"]) > 1:
            findings.append(_finding("multiple_h1", "low", f"{len(p['h1s'])} H1 headings on {p['path']}", p["path"],
                                     [p["url"]], {"h1s": p["h1s"]}, "S", 1, "Keep a single H1.", None))
        for img in p["images"]:
            if not img.get("alt"):
                findings.append(_finding("img_missing_alt", "low", f"Image without alt text on {page_name(p['path'])}",
                                         f"{p['path']}|{img['src']}", [p["url"]], {"image_src": img["src"]}, "S", 1,
                                         "Describe the image in a short alt attribute.", "image_alt"))
        if not p["canonical"]:
            findings.append(_finding("missing_canonical", "low", f"No canonical tag on {page_name(p['path'])}", p["path"], [p["url"]],
                                     {"canonical": ""}, "S", 1, "Add a self-referencing canonical tag.", "canonical"))
        if p["word_count"] < THIN_WORDS:
            findings.append(_finding("thin_content", "medium", f"Thin content on {page_name(p['path'])} ({p['word_count']} words)",
                                     p["path"], [p["url"]], {"word_count": p["word_count"], "threshold": THIN_WORDS}, "M", 3,
                                     "Expand with genuinely useful, expert-reviewed content (content workflow).", None))
        if not p["in_sitemap"] and sitemap_urls:
            findings.append(_finding("not_in_sitemap", "low", f"{page_name(p['path'])[0].upper() + page_name(p['path'])[1:]} is missing from the XML sitemap", p["path"],
                                     [p["url"]], {"sitemap_url_count": len(sitemap_urls)}, "S", 2,
                                     "Add the page to the sitemap so search engines find it.", "in_sitemap"))

    by_title: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in indexable:
        if p["title"]:
            by_title[p["title"]].append(p)
    for title, group in by_title.items():
        if len(group) > 1:
            findings.append(_finding("duplicate_title", "medium", f"{len(group)} pages share the title “{title}”",
                                     title, [g["url"] for g in group], {"title": title, "paths": [g["path"] for g in group]},
                                     "S", 3, "Give each page a unique title that matches its topic.", "title"))

    home = next((p for p in html_pages if p["path"] == "/"), None)
    if home and not (set(home["jsonld_types"]) & LOCAL_BUSINESS_TYPES):
        findings.append(_finding("missing_local_business_schema", "high", "Homepage has no LocalBusiness structured data",
                                 "/", [home["url"]], {"jsonld_types": home["jsonld_types"]}, "S", 4,
                                 "Add LocalBusiness (HVACBusiness) JSON-LD with name, address, phone and service area.",
                                 "schema_jsonld"))

    if ai_bots_blocked:
        findings.append(_finding("ai_crawlers_blocked", "high", f"robots.txt blocks AI crawlers: {', '.join(ai_bots_blocked)}",
                                 "robots", [], {"blocked": ai_bots_blocked}, "S", 4,
                                 "Allow AI search crawlers so assistants can read and cite the site.", "robots_txt"))
    if not sitemap_urls:
        findings.append(_finding("missing_sitemap", "medium", "No XML sitemap found", "sitemap", [], {}, "S", 2,
                                 "Publish an XML sitemap and reference it in robots.txt.", None))
    return findings


def health_score(findings: list[dict[str, Any]]) -> int:
    penalty = 0
    per_rule: dict[str, int] = defaultdict(int)
    for f in findings:
        # Cap each rule's contribution so one repeated low issue cannot dominate the score.
        w = SEVERITY_WEIGHT[f["severity"]]
        if per_rule[f["rule_id"]] < 3 * w:
            per_rule[f["rule_id"]] += w
            penalty += w
    return max(0, 100 - penalty)
