"""Team: invitations, approval rights, removal and ownership transfer."""
from fastapi.testclient import TestClient

from seo_platform import clock
from tests.conftest import CLIENT, MEMBER, STAFF, login


def invite(api, email="new@example.com", can_approve=False, headers=CLIENT):
    return api.post("/api/clients/1/team/invites", json={"email": email, "can_approve": can_approve}, headers=headers)


def token(mail, email="new@example.com"):
    return mail().last_link(email).split("token=")[1]


def joiner(api, make_user, email="new@example.com"):
    """A separate browser signed in as `email`."""
    from tests.conftest import RoleClient
    make_user(email)
    browser = RoleClient(api.app)
    browser.identities = {}
    login(browser, email)
    return browser


def test_owner_invites_and_person_joins(api, make_user, mail, db):
    assert invite(api, can_approve=True).status_code == 201
    browser = joiner(api, make_user)
    r = browser.post("/api/invites/accept", json={"token": token(mail)})
    assert r.status_code == 200 and r.json() == {"client_id": 1}
    me = browser.get("/api/auth/me").json()
    assert me["memberships"][0]["role"] == "member" and me["memberships"][0]["can_approve"] is True
    assert browser.get("/api/clients/1").json()["my_role"] == "approver"


def test_member_cannot_invite(api):
    assert invite(api, headers=MEMBER).status_code == 403


def test_admin_can_invite(api):
    assert invite(api, headers=STAFF).status_code == 201


def test_invite_email_must_match(api, make_user, mail):
    invite(api)
    browser = joiner(api, make_user, "someone.else@example.com")
    assert browser.post("/api/invites/accept", json={"token": token(mail)}).status_code == 400


def test_invite_expires_after_7_days(api, make_user, mail):
    invite(api)
    raw = token(mail)
    clock.advance(days=7, seconds=1)
    browser = joiner(api, make_user)
    assert browser.post("/api/invites/accept", json={"token": raw}).status_code == 400


def test_accept_is_atomic_and_single_use(api, make_user, mail, db):
    invite(api)
    raw = token(mail)
    browser = joiner(api, make_user)
    assert browser.post("/api/invites/accept", json={"token": raw}).status_code == 200
    assert browser.post("/api/invites/accept", json={"token": raw}).status_code == 400
    assert db.one("SELECT count(*) AS n FROM memberships WHERE client_id = 1")["n"] == 4


def test_reinvite_replaces_old_link(api, make_user, mail):
    invite(api)
    first = token(mail)
    invite(api)
    browser = joiner(api, make_user)
    assert browser.post("/api/invites/accept", json={"token": first}).status_code == 400


def test_cannot_invite_existing_member(api):
    assert invite(api, email="member@seosys.test").status_code == 409


def test_team_listing_and_cancel(api):
    invite(api)
    listed = api.get("/api/clients/1/team", headers=MEMBER).json()
    assert {m["email"] for m in listed["members"]} == {"owner@seosys.test", "member@seosys.test", "approver@seosys.test"}
    inv = listed["invites"][0]
    assert api.delete(f"/api/clients/1/team/invites/{inv['id']}", headers=CLIENT).status_code == 200
    assert api.get("/api/clients/1/team", headers=CLIENT).json()["invites"] == []


def test_owner_ticks_can_approve(api, db):
    member = db.one("SELECT id FROM users WHERE email = 'member@seosys.test'")["id"]
    assert api.patch(f"/api/clients/1/team/{member}", json={"can_approve": True}, headers=CLIENT).status_code == 200
    assert api.get("/api/clients/1", headers=MEMBER).json()["my_role"] == "approver"


def test_owner_cannot_leave_without_transfer(api, db):
    owner = db.one("SELECT id FROM users WHERE email = 'owner@seosys.test'")["id"]
    assert api.delete(f"/api/clients/1/team/{owner}", headers=CLIENT).status_code == 409
    assert api.delete(f"/api/clients/1/team/{owner}", headers=STAFF).status_code == 409


def test_remove_member_revokes_access(api, db):
    member = db.one("SELECT id FROM users WHERE email = 'member@seosys.test'")["id"]
    assert api.delete(f"/api/clients/1/team/{member}", headers=CLIENT).status_code == 200
    assert api.get("/api/clients/1", headers=MEMBER).status_code == 404


def test_transfer_ownership_swaps_roles(api, db):
    member = db.one("SELECT id FROM users WHERE email = 'member@seosys.test'")["id"]
    assert api.post("/api/clients/1/team/transfer", json={"user_id": member}, headers=CLIENT).status_code == 200
    assert api.get("/api/clients/1", headers=MEMBER).json()["my_role"] == "owner"
    assert api.get("/api/clients/1", headers=CLIENT).json()["my_role"] == "approver"
    assert db.one("SELECT count(*) AS n FROM memberships WHERE client_id = 1 AND role = 'owner'")["n"] == 1


def test_accepting_invite_verifies_email(api, make_user, mail, db):
    invite(api)
    make_user("new@example.com", verified=False)
    browser = TestClient(api.app)
    login(browser, "new@example.com")
    csrf = browser.get("/api/auth/me").json()["csrf_token"]
    browser.post("/api/invites/accept", json={"token": token(mail)}, headers={"X-CSRF-Token": csrf})
    assert db.one("SELECT email_verified_at FROM users WHERE email = 'new@example.com'")["email_verified_at"]
