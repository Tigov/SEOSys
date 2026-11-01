"""Billing: checkout, signed webhooks, account statuses and the maintenance job."""
import hashlib
import hmac
import json
import threading
import time

import pytest

from seo_platform import billing, clock, maintenance
from tests.conftest import CLIENT, STAFF

SECRET = "whsec_test_secret"


class FakeStripe:
    def __init__(self):
        self.checkouts, self.portals, self.sessions = [], [], {}

    def session(self, session_id):
        return self.sessions[session_id]

    def checkout(self, params):
        self.checkouts.append(params)
        return "https://checkout.stripe.test/session"

    def portal(self, customer_id, return_url):
        self.portals.append((customer_id, return_url))
        return "https://billing.stripe.test/portal"


@pytest.fixture()
def stripe_fake(override, monkeypatch):
    fake = FakeStripe()
    monkeypatch.setattr(billing, "gateway", fake)
    monkeypatch.setenv("STRIPE_PRICE_LOCAL", "price_local_test")
    override(stripe_webhook_secret=SECRET)
    return fake


def signed(event: dict) -> tuple[bytes, str]:
    payload = json.dumps(event).encode()
    ts = str(int(time.time()))
    sig = hmac.new(SECRET.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return payload, f"t={ts},v1={sig}"


def post_event(api, event):
    payload, sig = signed(event)
    return api.post("/api/billing/webhook", content=payload,
                    headers={"Stripe-Signature": sig, "Content-Type": "application/json"})


def completed(user_id, event_id="evt_1", customer="cus_1", plan="local", sub="sub_1"):
    return {"id": event_id, "type": "checkout.session.completed", "data": {"object": {
        "id": "cs_1", "customer": customer, "subscription": sub, "client_reference_id": str(user_id),
        "metadata": {"user_id": str(user_id), "plan": plan, "business_name": "Sam's Plumbing"}}}}


@pytest.fixture()
def buyer(api, make_user, db):
    uid = make_user("buyer@example.com")
    from tests.conftest import RoleClient, login
    browser = RoleClient(api.app)
    browser.identities = {}
    login(browser, "buyer@example.com")
    return uid, browser


def test_plans_are_public(api, stripe_fake):
    plans = {p["id"]: p for p in api.get("/api/plans").json()}
    assert set(plans) == {"audit", "local", "growth"}
    assert plans["local"]["available"] is True and plans["growth"]["available"] is False


def test_checkout_requires_verified_email(api, make_user, stripe_fake):
    from tests.conftest import RoleClient, login
    make_user("new@example.com", verified=False)
    browser = RoleClient(api.app)
    browser.identities = {}
    login(browser, "new@example.com")
    r = browser.post("/api/billing/checkout", json={"plan": "local", "business_name": "New Co"})
    assert r.status_code == 403 and r.json()["detail"] == "email_unverified"


def test_checkout_sends_buyer_to_stripe(buyer, stripe_fake):
    uid, browser = buyer
    r = browser.post("/api/billing/checkout", json={"plan": "local", "business_name": "Sam's Plumbing"})
    assert r.json() == {"url": "https://checkout.stripe.test/session"}
    params = stripe_fake.checkouts[0]
    assert params["mode"] == "subscription" and params["line_items"] == [{"price": "price_local_test", "quantity": 1}]
    assert params["metadata"] == {"user_id": str(uid), "plan": "local", "business_name": "Sam's Plumbing"}


def test_unpriced_plan_cannot_be_bought(buyer, stripe_fake):
    r = buyer[1].post("/api/billing/checkout", json={"plan": "growth", "business_name": "Sam's Plumbing"})
    assert r.status_code == 503


def test_owner_and_admin_cannot_buy_again(api, stripe_fake):
    assert api.post("/api/billing/checkout", json={"plan": "local", "business_name": "X Co"}, headers=CLIENT).status_code == 403
    assert api.post("/api/billing/checkout", json={"plan": "local", "business_name": "X Co"}, headers=STAFF).status_code == 403


def test_checkout_completed_creates_client_owner_subscription_and_welcome(api, buyer, stripe_fake, db, mail):
    uid, browser = buyer
    assert post_event(api, completed(uid)).json() == {"result": "client_created"}
    client = db.one("SELECT * FROM clients WHERE stripe_customer_id = 'cus_1'")
    assert client["name"] == "Sam's Plumbing" and client["status"] == "active" and client["plan"] == "local"
    assert db.one("SELECT role FROM memberships WHERE user_id = ?", (uid,))["role"] == "owner"
    assert db.one("SELECT status FROM subscriptions WHERE client_id = ?", (client["id"],))["status"] == "active"
    assert mail().to("buyer@example.com")[-1]["Subject"] == "Welcome to SEOSys"
    assert browser.get(f"/api/clients/{client['id']}").json()["my_role"] == "owner"


def test_bad_signature_rejected(api, buyer, stripe_fake):
    payload, _ = signed(completed(buyer[0]))
    r = api.post("/api/billing/webhook", content=payload,
                 headers={"Stripe-Signature": "t=1,v1=bad", "Content-Type": "application/json"})
    assert r.status_code == 400


def test_duplicate_webhook_ignored(api, buyer, stripe_fake, db):
    post_event(api, completed(buyer[0]))
    assert post_event(api, completed(buyer[0])).json() == {"result": "duplicate"}
    assert db.one("SELECT count(*) AS n FROM clients WHERE stripe_customer_id = 'cus_1'")["n"] == 1


def test_duplicate_webhook_concurrent(api, buyer, stripe_fake, db):
    event, results = completed(buyer[0]), []
    threads = [threading.Thread(target=lambda: results.append(billing.handle_event(db, event))) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["client_created", "duplicate", "duplicate", "duplicate"]
    assert db.one("SELECT count(*) AS n FROM clients WHERE stripe_customer_id = 'cus_1'")["n"] == 1


def _client_after_purchase(api, buyer, db):
    post_event(api, completed(buyer[0]))
    return db.one("SELECT * FROM clients WHERE stripe_customer_id = 'cus_1'")


def test_payment_failed_sets_past_due_and_emails(api, buyer, stripe_fake, db, mail):
    client = _client_after_purchase(api, buyer, db)
    post_event(api, {"id": "evt_2", "type": "invoice.payment_failed", "data": {"object": {"customer": "cus_1"}}})
    assert db.get_client(client["id"])["status"] == "past_due"
    assert mail().to("buyer@example.com")[-1]["Subject"] == "Your payment didn't go through"
    post_event(api, {"id": "evt_3", "type": "invoice.paid", "data": {"object": {"customer": "cus_1"}}})
    assert db.get_client(client["id"])["status"] == "active"


def test_past_due_blocks_bulk_deploy(audited, db):
    audited.post("/api/clients/1/changes/propose-all", headers=STAFF)
    db.execute("UPDATE clients SET status = 'past_due' WHERE id = 1")
    r = audited.post("/api/clients/1/changes/bulk", json={"action": "deploy"}, headers=STAFF)
    assert r.status_code == 403 and "payment" in r.json()["detail"]
    assert audited.post("/api/clients/1/audits", headers=STAFF).status_code == 403
    assert audited.get("/api/clients/1", headers=CLIENT).status_code == 200


def test_subscription_cancelled_then_closed_then_deleted(api, buyer, stripe_fake, db):
    client = _client_after_purchase(api, buyer, db)
    post_event(api, {"id": "evt_4", "type": "customer.subscription.deleted", "data": {"object": {
        "id": "sub_1", "customer": "cus_1", "status": "canceled", "cancel_at": None}}})
    assert db.get_client(client["id"])["status"] == "cancelled"
    browser = buyer[1]
    assert browser.get(f"/api/clients/{client['id']}").status_code == 200
    assert browser.patch(f"/api/clients/{client['id']}/settings", json={"freeze_deploys": True}).status_code == 403

    clock.advance(days=30, seconds=1)
    assert maintenance.run(db)["closed"] == 1
    assert db.get_client(client["id"])["status"] == "closed"
    clock.advance(days=30)
    assert maintenance.run(db)["deleted"] == 1
    assert db.get_client(client["id"]) is None
    assert db.one("SELECT action FROM audit_events WHERE action = 'client.deleted'")


def test_closed_account_keeps_export_only(api, db):
    db.execute("UPDATE clients SET status = 'closed' WHERE id = 1")
    assert api.get("/api/clients/1", headers=CLIENT).status_code == 403
    assert api.get("/api/clients/1/export", headers=CLIENT).status_code == 200


def test_manual_activation_logged(api, db):
    db.execute("UPDATE clients SET status = 'past_due' WHERE id = 1")
    assert api.post("/api/admin/clients/1/activate", headers=STAFF).json()["status"] == "active"
    assert api.post("/api/admin/clients/1/activate", headers=CLIENT).status_code == 403
    assert db.one("SELECT actor FROM audit_events WHERE action = 'billing.activated_manually'")["actor"].startswith("admin:")


def test_billing_portal_for_owner(api, buyer, stripe_fake, db):
    client = _client_after_purchase(api, buyer, db)
    r = buyer[1].post(f"/api/clients/{client['id']}/billing/portal")
    assert r.json() == {"url": "https://billing.stripe.test/portal"} and stripe_fake.portals[0][0] == "cus_1"
    assert api.post("/api/clients/1/billing/portal", headers=CLIENT).status_code == 409  # demo client isn't billed online


def test_maintenance_idempotent(db):
    first, second = maintenance.run(db), maintenance.run(db)
    assert second == {k: 0 for k in first}


def test_maintenance_clears_expired_sessions(api, db):
    clock.advance(days=31)
    assert maintenance.run(db)["sessions"] == 4


def test_seed_creates_admin_and_demo_people(db, override):
    from seo_platform.__main__ import seed
    override(seed_admin_email="Founder@Example.com", seed_admin_password="a long admin passphrase")
    created = seed(db, demo=True)
    assert "admin founder@example.com" in created and len(created) == 4
    assert seed(db, demo=True) == []  # safe to run again
    admin = db.one("SELECT is_admin, email_verified_at FROM users WHERE email = 'founder@example.com'")
    assert admin["is_admin"] is True and admin["email_verified_at"]


def test_seed_refuses_demo_in_production(db, override):
    from seo_platform.__main__ import seed
    override(app_env="production")
    with pytest.raises(SystemExit):
        seed(db, demo=True)


def _session(user_id, status="complete"):
    return {"id": "cs_test_1", "status": status, "customer": "cus_1", "subscription": "sub_1",
            "client_reference_id": str(user_id),
            "metadata": {"user_id": str(user_id), "plan": "local", "business_name": "Sam's Plumbing"}}


def test_return_from_stripe_sets_up_account_without_webhook(api, buyer, stripe_fake, db):
    uid, browser = buyer
    stripe_fake.sessions["cs_test_1"] = _session(uid)
    r = browser.post("/api/billing/confirm", json={"session_id": "cs_test_1"})
    client_id = r.json()["client_id"]
    assert r.status_code == 200 and db.get_client(client_id)["plan"] == "local"
    assert browser.post("/api/billing/confirm", json={"session_id": "cs_test_1"}).json() == {"client_id": client_id}
    assert post_event(api, completed(uid)).json() == {"result": "already_created"}  # the late webhook changes nothing
    assert db.one("SELECT count(*) AS n FROM clients WHERE stripe_customer_id = 'cus_1'")["n"] == 1


def test_confirm_unfinished_checkout_waits(buyer, stripe_fake):
    uid, browser = buyer
    stripe_fake.sessions["cs_test_1"] = _session(uid, status="open")
    assert browser.post("/api/billing/confirm", json={"session_id": "cs_test_1"}).json() == {"client_id": None}


def test_cannot_confirm_someone_elses_checkout(buyer, stripe_fake):
    _, browser = buyer
    stripe_fake.sessions["cs_test_1"] = _session(999)
    assert browser.post("/api/billing/confirm", json={"session_id": "cs_test_1"}).status_code == 403
    assert browser.post("/api/billing/confirm", json={"session_id": "not-a-session"}).status_code == 404


def test_stripe_setup_refuses_live_keys(override):
    from seo_platform.__main__ import stripe_setup
    override(stripe_secret_key="sk_live_nope")
    with pytest.raises(SystemExit):
        stripe_setup(None)
