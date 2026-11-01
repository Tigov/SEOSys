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
    summary: str
    includes: tuple[str, ...]

    @property
    def price_id(self) -> str:
        return os.environ.get(self.price_env, "").strip()

    def public(self) -> dict[str, object]:
        return {"id": self.id, "name": self.name, "mode": self.mode, "price_label": self.price_label,
                "summary": self.summary, "includes": list(self.includes), "available": bool(self.price_id)}


PLANS: dict[str, Plan] = {p.id: p for p in (
    Plan("audit", "Audit and roadmap", "STRIPE_PRICE_AUDIT", "payment", "$1,500 one-off",
         "A full check of your website and a 90-day plan, so you know exactly what to fix first.",
         ("Full technical and content audit", "Keyword and competitor gaps", "How often AI assistants mention you",
          "A 90-day roadmap in plain English")),
    Plan("local", "Local", "STRIPE_PRICE_LOCAL", "subscription", "$750 a month",
         "For businesses that win customers nearby: show up on maps, in local searches and in AI answers.",
         ("Google Business Profile care", "Local listings and reviews", "Location pages", "AI answer monitoring",
          "Monthly report")),
    Plan("growth", "Growth", "STRIPE_PRICE_GROWTH", "subscription", "$2,500 a month",
         "We fix your website for you every month and grow the searches you're found for.",
         ("Technical fixes made for you, with your approval", "Content refreshes", "Keyword strategy",
          "AI visibility", "Quarterly review")),
)}
