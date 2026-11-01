"""AI-search visibility tracking (FDD M9).

Until the real AI-engine adapters land, this uses SIMULATED engines so it runs offline and costs nothing. They sit
behind the same `AIEngine` interface a real adapter would implement (OpenAI,
Gemini, Perplexity Sonar, Claude with web search, or DataForSEO for Google AI
Overviews). The simulation is deterministic and reacts to real site signals
from the latest crawl (schema, AI-crawler access, descriptions, indexability,
thin pages), so deployed fixes visibly move the numbers on the next run.
Every observation is labelled with its method so reports never pass a
simulation off as real data.
"""
from __future__ import annotations

import hashlib
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Protocol

from .db import ClientRepo, now
from .rules import LOCAL_BUSINESS_TYPES

COST_PER_CALL_USD = 0.004
TEMPLATES = [
    ("Best {service} company in {city}", "commercial"),
    ("Who is a reliable {service} company near {city}, {region}?", "local"),
    ("How much does {service} cost in {city}?", "informational"),
]
SOURCES = ["yelp.com", "bbb.org", "reddit.com/r/Austin", "angi.com", "nextdoor.com", "homeadvisor.com"]


@dataclass
class SiteSignals:
    schema: bool
    meta_coverage: float
    contact_indexable: bool
    thin_ratio: float
    blocked_bots: list[str]


@dataclass
class Observation:
    mentioned: bool
    position: int | None
    cited_url: str | None
    brands: list[str]
    sources: list[str]
    answer: str


class AIEngine(Protocol):
    name: str
    method: str

    def ask(self, prompt: str, client: dict[str, Any], site_url: str, signals: SiteSignals, seed: str) -> Observation: ...


class SimulatedEngine:
    method = "simulated"

    def __init__(self, name: str, bot: str | None, base: float) -> None:
        self.name, self.bot, self.base = name, bot, base

    def ask(self, prompt: str, client: dict[str, Any], site_url: str, signals: SiteSignals, seed: str) -> Observation:
        rng = random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:16], 16))
        p = (self.base + 0.22 * signals.schema + 0.15 * signals.meta_coverage + 0.10 * signals.contact_indexable
             + 0.10 * (1 - signals.thin_ratio))
        blocked = bool(self.bot and self.bot in signals.blocked_bots)
        if blocked:
            p *= 0.35
        brands: list[str] = []
        if rng.random() < min(p, 0.95):
            brands.append(client["name"])
        for i, comp in enumerate(client.get("competitors") or []):
            if rng.random() < max(0.2, 0.6 - 0.12 * i):
                brands.append(comp)
        rng.shuffle(brands)
        mentioned = client["name"] in brands
        position = brands.index(client["name"]) + 1 if mentioned else None
        sources = rng.sample(SOURCES, k=3)
        cited = site_url if mentioned and not blocked and rng.random() < 0.6 else None
        if cited:
            sources.insert(0, cited)
        listed = ", ".join(brands) or "none"
        answer = f"Simulated {self.name} answer. Companies named: {listed}. Sources cited: {', '.join(sources)}."
        return Observation(mentioned, position, cited, brands, sources, answer)


ENGINES: list[AIEngine] = [
    SimulatedEngine("ChatGPT", "GPTBot", 0.10),
    SimulatedEngine("Gemini", None, 0.14),
    SimulatedEngine("Perplexity", "PerplexityBot", 0.12),
    SimulatedEngine("Google AI Overviews", None, 0.16),
]


def ensure_prompts(repo: ClientRepo) -> list[dict[str, Any]]:
    existing = repo.list("prompts")
    if existing:
        return existing
    client = repo.client()
    for service in (client.get("services") or ["services"])[:4]:
        for template, cluster in TEMPLATES:
            text = template.format(service=service, city=client.get("city") or "", region=client.get("region") or "")
            repo.insert("prompts", {"text": text, "cluster": cluster, "created_at": now()})
    return repo.list("prompts")


