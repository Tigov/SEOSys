"""Sign in with Google, against the in-process FakeGoogle."""
from urllib.parse import parse_qs, urlparse

import pytest

from .test_google import fake  # noqa: F401  (fixture)


@pytest.fixture()
def api(bare_api):
    """These tests start with no accounts at all."""
    return bare_api


def google_signin(api, fake, sub="g-123", email="sam@example.com", verified=True, name="Sam Google"):
    fake.claims = {"sub": sub, "email": email, "email_verified": verified, "name": name}
    start = api.get("/api/auth/google/start", follow_redirects=False)
    assert start.status_code == 303
    q = parse_qs(urlparse(start.headers["location"]).query)
    assert q["scope"] == ["openid email profile"] and q["code_challenge_method"] == ["S256"]
    return api.get(f"/api/oauth/google/callback?code=good-code&state={q['state'][0]}", follow_redirects=False)


def test_google_signin_creates_verified_user(api, fake, db):
    r = google_signin(api, fake)
    assert r.headers["location"] == "/?signin=ok#/"
    me = api.get("/api/auth/me").json()
    assert me["user"]["email"] == "sam@example.com" and me["user"]["email_verified"] is True
    assert db.one("SELECT password_hash, google_sub FROM users") == {"password_hash": None, "google_sub": "g-123"}


def test_google_signin_existing_google_user(api, fake, db):
    google_signin(api, fake)
    api.post("/api/auth/logout")
    assert google_signin(api, fake).headers["location"] == "/?signin=ok#/"
    assert db.one("SELECT count(*) AS n FROM users")["n"] == 1


def test_google_unverified_email_refused(api, fake):
    assert google_signin(api, fake, verified=False).headers["location"] == "/?signin=failed#/login"
    assert api.get("/api/auth/me").status_code == 401


def test_google_email_matches_password_account_requires_link(api, fake, db, make_user, mail):
    make_user("sam@example.com")
    r = google_signin(api, fake)
    assert r.headers["location"] == "/?signin=link_sent#/login"
    assert api.get("/api/auth/me").status_code == 401
    assert db.one("SELECT google_sub FROM users")["google_sub"] is None
    link = mail().last_link("sam@example.com")
    assert "#/link-google?token=" in link


def test_link_token_links_account(api, fake, db, make_user, mail):
    make_user("sam@example.com")
    google_signin(api, fake)
    token = mail().last_link("sam@example.com").split("token=")[1]
    assert api.post("/api/auth/google/link", json={"token": token}).status_code == 200
    assert api.post("/api/auth/google/link", json={"token": token}).status_code == 400
    assert google_signin(api, fake).headers["location"] == "/?signin=ok#/"


def test_signin_state_reuse_rejected(api, fake):
    fake.claims = {"sub": "g-1", "email": "sam@example.com", "email_verified": True}
    q = parse_qs(urlparse(api.get("/api/auth/google/start", follow_redirects=False).headers["location"]).query)
    url = f"/api/oauth/google/callback?code=good-code&state={q['state'][0]}"
    assert api.get(url, follow_redirects=False).status_code == 303
    assert api.get(url, follow_redirects=False).status_code == 400


def test_signin_link_from_another_browser_rejected(api, fake):
    """Login CSRF: a callback URL started in the attacker's browser must not sign the victim in."""
    from fastapi.testclient import TestClient

    fake.claims = {"sub": "attacker", "email": "attacker@example.com", "email_verified": True}
    q = parse_qs(urlparse(api.get("/api/auth/google/start", follow_redirects=False).headers["location"]).query)
    victim = TestClient(api.app)
    r = victim.get(f"/api/oauth/google/callback?code=good-code&state={q['state'][0]}", follow_redirects=False)
    assert r.status_code == 400 and victim.get("/api/auth/me").status_code == 401


def test_google_signin_with_mfa_asks_for_code(api, fake, db):
    google_signin(api, fake)
    db.execute("UPDATE users SET totp_secret = 'x', totp_enabled_at = now()")
    api.post("/api/auth/logout")
    assert google_signin(api, fake).headers["location"] == "/?signin=mfa#/login"
    assert api.get("/api/auth/me").json()["gate"] == "mfa_required"


def test_suspended_google_user_refused(api, fake, db):
    google_signin(api, fake)
    db.execute("UPDATE users SET status = 'suspended'")
    assert google_signin(api, fake).headers["location"] == "/?signin=failed#/login"
