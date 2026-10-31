"""Site crawler (FDD FR-5.1). Reads the live site the way a search engine does.

It never needs the client's code: it requests public URLs, records redirect
chains and status codes, and parses each HTML page into structured facts that
the rules engine and the post-deploy verifier use as evidence.
"""
from __future__ import annotations

import asyncio
import json
import re
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from .config import settings
from .net import assert_public_host, make_client

AI_BOTS = ["GPTBot", "OAI-SearchBot", "ClaudeBot", "PerplexityBot", "Google-Extended", "CCBot"]
MAX_REDIRECT_HOPS = 5


@dataclass
class PageFacts:
    url: str
    path: str
    status: int
    final_url: str
    redirect_chain: list[dict[str, Any]] = field(default_factory=list)
    title: str = ""
    meta_description: str = ""
    h1s: list[str] = field(default_factory=list)
    canonical: str = ""
    noindex: bool = False
    word_count: int = 0
    images: list[dict[str, str]] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    jsonld_types: list[str] = field(default_factory=list)
    in_sitemap: bool = False

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["noindex"] = int(self.noindex)
        row["in_sitemap"] = int(self.in_sitemap)
        return row


@dataclass
class CrawlResult:
    base_url: str
    pages: list[PageFacts]
    robots_txt: str
    ai_bots_blocked: list[str]
    sitemap_urls: list[str]


def normalize(url: str) -> str:
    parts = urlparse(url)
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlunparse((parts.scheme, parts.netloc.lower(), path, "", parts.query, ""))


def path_of(url: str) -> str:
    return urlparse(url).path or "/"


def parse_html(html: str, page_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    desc_tag = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    robots_tag = soup.find("meta", attrs={"name": re.compile("^robots$", re.I)})
    canon_tag = soup.find("link", rel=lambda v: v and "canonical" in (v if isinstance(v, list) else [v]))
    jsonld_types: list[str] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
        except json.JSONDecodeError:
            jsonld_types.append("INVALID")
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            t = item.get("@type") if isinstance(item, dict) else None
            jsonld_types.extend(t if isinstance(t, list) else [t] if t else [])
    for s in soup(["script", "style", "noscript"]):
        s.decompose()
    main = soup.find("main") or soup.body or soup
    text = main.get_text(" ", strip=True) if main else ""
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        links.append(normalize(urljoin(page_url, href)))
    return {
        "title": title,
        "meta_description": (desc_tag.get("content") or "").strip() if desc_tag else "",
        "h1s": [h.get_text(strip=True) for h in soup.find_all("h1")],
        "canonical": canon_tag.get("href", "").strip() if canon_tag else "",
        "noindex": bool(robots_tag and "noindex" in (robots_tag.get("content") or "").lower()),
        "word_count": len(text.split()),
        "images": [{"src": i.get("src", ""), "alt": i.get("alt") if i.has_attr("alt") else None} for i in soup.find_all("img")],
        "links": sorted(set(links)),
        "jsonld_types": jsonld_types,
    }


async def fetch_with_redirects(client: httpx.AsyncClient, url: str) -> tuple[httpx.Response | None, list[dict[str, Any]], str]:
    """Follow redirects by hand so the chain can be reported as evidence."""
    chain: list[dict[str, Any]] = []
    current = url
    for _ in range(MAX_REDIRECT_HOPS + 1):
        assert_public_host(current)
        try:
            resp = await client.get(current)
        except httpx.HTTPError as exc:
            chain.append({"url": current, "status": 0, "error": type(exc).__name__})
            return None, chain, current
        if resp.status_code in (301, 302, 303, 307, 308) and "location" in resp.headers:
            nxt = normalize(urljoin(current, resp.headers["location"]))
            chain.append({"url": current, "status": resp.status_code, "to": nxt})
            current = nxt
            continue
        return resp, chain, current
    return None, chain, current


async def fetch_page(client: httpx.AsyncClient, url: str) -> PageFacts:
    resp, chain, final = await fetch_with_redirects(client, url)
    facts = PageFacts(url=url, path=path_of(url), status=resp.status_code if resp is not None else 0,
                      final_url=final, redirect_chain=chain)
    # A redirecting URL is recorded with its chain only; its target is crawled as its own page.
    if not chain and resp is not None and resp.status_code == 200 and "html" in resp.headers.get("content-type", ""):
        for key, val in parse_html(resp.text, final).items():
            setattr(facts, key, val)
    return facts


async def fetch_text(client: httpx.AsyncClient, url: str) -> str:
    assert_public_host(url)
    try:
        resp = await client.get(url)
        return resp.text if resp.status_code == 200 else ""
    except httpx.HTTPError:
        return ""


def blocked_ai_bots(robots_txt: str, base_url: str) -> list[str]:
    parser = RobotFileParser()
    parser.parse(robots_txt.splitlines())
    return [bot for bot in AI_BOTS if not parser.can_fetch(bot, base_url + "/")]


def parse_sitemap(xml_text: str) -> list[str]:
    if not xml_text.strip():
        return []
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []
    return [normalize(el.text.strip()) for el in root.iter() if el.tag.endswith("loc") and el.text]


async def crawl(base_url: str, max_pages: int | None = None, concurrency: int = 4) -> CrawlResult:
    base = base_url.rstrip("/")
    host = urlparse(base).netloc
    limit = max_pages or settings.max_pages
    async with make_client() as client:
        robots_txt = await fetch_text(client, base + "/robots.txt")
        parser = RobotFileParser()
        parser.parse(robots_txt.splitlines())
        sitemap_urls = parse_sitemap(await fetch_text(client, base + "/sitemap.xml"))

        seen: set[str] = set()
        queue: deque[str] = deque([normalize(base + "/")] + sitemap_urls)
        pages: list[PageFacts] = []
        sem = asyncio.Semaphore(concurrency)

        async def worker(url: str) -> PageFacts:
            async with sem:
                return await fetch_page(client, url)

        while queue and len(pages) < limit:
            batch: list[str] = []
            while queue and len(batch) + len(pages) < limit:
                url = queue.popleft()
                if url in seen or urlparse(url).netloc != host:
                    continue
                if not parser.can_fetch(settings.crawl_user_agent, url):
                    continue
                seen.add(url)
                batch.append(url)
            results = await asyncio.gather(*(worker(u) for u in batch))
            for facts in results:
                facts.in_sitemap = facts.url in sitemap_urls
                pages.append(facts)
                follow = facts.links + ([facts.final_url] if facts.redirect_chain else [])
                for link in follow:
                    if link not in seen and urlparse(link).netloc == host:
                        queue.append(link)
        return CrawlResult(base_url=base, pages=pages, robots_txt=robots_txt,
                           ai_bots_blocked=blocked_ai_bots(robots_txt, base), sitemap_urls=sitemap_urls)
