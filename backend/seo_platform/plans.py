"""The packages people can buy. Prices are charged by Stripe from the price IDs in the environment; the labels here
must match what is set in the Stripe dashboard (see notes: Business and Offer)."""
from __future__ import annotations

import os
from dataclasses import dataclass

from .rules import AREAS, area_of

ALL_AREAS = frozenset(AREAS)


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    price_env: str
    mode: str  # "subscription" (monthly) or "payment" (one-off)
    price_label: str
    amount_cents: int  # used only to create test prices (python -m seo_platform stripe-setup)
    summary: str
    includes: tuple[str, ...]
    covers: frozenset[str]  # the areas of work (rules.AREAS) whose fixes this package makes
    coming_soon: bool = False  # shown on the website, but can't be bought yet

    @property
    def price_id(self) -> str:
        return os.environ.get(self.price_env, "").strip()

    @property
    def available(self) -> bool:
        return bool(self.price_id) and not self.coming_soon

    def public(self) -> dict[str, object]:
        return {"id": self.id, "name": self.name, "mode": self.mode, "price_label": self.price_label,
                "summary": self.summary, "includes": list(self.includes), "available": self.available,
                "coming_soon": self.coming_soon}


PLANS: dict[str, Plan] = {p.id: p for p in (
    Plan("technical", "Technical SEO", "STRIPE_PRICE_TECHNICAL", "subscription", "$1,000 a month", 100000,
         "We keep your website fast, error-free and easy for Google and AI assistants to read.",
         ("Every page checked each month", "Broken links and redirect chains fixed",
          "Pages hidden from Google by mistake made visible again", "Your sitemap kept complete, so Google finds every page",
          "AI assistants like ChatGPT able to read your website",
          "Your business details added in the format Google reads", "A monthly report on your Google visitors and searches"),
         frozenset({"technical", "ai_local"})),
    Plan("onpage", "On-Page SEO", "STRIPE_PRICE_ONPAGE", "subscription", "$1,000 a month", 100000,
         "We improve what's on each page so Google knows what you offer and people click through.",
         ("Page titles and search result descriptions written for you", "A clear main heading on every page",
          "Image descriptions for Google and screen readers", "Pages with too little content flagged, with what to add",
          "Every page checked each month", "A monthly report on your Google visitors and searches"),
         frozenset({"onpage"})),
    Plan("local", "Local SEO", "STRIPE_PRICE_LOCAL", "subscription", "$1,000 a month", 100000,
         "Help showing up on Google Maps and in \"near me\" searches.",
         ("Your Google Business Profile kept complete and up to date",
          "New reviews tracked, with replies drafted for you to approve",
          "Your business listed correctly on Apple Maps, Bing, Yelp and other directories",
          "A page for each town or area you serve", "A monthly report on your Google Maps views and clicks"),
         frozenset({"ai_local"}), coming_soon=True),
    Plan("complete", "Complete SEO", "STRIPE_PRICE_COMPLETE", "subscription", "$2,300 a month", 230000,
         "Everything we do, in one package: Technical SEO and On-Page SEO, with Local SEO added when it launches.",
         ("Everything in Technical SEO", "Everything in On-Page SEO", "Local SEO included when it launches",
          "A quarterly review of what's working and what's next"),
         ALL_AREAS),
    Plan("audit", "SEO Audit", "STRIPE_PRICE_AUDIT", "payment", "$1,500 one-off", 150000,
         "We check your whole website once and tell you exactly what to fix, so you or your web person can do it.",
         ("Every page checked for technical and on-page problems", "Page speed on phones and computers",
          "A check that AI assistants like ChatGPT can read your website",
          "Your Google Search Console and Analytics data reviewed",
          "Every issue listed, most important first, with how to fix it"),
         frozenset()),
    Plan("fixup", "SEO Fix-Up", "STRIPE_PRICE_FIXUP", "payment", "$2,500 one-off", 250000,
         "We check your whole website and fix what we find, once. No monthly commitment.",
         ("Everything in the SEO Audit", "Technical and on-page fixes made for you, with your approval",
          "Fixes made on WordPress sites, step-by-step instructions for other builders",
          "Your website checked again afterwards, so you see the difference"),
         ALL_AREAS),
)}

# Packages we no longer sell, mapped to what their clients now see.
RETIRED = {"growth": "technical"}


def plan_for(plan_id: str | None) -> Plan | None:
    """The package a stored plan id refers to, including retired ones."""
    plan_id = plan_id or ""
    return PLANS.get(RETIRED.get(plan_id, plan_id))


def plan_covers(plan_id: str | None, rule_id: str) -> bool:
    """Whether a client's package includes fixing this kind of problem. Clients without a package were set up by
    the agency directly, so they get everything."""
    plan = plan_for(plan_id)
    return plan is None or area_of(rule_id) in plan.covers


def recommend(areas_with_issues: set[str]) -> str:
    """The cheapest monthly package on sale that fixes every area where problems were found."""
    on_sale = [p for p in PLANS.values() if p.mode == "subscription" and not p.coming_soon]
    fits = [p for p in on_sale if areas_with_issues <= p.covers] or [PLANS["complete"]]
    return min(fits, key=lambda p: p.amount_cents).id
