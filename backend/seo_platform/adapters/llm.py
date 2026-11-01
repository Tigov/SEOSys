"""LLM port and adapters (TDD section 7).

`OfflineWriter` is deterministic and needs no API key, so the platform
runs anywhere. `AnthropicWriter` is used when ANTHROPIC_API_KEY is set; any API
error falls back to the offline writer so a vendor outage never blocks work.
All outputs are drafts that a human reviews before anything reaches a site.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Protocol

import httpx

from ..config import settings
from ..net import make_client

log = logging.getLogger(__name__)

# Rough per-million-token prices used only for metering estimates.
EST_INPUT_USD_PER_M = 1.0
EST_OUTPUT_USD_PER_M = 5.0


class Writer(Protocol):
    name: str

    async def write(self, task: str, context: dict[str, Any], max_chars: int) -> tuple[str, dict[str, float]]:
        """Return (text, usage) where usage has input_tokens, output_tokens, cost_usd."""
        ...


def _trim(text: str, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", text).strip().strip('"')
    if len(text) <= max_chars:
        return text
    cut = text[: max_chars - 1].rsplit(" ", 1)[0].rstrip(",;:-–")
    return cut + "…" if not cut.endswith(".") else cut


def _humanize_filename(src: str) -> str:
    stem = src.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return re.sub(r"[-_]+", " ", stem).strip()


class OfflineWriter:
    name = "Text writer (offline templates)"

    async def write(self, task: str, context: dict[str, Any], max_chars: int) -> tuple[str, dict[str, float]]:
        biz = context.get("business", {})
        name, city = biz.get("name", "Our team"), biz.get("city", "your area")
        topic = context.get("h1") or context.get("title") or context.get("path", "").strip("/").replace("-", " ").title()
        if task == "title":
            short = name.replace(" HVAC", "")
            text = f"{topic} | {short}"
            if len(text) > max_chars:
                text = topic
        elif task == "meta_description":
            phone = biz.get("phone", "")
            text = f"{topic} from {name}. Licensed technicians serving {city} with upfront pricing."
            if phone and len(text) + len(phone) + 7 <= max_chars:
                text += f" Call {phone}."
        elif task == "h1":
            text = context.get("title", "").split("|")[0].strip() or topic
        elif task == "alt":
            text = f"{name} {_humanize_filename(context.get('image_src', ''))}".strip()
        elif task == "report_summary":
            m = context["metrics"]
            text = (f"This month we made {m['changes_live']} approved changes to the site, and its health score is now "
                    f"{m['health_score']} out of 100. {m['open_critical_high']} high-priority items remain open. "
                    f"In the latest sample of AI answers, the business was mentioned {m['mention_rate_pct']}% of the time. "
                    "Next month we will finish the remaining high-priority fixes and start improving the thinnest pages.")
        else:
            text = topic
        return _trim(text, max_chars), {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}


PROMPTS = {
    "title": "Write one SEO page title (max {max_chars} characters) for this page. Plain text only.",
    "meta_description": "Write one meta description (120-{max_chars} characters) for this page. Plain text only, no quotes.",
    "h1": "Write one H1 heading (max {max_chars} characters) for this page. Plain text only.",
    "alt": "Write concise alt text (max {max_chars} characters) for the image {image_src} on this page. Plain text only.",
    "report_summary": "Write a 3-4 sentence plain-English monthly summary for the business owner from these metrics: {metrics}",
}
SYSTEM = ("You write SEO copy for a small business. Use only facts in the provided context. Never promise rankings, "
          "never use the words guarantee or #1, and never invent prices, awards or statistics.")


class AnthropicWriter:
    name = "Claude API (text drafts)"

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model
        self.fallback = OfflineWriter()

    async def write(self, task: str, context: dict[str, Any], max_chars: int) -> tuple[str, dict[str, float]]:
        instruction = PROMPTS.get(task, "Write a short text.").format(max_chars=max_chars, **{k: context.get(k, "") for k in ("image_src", "metrics")})
        page_ctx = {k: context.get(k) for k in ("path", "title", "h1", "excerpt") if context.get(k)}
        user = f"{instruction}\n\nBusiness: {context.get('business')}\nPage: {page_ctx}"
        try:
            async with make_client(timeout=30) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    json={"model": self.model, "max_tokens": 300, "system": SYSTEM,
                          "messages": [{"role": "user", "content": user}]},
                )
            resp.raise_for_status()
            data = resp.json()
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            usage = data.get("usage", {})
            it, ot = float(usage.get("input_tokens", 0)), float(usage.get("output_tokens", 0))
            cost = it / 1e6 * EST_INPUT_USD_PER_M + ot / 1e6 * EST_OUTPUT_USD_PER_M
            return _trim(text, max_chars), {"input_tokens": it, "output_tokens": ot, "cost_usd": cost}
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            log.warning("LLM call failed, using offline writer: %s", exc)
            return await self.fallback.write(task, context, max_chars)


def get_writer() -> Writer:
    if settings.anthropic_api_key:
        return AnthropicWriter(settings.anthropic_api_key, settings.llm_model)
    return OfflineWriter()
