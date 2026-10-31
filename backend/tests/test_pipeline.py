import json

import httpx
import pytest

from seo_platform.fixes import robots_without_ai_blocks
from seo_platform.policy import lint

from .conftest import CLIENT, STAFF


def rule_ids(api, status="open"):
    return {f["rule_id"] for f in api.get(f"/api/clients/1/findings?status={status}", headers=STAFF).json()}


def test_audit_finds_seeded_problems(audited):
    found = rule_ids(audited)
    expected = {"broken_link", "redirect_chain", "noindex_important", "duplicate_title", "missing_meta_description",
                "missing_h1", "img_missing_alt", "missing_canonical", "thin_content", "title_too_long",
                "missing_local_business_schema", "ai_crawlers_blocked", "not_in_sitemap"}
    assert expected <= found, expected - found
    summary = audited.get("/api/clients/1", headers=STAFF).json()
    assert summary["health_score"] < 60
    assert summary["pages_crawled"] >= 8


def test_every_finding_has_evidence(audited):
    for f in audited.get("/api/clients/1/findings", headers=STAFF).json():
        assert f["evidence"] is not None and f["fix_hint"], f


def deploy_everything(api):
    assert api.post("/api/clients/1/changes/propose-all", headers=STAFF).status_code == 200
    api.post("/api/clients/1/changes/bulk", json={"action": "submit"}, headers=STAFF)
    api.post("/api/clients/1/changes/bulk", json={"action": "approve"}, headers=CLIENT)
    return api.post("/api/clients/1/changes/bulk", json={"action": "deploy"}, headers=STAFF).json()["results"]


def test_full_pipeline_fixes_site_and_raises_score(audited):
    before = audited.get("/api/clients/1", headers=STAFF).json()["health_score"]
    results = deploy_everything(audited)
    assert results and all(r["status"] == "live" for r in results), results
    audited.post("/api/clients/1/audits", headers=STAFF)
    after = audited.get("/api/clients/1", headers=STAFF).json()["health_score"]
    assert after > before + 30
    remaining = rule_ids(audited)
    for fixed in ("noindex_important", "duplicate_title", "missing_meta_description", "ai_crawlers_blocked",
                  "missing_local_business_schema", "redirect_chain", "img_missing_alt"):
        assert fixed not in remaining
    assert "thin_content" in remaining  # content needs humans; never auto-fixed


def test_fault_triggers_automatic_rollback(audited, demo):
    audited.post("/api/clients/1/changes/propose-all", headers=STAFF)
    change = next(c for c in audited.get("/api/clients/1/changes", headers=STAFF).json()
                  if c["target"].get("field") == "meta_description")
    audited.post(f"/api/clients/1/changes/{change['id']}/submit", headers=STAFF)
    audited.post(f"/api/clients/1/changes/{change['id']}/approve", headers=CLIENT)
    audited.post("/api/demo/fault", json={"on": True}, headers=STAFF)
    out = audited.post(f"/api/clients/1/changes/{change['id']}/deploy", headers=STAFF).json()
    assert out["status"] == "rolled_back"
    assert not out["verification"]["passed"]
    page = demo.state.store.page(change["target"]["path"])
    assert page["broken"] is False and page["meta_description"] == json.loads(change["before_value"])
    alerts = audited.get("/api/clients/1", headers=STAFF).json()["alerts"]
    assert any(a["level"] == "critical" for a in alerts)


def test_manual_rollback_restores_value(audited, demo):
    results = deploy_everything(audited)
    cid = results[0]["id"]
    change = next(c for c in audited.get("/api/clients/1/changes", headers=STAFF).json() if c["id"] == cid)
    out = audited.post(f"/api/clients/1/changes/{cid}/rollback", headers=CLIENT).json()
    assert out["status"] == "rolled_back"