def site_signals(repo: ClientRepo) -> SiteSignals:
    crawl = repo.latest_crawl()
    if not crawl:
        return SiteSignals(False, 0.0, False, 1.0, [])
    pages = [p for p in repo.list("pages", "crawl_id = ?", (crawl["id"],)) if p["status"] == 200 and not p["redirect_chain"]]
    indexable = [p for p in pages if not p["noindex"]]
    home = next((p for p in pages if p["path"] == "/"), None)
    contact = next((p for p in pages if p["path"] == "/contact"), None)
    return SiteSignals(
        schema=bool(home and set(home["jsonld_types"]) & LOCAL_BUSINESS_TYPES),
        meta_coverage=sum(1 for p in indexable if p["meta_description"]) / max(1, len(indexable)),
        contact_indexable=bool(contact and not contact["noindex"]),
        thin_ratio=sum(1 for p in indexable if p["word_count"] < 200) / max(1, len(indexable)),
        blocked_bots=list(crawl["ai_bots_blocked"] or []),
    )


def run_sample(repo: ClientRepo, actor: str = "system") -> dict[str, Any]:
    prompts = ensure_prompts(repo)
    client = repo.client()
    site_url = repo.site()["base_url"].rstrip("/") + "/"
    signals = site_signals(repo)
    last = repo.list("ai_observations", order="run_no DESC")
    run_no = (last[0]["run_no"] + 1) if last else 1
    for prompt in prompts:
        for engine in ENGINES:
            obs = engine.ask(prompt["text"], client, site_url, signals, f"{repo.client_id}|{prompt['id']}|{engine.name}|{run_no}")
            repo.insert("ai_observations", {
                "prompt_id": prompt["id"], "run_no": run_no, "engine": engine.name, "method": engine.method,
                "run_at": now(), "mentioned": int(obs.mentioned), "position": obs.position, "cited_url": obs.cited_url,
                "brands": obs.brands, "sources": obs.sources, "answer": obs.answer,
            })
    calls = len(prompts) * len(ENGINES)
    repo.meter("AI engine answers (simulated)", "answer", calls, calls * COST_PER_CALL_USD)
    repo.log(actor, "visibility.sampled", f"run:{run_no}", {"prompts": len(prompts), "engines": len(ENGINES)})
    return metrics(repo)


def metrics(repo: ClientRepo) -> dict[str, Any]:
    client = repo.client()
    obs = repo.list("ai_observations")
    if not obs:
        return {"runs": [], "latest": None, "by_engine": [], "share_of_voice": [], "opportunities": [], "method": "simulated"}
    prompts = {p["id"]: p for p in repo.list("prompts")}
    by_run: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for o in obs:
        by_run[o["run_no"]].append(o)
    runs = [{"run_no": r, "run_at": rows[0]["run_at"], "mention_rate": round(100 * sum(o["mentioned"] for o in rows) / len(rows), 1),
             "citation_rate": round(100 * sum(1 for o in rows if o["cited_url"]) / len(rows), 1)}
            for r, rows in sorted(by_run.items())]
    latest_no = max(by_run)
    latest = by_run[latest_no]
    engines = sorted({o["engine"] for o in latest})
    by_engine = [{"engine": e, "mention_rate": round(100 * sum(o["mentioned"] for o in latest if o["engine"] == e)
                                                       / max(1, sum(1 for o in latest if o["engine"] == e)), 1)} for e in engines]
    brand_counts = Counter(b for o in latest for b in o["brands"])
    total = sum(brand_counts.values()) or 1
    sov = [{"brand": b, "share": round(100 * c / total, 1), "is_client": b == client["name"]} for b, c in brand_counts.most_common()]
    opp: dict[int, dict[str, Any]] = {}
    for o in latest:
        if not o["mentioned"] and any(b != client["name"] for b in o["brands"]):
            entry = opp.setdefault(o["prompt_id"], {"prompt": prompts[o["prompt_id"]]["text"], "engines": [], "competitors": set(), "sources": Counter()})
            entry["engines"].append(o["engine"])
            entry["competitors"].update(b for b in o["brands"] if b != client["name"])
            entry["sources"].update(s for s in o["sources"] if "://" not in s)
    opportunities = sorted(
        ({"prompt": v["prompt"], "engines": v["engines"], "competitors": sorted(v["competitors"]),
          "top_sources": [s for s, _ in v["sources"].most_common(3)]} for v in opp.values()),
        key=lambda x: -len(x["engines"]))
    return {"runs": runs, "latest": runs[-1], "by_engine": by_engine, "share_of_voice": sov,
            "opportunities": opportunities[:10], "method": "simulated", "prompt_count": len(prompts)}
