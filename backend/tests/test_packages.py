"""Packages split by service: what each one fixes, and which one the free check recommends."""
import pytest

from seo_platform.plans import PLANS, plan_covers, recommend
from seo_platform.rules import area_of

from .conftest import STAFF


def test_lineup_prices_and_order():
    monthly = {p.id: p.amount_cents for p in PLANS.values() if p.mode == "subscription"}
    one_off = {p.id: p.amount_cents for p in PLANS.values() if p.mode == "payment"}
    assert monthly == {"technical": 100000, "onpage": 100000, "local": 100000, "complete": 230000}
    assert one_off == {"audit": 150000, "fixup": 250000}
    assert min(p.amount_cents for p in PLANS.values()) >= 100000
    # Buying a one-off every month must never beat the monthly package it replaces.
    assert one_off["audit"] > monthly["technical"] and one_off["fixup"] > monthly["complete"]


@pytest.mark.parametrize(("areas", "plan"), [
    ({"technical"}, "technical"),
    ({"technical", "ai_local"}, "technical"),
    ({"onpage"}, "onpage"),
    ({"technical", "onpage"}, "complete"),
    ({"onpage", "ai_local"}, "complete"),
    (set(), "technical"),
])
def test_free_check_recommends_the_smallest_package_that_fixes_everything(areas, plan):
    assert recommend(areas) == plan


def test_each_package_fixes_only_its_own_area():
    assert area_of("broken_link") == "technical" and area_of("missing_meta_description") == "onpage"
    assert area_of("ai_crawlers_blocked") == "ai_local" and area_of("some_future_rule") == "technical"
    assert plan_covers("technical", "broken_link") and plan_covers("technical", "ai_crawlers_blocked")
    assert not plan_covers("technical", "missing_meta_description")
    assert plan_covers("onpage", "missing_meta_description") and not plan_covers("onpage", "broken_link")
    for everything in ("complete", "fixup", None, "an_unknown_id"):  # no package: a client the agency set up itself
        assert plan_covers(everything, "broken_link") and plan_covers(everything, "missing_title")
    assert not plan_covers("audit", "broken_link")  # the audit is a report; the client makes the fixes
    assert plan_covers("growth", "broken_link") and not plan_covers("growth", "missing_title")  # retired → technical


def test_only_fixes_in_the_clients_package_are_prepared(audited, db):
    db.execute("UPDATE clients SET plan = 'onpage' WHERE id = 1")
    assert audited.post("/api/clients/1/changes/propose-all", headers=STAFF).json()["created"]
    rules = {r["rule_id"] for r in db.query(
        "SELECT f.rule_id FROM change_requests c JOIN findings f ON f.id = c.finding_id WHERE c.client_id = 1")}
    assert rules and all(area_of(r) == "onpage" for r in rules), rules

    broken = db.one("SELECT id FROM findings WHERE client_id = 1 AND rule_id = 'broken_link'")
    r = audited.post(f"/api/clients/1/findings/{broken['id']}/propose", headers=STAFF)
    assert r.status_code == 403 and "On-Page SEO" in r.json()["detail"]
