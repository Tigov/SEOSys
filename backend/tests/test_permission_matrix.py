"""Every route, called by every kind of person, gets exactly the answer the permission table says.

The expected answer is computed from permissions.ACTIONS and STATUS_ALLOWS, so adding a route or changing a rule
changes the test with it. "Allowed" means the request got past the permission layer: any status except 401, 403
and the 404 "Client N was not found" used to hide clients you can't see. Nothing may answer 500.
"""
import re

import pytest
from fastapi.routing import APIRoute

from seo_platform.auth import sessions, tokens
from seo_platform.permissions import ACTIONS, CHANGE_ACTIONS, CLIENT_SCOPED, STATUS_ALLOWS
from tests.conftest import GOOD_PASSWORD

SKIP_PREFIXES = ("/api/auth/", "/api/oauth/", "/api/demo/", "/api/billing/webhook")
EXTRA = ("no_package", "suspended", "other_owner")


def _action(route: APIRoute) -> str:
    def walk(dep):
        for d in dep.dependencies:
            if hasattr(d.call, "action"):
                return d.call.action
            if found := walk(d):
                return found
        return None
    return walk(route.dependant)


def _effective(route: APIRoute, action: str) -> str:
    """Some routes check a second, more specific action inside (change actions, bulk)."""
    if route.path.endswith("/changes/{change_id}/{action}"):
        return CHANGE_ACTIONS["approve"]
    if route.path.endswith("/changes/bulk"):
        return CHANGE_ACTIONS["submit"]
    return action


def _calls(app):
    for route in app.routes:
        if not isinstance(route, APIRoute) or route.path.startswith(SKIP_PREFIXES):
            continue
        path = route.path.replace("{action}", "approve").replace("{user_id}", "2")  # user 1 is the admin
        path = re.sub(r"\{[a-z_]+\}", "1", path)
        for method in sorted(route.methods - {"HEAD"}):
            yield method, path, route


def _body(path: str):
    return {"action": "submit"} if path.endswith("/changes/bulk") else {}


def expected(who: str, action: str, status: str) -> str:
    role = {"anonymous": "public", "suspended": "public", "past_due_owner": "owner",
            "cancelled_owner": "owner", "closed_owner": "owner"}.get(who, who)
    if action == "public":
        return "allowed"
    if role == "public":
        return "login"
    if action in CLIENT_SCOPED and role in ("no_package", "other_owner"):
        return "hidden"
    if role == "other_owner":
        role = "owner"
    if action not in CLIENT_SCOPED and role in ("member", "approver"):
        role = "no_package"  # outside a client, a member is just someone who owns no client yet
    if role not in ACTIONS[action]:
        return "forbidden"
    if action in CLIENT_SCOPED and (role != "admin" or action == "work.run"):
        allowed = STATUS_ALLOWS[status]
        if allowed is not None and action not in allowed:
            return "forbidden"
    return "allowed"


def outcome(resp) -> str:
    assert resp.status_code != 500, resp.text
    if resp.status_code == 401:
        return "login"
    if resp.status_code == 403:
        return "forbidden"
    if resp.status_code == 404 and str(resp.json().get("detail", "")).startswith("Client "):
        return "hidden"
    return "allowed"


def _add_people(db, api):
    from seo_platform.auth import passwords

    other = db.create_client(name="Other Co")
    for who in EXTRA:
        uid = db.insert("users", {"email": f"{who}@seosys.test", "name": who, "password_hash": passwords.hash(GOOD_PASSWORD),
                                  "email_verified_at": "2026-01-01T00:00:00+00:00"})
        if who == "other_owner":
            db.insert("memberships", {"user_id": uid, "client_id": other, "role": "owner"})
        raw = sessions.create(db, db.one("SELECT * FROM users WHERE id = ?", (uid,)), None, "pytest", mfa_passed=True)
        csrf = db.one("SELECT csrf_token FROM sessions WHERE id_hash = ?", (tokens.digest(raw),))["csrf_token"]
        api.identities[who] = (raw, csrf)
        if who == "suspended":
            db.execute("UPDATE users SET status = 'suspended' WHERE id = ?", (uid,))
    api.identities["past_due_owner"] = api.identities["cancelled_owner"] = api.identities["closed_owner"] = \
        api.identities["owner"]


PEOPLE = ("admin", "owner", "member", "approver", "no_package", "anonymous", "suspended", "other_owner",
          "past_due_owner", "cancelled_owner", "closed_owner")


@pytest.mark.parametrize("who", PEOPLE)
def test_permission_matrix(audited, db, who):
    api = audited
    _add_people(db, api)
    status = {"past_due_owner": "past_due", "cancelled_owner": "cancelled", "closed_owner": "closed"}.get(who, "active")
    db.execute("UPDATE clients SET status = ? WHERE id = 1", (status,))
    headers = {} if who == "anonymous" else {"X-Test-As": who}
    mismatches, checked = [], 0
    for method, path, route in _calls(api.app):
        checked += 1
        action = _effective(route, _action(route))
        want = expected(who, action, status)
        kwargs = {"json": _body(path)} if method in ("POST", "PATCH", "PUT") else {}
        got = outcome(api.request(method, path, headers=headers, **kwargs))
        if got != want:
            mismatches.append(f"{method} {path} [{action}] wanted {want}, got {got}")
    assert checked > 30  # the matrix really walked the API
    assert mismatches == []
