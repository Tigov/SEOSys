"""Buying a package with Stripe Checkout, managing it in Stripe's billing portal, and keeping account status in step
with Stripe's webhooks.

Webhooks are verified with STRIPE_WEBHOOK_SECRET and each event is handled once: its id is recorded in the same
transaction as its effects, so a duplicate delivery (even a simultaneous one) does nothing.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Protocol

import stripe

from . import clock, mailer
from .config import settings
from .db import Database
from .permissions import Access
from .plans import PLANS

log = logging.getLogger("seo_platform.billing")


class BillingError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class Gateway(Protocol):
    def checkout(self, params: dict[str, Any]) -> str: ...
    def portal(self, customer_id: str, return_url: str) -> str: ...


class StripeGateway:
    def _client(self) -> stripe.StripeClient:
        if not settings.stripe_secret_key:
            raise BillingError("Payments aren't set up on this server yet. Add STRIPE_SECRET_KEY to the .env file.", 503)
        return stripe.StripeClient(settings.stripe_secret_key)

    def checkout(self, params: dict[str, Any]) -> str:
        return self._client().v1.checkout.sessions.create(params=params).url  # type: ignore[arg-type,return-value]

    def portal(self, customer_id: str, return_url: str) -> str:
        session = self._client().v1.billing_portal.sessions.create(
            params={"customer": customer_id, "return_url": return_url})
        return session.url


gateway: Gateway = StripeGateway()

CLIENT_STATUS = {"active": "active", "trialing": "active", "past_due": "past_due", "unpaid": "past_due",
                 "incomplete": "past_due", "canceled": "cancelled", "incomplete_expired": "cancelled"}


# ---------- buying and managing ----------

def start_checkout(db: Database, a: Access, plan_id: str, business_name: str) -> str:
    plan = PLANS.get(plan_id)
    if plan is None:
        raise BillingError("That package doesn't exist.", 404)
    if not plan.price_id:
        raise BillingError(f"The {plan.name} package can't be bought online yet. Contact us to get started.", 503)
    name = business_name.strip()[:200]
    if len(name) < 2:
        raise BillingError("Enter your business name.")
    assert a.principal is not None
    meta = {"user_id": str(a.principal.user_id), "plan": plan.id, "business_name": name}
    params: dict[str, Any] = {
        "mode": plan.mode, "line_items": [{"price": plan.price_id, "quantity": 1}],
        "customer_email": a.principal.email, "client_reference_id": str(a.principal.user_id), "metadata": meta,
        "success_url": f"{settings.app_base_url}/?checkout=done#/welcome",
        "cancel_url": f"{settings.app_base_url}/?checkout=cancelled#/packages",
    }
    if plan.mode == "subscription":
        params["subscription_data"] = {"metadata": meta}
    else:
        params["customer_creation"] = "always"
    url = gateway.checkout(params)
    db.log(None, a.actor, "billing.checkout_started", f"user:{a.principal.user_id}", {"plan": plan.id},
           actor_user_id=a.principal.user_id)
    return url


def portal_url(db: Database, a: Access) -> str:
    customer = (a.client or {}).get("stripe_customer_id")
    if not customer:
        raise BillingError("This account isn't billed through the website. Contact us about billing.", 409)
    return gateway.portal(customer, f"{settings.app_base_url}/#/clients/{a.client_id}/billing")


def summary(db: Database, client_id: int) -> dict[str, Any]:
    client = db.get_client(client_id) or {}
    sub = db.one("SELECT plan, status, current_period_end, cancel_at FROM subscriptions WHERE client_id = ?", (client_id,))
    plan = PLANS.get(client.get("plan") or "")
    return {"plan": plan.public() if plan else None, "status": client.get("status"), "subscription": sub,
            "billed_online": bool(client.get("stripe_customer_id"))}


# ---------- webhooks ----------

def parse_event(payload: bytes, signature: str | None) -> dict[str, Any]:
    if not settings.stripe_webhook_secret:
        raise BillingError("Webhooks aren't set up on this server.", 503)
    try:
        stripe.Webhook.construct_event(payload, signature, settings.stripe_webhook_secret)
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise BillingError("Invalid webhook signature.") from exc
    return json.loads(payload)


def _ts(value: Any) -> datetime | None:
    return datetime.fromtimestamp(int(value), timezone.utc) if value else None


def handle_event(db: Database, event: dict[str, Any]) -> str:
    """Apply one Stripe event. Returns what happened, for logs and tests."""
    with db.transaction():
        first = db.one("INSERT INTO stripe_events (id, type, received_at) VALUES (?, ?, ?) "
                       "ON CONFLICT (id) DO NOTHING RETURNING id", (event["id"], event["type"], clock.now()))
        if first is None:
            return "duplicate"
        obj = event["data"]["object"]
        handler = HANDLERS.get(event["type"])
        return handler(db, obj) if handler else "ignored"


def _checkout_completed(db: Database, obj: dict[str, Any]) -> str:
    meta = obj.get("metadata") or {}
    user_id = int(meta.get("user_id") or obj.get("client_reference_id") or 0)
    plan = PLANS.get(meta.get("plan", ""))
    user = db.one("SELECT * FROM users WHERE id = ?", (user_id,))
    customer = obj.get("customer")
    if user is None or plan is None or not customer:
        log.error("checkout %s is missing its user, plan or customer", obj.get("id"))
        return "invalid"
    if db.one("SELECT id FROM clients WHERE stripe_customer_id = ?", (customer,)):
        return "already_created"
    client_id = db.create_client(name=meta.get("business_name") or user["name"], plan=plan.id, status="active",
                                 stripe_customer_id=customer, monthly_budget_usd=settings.default_monthly_budget_usd)
    db.insert("memberships", {"user_id": user_id, "client_id": client_id, "role": "owner"})
    if obj.get("subscription"):
        db.insert("subscriptions", {"client_id": client_id, "stripe_subscription_id": obj["subscription"],
                                    "plan": plan.id, "status": "active", "updated_at": clock.now()})
    mailer.queue(db, user["email"], "welcome", name=user["name"], plan=plan.name, client=meta.get("business_name") or "",
                 url=f"{settings.app_base_url}/#/clients/{client_id}")
    db.log(client_id, "stripe", "billing.purchased", f"client:{client_id}", {"plan": plan.id}, actor_user_id=user_id)
    return "client_created"


def _client_for_customer(db: Database, customer: str | None) -> dict[str, Any] | None:
    return db.one("SELECT * FROM clients WHERE stripe_customer_id = ?", (customer,)) if customer else None


def _subscription_changed(db: Database, obj: dict[str, Any]) -> str:
    client = _client_for_customer(db, obj.get("customer"))
    if client is None:
        return "unknown_customer"
    status = CLIENT_STATUS.get(obj.get("status", ""), client["status"])
    items = (obj.get("items") or {}).get("data") or [{}]  # newer API versions keep the period on each item
    period_end = obj.get("current_period_end") or items[0].get("current_period_end")
    db.execute("UPDATE subscriptions SET status = ?, current_period_end = ?, cancel_at = ?, updated_at = ? "
               "WHERE stripe_subscription_id = ?",
               (obj.get("status"), _ts(period_end), _ts(obj.get("cancel_at")), clock.now(), obj["id"]))
    _set_status(db, client, status)
    return f"status:{status}"


def _set_status(db: Database, client: dict[str, Any], status: str) -> None:
    if client["status"] == status or client["status"] == "closed":
        return
    db.execute("UPDATE clients SET status = ?, cancelled_at = ? WHERE id = ?",
               (status, clock.now() if status == "cancelled" else None, client["id"]))
    db.log(client["id"], "stripe", "billing.status_changed", f"client:{client['id']}",
           {"from": client["status"], "to": status})


def _payment_failed(db: Database, obj: dict[str, Any]) -> str:
    client = _client_for_customer(db, obj.get("customer"))
    if client is None:
        return "unknown_customer"
    if client["status"] == "active":
        _set_status(db, client, "past_due")
    owner = db.one("SELECT u.email, u.name FROM memberships m JOIN users u ON u.id = m.user_id "
                   "WHERE m.client_id = ? AND m.role = 'owner'", (client["id"],))
    if owner:
        mailer.queue(db, owner["email"], "payment_failed", name=owner["name"], client=client["name"],
                     url=f"{settings.app_base_url}/#/clients/{client['id']}/billing")
    return "past_due"


def _paid(db: Database, obj: dict[str, Any]) -> str:
    client = _client_for_customer(db, obj.get("customer"))
    if client is None:
        return "unknown_customer"
    if client["status"] == "past_due":
        _set_status(db, client, "active")
    return "paid"


HANDLERS = {
    "checkout.session.completed": _checkout_completed,
    "customer.subscription.updated": _subscription_changed,
    "customer.subscription.deleted": _subscription_changed,
    "invoice.payment_failed": _payment_failed,
    "invoice.paid": _paid,
}


def activate_manually(db: Database, a: Access, client_id: int) -> None:
    """For clients who pay by invoice or bank transfer."""
    client = db.get_client(client_id)
    if client is None:
        raise LookupError(f"Client {client_id} was not found.")
    db.execute("UPDATE clients SET status = 'active', cancelled_at = NULL WHERE id = ?", (client_id,))
    db.log(client_id, a.actor, "billing.activated_manually", f"client:{client_id}", {"from": client["status"]},
           actor_user_id=a.user_id)