def test_roles_are_enforced(audited):
    audited.post("/api/clients/1/changes/propose-all", headers=STAFF)
    cid = audited.get("/api/clients/1/changes", headers=STAFF).json()[0]["id"]
    assert audited.post(f"/api/clients/1/changes/{cid}/submit", headers=CLIENT).status_code == 403
    audited.post(f"/api/clients/1/changes/{cid}/submit", headers=STAFF)
    assert audited.post(f"/api/clients/1/changes/{cid}/approve", headers=STAFF).status_code == 403
    assert audited.post(f"/api/clients/1/changes/{cid}/deploy", headers=STAFF).status_code == 409  # not approved yet
    audited.post(f"/api/clients/1/changes/{cid}/approve", headers=CLIENT)
    assert audited.post(f"/api/clients/1/changes/{cid}/deploy", headers=CLIENT).status_code == 403


def test_freeze_switch_blocks_deploys(audited):
    audited.post("/api/clients/1/changes/propose-all", headers=STAFF)
    cid = audited.get("/api/clients/1/changes", headers=STAFF).json()[0]["id"]
    audited.post(f"/api/clients/1/changes/{cid}/submit", headers=STAFF)
    audited.post(f"/api/clients/1/changes/{cid}/approve", headers=CLIENT)
    audited.patch("/api/clients/1/settings", json={"freeze_deploys": True}, headers=STAFF)
    assert audited.post(f"/api/clients/1/changes/{cid}/deploy", headers=STAFF).status_code == 409


def test_low_risk_auto_approval_only_when_client_opts_in(audited):
    assert audited.patch("/api/clients/1/settings", json={"auto_approve_low": True}, headers=STAFF).status_code == 403
    audited.patch("/api/clients/1/settings", json={"auto_approve_low": True}, headers=CLIENT)
    audited.post("/api/clients/1/changes/propose-all", headers=STAFF)
    audited.post("/api/clients/1/changes/bulk", json={"action": "submit"}, headers=STAFF)
    changes = audited.get("/api/clients/1/changes", headers=STAFF).json()
    assert all(c["status"] == "approved" for c in changes if c["risk"] == "low")
    assert all(c["status"] == "awaiting_client" for c in changes if c["risk"] != "low")


def test_drift_is_detected_before_deploy(audited, demo):
    audited.post("/api/clients/1/changes/propose-all", headers=STAFF)
    change = next(c for c in audited.get("/api/clients/1/changes", headers=STAFF).json()
                  if c["target"].get("field") == "title")
    audited.post(f"/api/clients/1/changes/{change['id']}/submit", headers=STAFF)
    audited.post(f"/api/clients/1/changes/{change['id']}/approve", headers=CLIENT)
    demo.state.store.update_field(change["target"]["path"], "title", "Edited by the client meanwhile")
    out = audited.post(f"/api/clients/1/changes/{change['id']}/deploy", headers=STAFF).json()
    assert out["status"] == "failed" and "page changed" in out["deploy_result"]["error"]


def test_tenant_isolation(audited):
    r = audited.post("/api/clients", headers=STAFF, json={"name": "Other Co", "site_url": "http://127.0.0.1:8001",
                                                          "city": "Dallas"})
    other = r.json()["id"]
    finding_id = audited.get("/api/clients/1/findings", headers=STAFF).json()[0]["id"]
    assert audited.get(f"/api/clients/{other}/findings", headers=STAFF).json() == []
    assert audited.post(f"/api/clients/{other}/findings/{finding_id}/propose", headers=STAFF).status_code == 404
    assert audited.get("/api/clients/999/findings", headers=STAFF).status_code == 404
    export = audited.get(f"/api/clients/{other}/export", headers=STAFF).json()
    assert export["findings"] == [] and export["change_requests"] == []


def test_visibility_improves_after_fixes(audited):
    first = audited.post("/api/clients/1/visibility/run", headers=STAFF).json()["latest"]["mention_rate"]
    deploy_everything(audited)
    audited.post("/api/clients/1/audits", headers=STAFF)
    second = audited.post("/api/clients/1/visibility/run", headers=STAFF).json()
    assert second["method"] == "simulated"
    assert second["latest"]["mention_rate"] > first


def test_grader_and_report(api):
    out = api.post("/api/grader", json={"url": "http://127.0.0.1:8001", "email": "owner@example.com"}).json()
    assert 0 <= out["score"] < 100 and out["top_issues"]
    assert api.get("/api/leads", headers=STAFF).json()[0]["email"] == "owner@example.com"
    api.post("/api/clients/1/audits", headers=STAFF)
    html = api.get("/api/clients/1/report", headers=CLIENT).text
    assert "Monthly SEO report" in html and "simulated" in html


