"""Permissions: every route declares an action, CSRF protection, and the client roles."""
from fastapi.routing import APIRoute

from tests.conftest import APPROVER, CLIENT, MEMBER, STAFF


def _actions(dependant):
    found = []
    for dep in dependant.dependencies:
        if hasattr(dep.call, "action"):
            found.append(dep.call.action)
        found += _actions(dep)
    return found


def test_every_route_declares_action(api):
    missing = [f"{sorted(r.methods)} {r.path}" for r in api.app.routes
               if isinstance(r, APIRoute) and not _actions(r.dependant)]
    assert missing == []


def test_missing_csrf_rejected(api):
    r = api.patch("/api/clients/1/settings", json={"freeze_deploys": True}, headers={**STAFF, "X-CSRF-Token": ""})
    assert r.status_code == 403 and "session" in r.json()["detail"]


def test_wrong_csrf_rejected(api):
    r = api.patch("/api/clients/1/settings", json={"freeze_deploys": True}, headers={**STAFF, "X-CSRF-Token": "nope"})
    assert r.status_code == 403


def test_form_post_without_session_rejected(api):
    r = api.post("/api/auth/login", content="email=a&password=b",
                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 415


def test_x_role_header_ignored(api):
    assert api.get("/api/clients", headers={"X-Role": "staff", "X-Actor": "staff:me"}).status_code == 401
    assert api.get("/api/clients/1", headers={"X-Role": "staff"}).status_code == 401


def test_admin_sees_every_client_clients_see_only_theirs(api, db):
    other = db.create_client(name="Other Co")
    assert api.get("/api/clients", headers=STAFF).status_code == 200
    assert api.get("/api/clients", headers=CLIENT).status_code == 403
    assert api.get(f"/api/clients/{other}", headers=STAFF).status_code == 200
    assert api.get(f"/api/clients/{other}", headers=CLIENT).status_code == 404  # not even told it exists


def test_member_can_view_but_not_change(audited):
    audited.post("/api/clients/1/changes/propose-all", headers=STAFF)
    cid = audited.get("/api/clients/1/changes", headers=MEMBER).json()[0]["id"]
    audited.post(f"/api/clients/1/changes/{cid}/submit", headers=STAFF)
    assert audited.post(f"/api/clients/1/changes/{cid}/approve", headers=MEMBER).status_code == 403
    assert audited.patch("/api/clients/1/settings", json={"freeze_deploys": True}, headers=MEMBER).status_code == 403
    assert audited.get("/api/clients/1/export", headers=MEMBER).status_code == 403
    assert audited.post(f"/api/clients/1/changes/{cid}/approve", headers=APPROVER).status_code == 200


def test_bulk_checks_the_bulk_action(audited):
    audited.post("/api/clients/1/changes/propose-all", headers=STAFF)
    assert audited.post("/api/clients/1/changes/bulk", json={"action": "submit"}, headers=CLIENT).status_code == 403
    assert audited.post("/api/clients/1/changes/bulk", json={"action": "submit"}, headers=STAFF).status_code == 200
    assert audited.post("/api/clients/1/changes/bulk", json={"action": "approve"}, headers=STAFF).status_code == 403
    assert audited.post("/api/clients/1/changes/bulk", json={"action": "approve"}, headers=MEMBER).status_code == 403


def test_client_summary_lists_what_i_can_do(api):
    owner = api.get("/api/clients/1", headers=CLIENT).json()
    assert owner["my_role"] == "owner" and "change.approve" in owner["can"] and "work.run" not in owner["can"]
    member = api.get("/api/clients/1", headers=MEMBER).json()
    assert "client.view" in member["can"] and "change.approve" not in member["can"]


def test_admin_blocked_until_mfa_passed(api, db):
    db.execute("UPDATE sessions SET mfa_passed = false WHERE user_id = (SELECT id FROM users WHERE is_admin)")
    r = api.get("/api/clients", headers=STAFF)
    assert r.status_code == 403 and r.json()["detail"] == "mfa_required"


def test_require_mfa_client_forces_setup(api):
    assert api.patch("/api/clients/1/settings", json={"require_mfa": True}, headers=CLIENT).status_code == 403  # owner has none
    api.patch("/api/clients/1/settings", json={"require_mfa": True}, headers=STAFF)
    r = api.get("/api/clients/1", headers=MEMBER)
    assert r.status_code == 403 and r.json()["detail"] == "mfa_setup_required"
    assert api.get("/api/clients/1", headers=STAFF).status_code == 200


def test_permission_table_is_published(api):
    table = api.get("/api/auth/permissions").json()
    assert table["actions"]["change.approve"] == ["approver", "owner"]
    assert table["change_actions"]["deploy"] == "work.run"
