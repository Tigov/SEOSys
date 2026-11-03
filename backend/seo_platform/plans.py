"""The packages people can buy. Prices are charged by Stripe from the price IDs in the environment; the labels here
must match what is set in the Stripe dashboard (see notes: Business and Offer)."""
from __future__ import annotations

import os
from dataclasses import dataclass


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
    Plan("audit", "SEO Audit", "STRIPE_PRICE_AUDIT", "payment", "$1,500 one-off", 150000,
         "A full check of your website and a 90-day plan, so you know exactly what to fix first.",
         ("Every page checked for technical problems", "Page speed on phones and computers",
          "A check that AI assistants like ChatGPT can read your website",
          "Your Google Search Console and Analytics data reviewed", "A 90-day plan in plain English, most important first")),
    Plan("technical", "Technical SEO", "STRIPE_PRICE_TECHNICAL", "subscription", "$750 a month", 75000,
         "We check your website every month and fix what's holding it back in Google, with your approval.",
         ("A full check of every page, every month", "Fixes prepared for you and explained in plain English",
          "Fixes made on WordPress sites once you approve them, and undone if anything goes wrong",
          "Step-by-step fixes for other website builders", "AI assistants like ChatGPT kept able to read your website",
          "Google Search Console and Analytics in one report",
          "A monthly report on visitors, searches and enquiries")),
    Plan("local", "Local SEO", "STRIPE_PRICE_LOCAL", "subscription", "$1,000 a month", 100000,
         "Everything in Technical SEO, plus help showing up on Google Maps and in \"near me\" searches.",
         ("Everything in Technical SEO", "Google Business Profile kept up to date", "Review monitoring and replies",
          "Your name, address and phone the same on every directory", "Pages for each area you serve"),
         coming_soon=True),
)}

# Packages we no longer sell, mapped to what their clients now see.
RETIRED = {"growth": "technical"}


def plan_for(plan_id: str | None) -> Plan | None:
    """The package a stored plan id refers to, including retired ones."""
    plan_id = plan_id or ""
    return PLANS.get(RETIRED.get(plan_id, plan_id))