def _demo_post(demo, path, body, headers):
    import asyncio

    async def call():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=demo), base_url="http://demo") as c:
            return await c.post(path, content=body, headers=headers)

    return asyncio.run(call())


def test_demo_plugin_rejects_unsigned_replayed_and_bad_timestamp_requests(demo):
    import time

    from seo_platform.adapters.site_wp import sign
    from seo_platform.config import settings

    path = "/wp-json/seo-poc/v1/update"
    body = json.dumps({"path": "/", "field": "title", "value": "x"}).encode()
    assert _demo_post(demo, path, body, {}).status_code == 401

    def signed(ts, nonce, sig_path=path):
        return {"x-seo-timestamp": ts, "x-seo-nonce": nonce,
                "x-seo-signature": sign(settings.demo_site_secret, ts, nonce, "POST", sig_path, body)}

    good = signed(str(time.time()), "n1")
    assert _demo_post(demo, path, body, good).status_code == 200
    assert _demo_post(demo, path, body, good).status_code == 401          # replay
    assert _demo_post(demo, path, body, signed("nan", "n2")).status_code == 401
    assert _demo_post(demo, path, body, signed(str(time.time()), "n3", "/wp-json/seo-poc/v1/robots")).status_code == 401


def test_signing_secret_is_never_returned(audited):
    assert "adapter_secret" not in audited.get("/api/clients/1", headers=CLIENT).json()["site"]
    export = audited.get("/api/clients/1/export", headers=STAFF).json()
    assert all("adapter_secret" not in s for s in export["sites"])
    assert audited.get("/api/clients/1").status_code == 401            # no role header -> rejected
    assert audited.get("/api/clients/1/report").status_code == 401


def test_parallel_deploys_write_once(audited):
    import asyncio

    from seo_platform import changes as change_svc
    from seo_platform.adapters.site_wp import WordPressAdapter

    audited.post("/api/clients/1/changes/propose-all", headers=STAFF)
    cid = audited.get("/api/clients/1/changes", headers=STAFF).json()[0]["id"]
    audited.post(f"/api/clients/1/changes/{cid}/submit", headers=STAFF)
    audited.post(f"/api/clients/1/changes/{cid}/approve", headers=CLIENT)
    repo = audited.app.state.db.for_client(1)
    site = repo.site()
    adapter = WordPressAdapter(site["base_url"], site["adapter_secret"])

    async def both():
        return await asyncio.gather(
            change_svc.deploy_change(repo, cid, "a", "staff", adapter),
            change_svc.deploy_change(repo, cid, "b", "staff", adapter), return_exceptions=True)

    results = asyncio.run(both())
    assert sum(isinstance(r, change_svc.TransitionError) for r in results) == 1
    assert sum(isinstance(r, dict) and r["status"] == "live" for r in results) == 1


def test_schema_cannot_break_out_of_script_tag():
    from seo_platform.fixes import local_business_schema

    out = local_business_schema({"name": "Acme</script><script>alert(1)</script>", "city": "Austin"}, "http://x")
    assert "<" not in out and ">" not in out
    assert json.loads(out)["name"].startswith("Acme</script>")


def test_policy_linter():
    for bad in ("We guarantee #1 rankings on Google", "Become a Google Partner today", "Guaranteeing results",
                "Austin's #1st choice", "No. 1 HVAC in Austin", "the number-one AC company", "Ranked first on Google"):
        assert lint(bad), bad
    assert not lint("Fast, honest AC repair in Austin.")


def test_robots_rewrite_keeps_other_rules():
    src = "User-agent: GPTBot\nDisallow: /\nSitemap: https://x.com/sitemap.xml\n\nUser-agent: *\nDisallow: /wp-admin\nUser-agent broken line\n"
    out = robots_without_ai_blocks(src)
    assert "GPTBot" not in out and "Disallow: /wp-admin" in out and "Sitemap: https://x.com/sitemap.xml" in out
    mixed = robots_without_ai_blocks("User-agent: GPTBot\nUser-agent: Bingbot\nDisallow: /private\n")
    assert "Bingbot" in mixed and "Disallow: /private" in mixed
