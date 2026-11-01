"""Accounts: sign-up, verification, login, lockout, sessions, reset and password change (spec section 5)."""
import pytest
from fastapi.testclient import TestClient

from seo_platform import clock
from seo_platform.auth import sessions
from seo_platform.auth.service import suspend
from tests.conftest import GOOD_PASSWORD, login

NEW_PASSWORD = "green kettle hums softly"


@pytest.fixture()
def api(bare_api):
    """These tests start with no accounts at all."""
    return bare_api


def token_from(link: str) -> str:
    return link.split("token=", 1)[1]


def signup(api, email="sam@example.com", name="Sam", password=GOOD_PASSWORD):
    return api.post("/api/auth/signup", json={"email": email, "name": name, "password": password})


def test_signup_creates_unverified_user_and_queues_verify(api, db, mail):
    r = signup(api)
    assert r.status_code == 202
    user = db.one("SELECT * FROM users WHERE email = 'sam@example.com'")
    assert user["email_verified_at"] is None and user["password_hash"].startswith("$argon2id$")
    link = mail().last_link("sam@example.com")
    assert "#/verify?token=" in link
    assert api.post("/api/auth/verify", json={"token": token_from(link)}).status_code == 200
    assert db.one("SELECT email_verified_at FROM users")["email_verified_at"] is not None


def test_verify_token_is_single_use_and_lasts_24h(api, mail):
    signup(api)
    token = token_from(mail().last_link("sam@example.com"))
    clock.advance(hours=24, seconds=1)
    assert api.post("/api/auth/verify", json={"token": token}).status_code == 400
    clock.reset()
    assert api.post("/api/auth/verify", json={"token": token}).status_code == 200
    assert api.post("/api/auth/verify", json={"token": token}).status_code == 400


def test_signup_taken_email_same_response_and_emails_owner(api, db, mail, make_user):
    make_user("sam@example.com")
    r = signup(api, password="another fine password")
    assert r.status_code == 202 and r.json() == signup(api, email="new@example.com").json()
    assert db.one("SELECT count(*) AS n FROM users WHERE email = 'sam@example.com'")["n"] == 1
    assert "already have an account" in mail().to("sam@example.com")[-1]["Subject"]


def test_signup_rejects_weak_password(api):
    r = signup(api, password="password1234")
    assert r.status_code == 400 and "common" in r.json()["detail"]


def test_email_normalised_everywhere(api, db, mail):
    signup(api, email="  Sam@Example.COM ")
    assert db.one("SELECT email FROM users")["email"] == "sam@example.com"
    login(api, " SAM@example.com")
    api.post("/api/auth/forgot", json={"email": "SAM@EXAMPLE.COM "})
    assert any("Reset" in m["Subject"] for m in mail().to("sam@example.com"))


def test_login_sets_secure_cookie_and_me_works(api, make_user):
    make_user("sam@example.com")
    r = login(api, "sam@example.com")
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    me = api.get("/api/auth/me").json()
    assert me["user"]["email"] == "sam@example.com" and me["csrf_token"] and me["memberships"] == []


def test_cookie_is_secure_in_production(api, make_user, override):
    override(app_env="production")
    make_user("sam@example.com")
    assert "secure" in login(api, "sam@example.com").headers["set-cookie"].lower()


def test_login_unknown_email_generic_error(api, make_user):
    make_user("sam@example.com")
    unknown = api.post("/api/auth/login", json={"email": "nobody@example.com", "password": GOOD_PASSWORD})
    wrong = api.post("/api/auth/login", json={"email": "sam@example.com", "password": "not the password"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


def test_suspended_user_cannot_log_in(api, make_user):
    make_user("sam@example.com", status="suspended")
    assert api.post("/api/auth/login", json={"email": "sam@example.com", "password": GOOD_PASSWORD}).status_code == 401


def test_lockout_after_5_failures_for_15_minutes(api, make_user):
    make_user("sam@example.com")
    for _ in range(5):
        assert api.post("/api/auth/login", json={"email": "sam@example.com", "password": "wrong"}).status_code == 401
    locked = api.post("/api/auth/login", json={"email": "sam@example.com", "password": GOOD_PASSWORD})
    assert locked.status_code == 429
    clock.advance(minutes=15, seconds=1)
    login(api, "sam@example.com")


def test_unknown_email_locks_the_same_way(api):
    for _ in range(5):
        api.post("/api/auth/login", json={"email": "ghost@example.com", "password": "wrong"})
    assert api.post("/api/auth/login", json={"email": "ghost@example.com", "password": "x"}).status_code == 429


def test_ip_block_after_20_failures(api, make_user):
    make_user("sam@example.com")
    attacker = TestClient(api.app, client=("203.0.113.9", 5000))
    for i in range(20):
        attacker.post("/api/auth/login", json={"email": f"user{i}@example.com", "password": "wrong"})
    assert attacker.post("/api/auth/login", json={"email": "sam@example.com", "password": GOOD_PASSWORD}).status_code == 429
    login(api, "sam@example.com")  # other addresses are unaffected


def test_session_idle_12h(api, make_user):
    make_user("sam@example.com")
    login(api, "sam@example.com")
    clock.advance(hours=11)
    assert api.get("/api/auth/me").status_code == 200
    clock.advance(hours=12, seconds=1)
    assert api.get("/api/auth/me").status_code == 401


def test_session_absolute_30_days(api, make_user):
    make_user("sam@example.com")
    login(api, "sam@example.com")
    for _ in range(65):  # stay active (every 11 hours) for 715 hours
        clock.advance(hours=11)
        assert api.get("/api/auth/me").status_code == 200
    clock.advance(hours=5, seconds=1)  # 30 days and a second after login
    assert api.get("/api/auth/me").status_code == 401


def test_admin_session_absolute_8h(api, make_user):
    make_user("admin@example.com", admin=True)
    login(api, "admin@example.com")
    clock.advance(hours=7)
    assert api.get("/api/auth/me").status_code == 200
    clock.advance(hours=1, seconds=1)
    assert api.get("/api/auth/me").status_code == 401


def test_session_rotates_on_login(api, db, make_user):
    make_user("sam@example.com")
    first = login(api, "sam@example.com").cookies[sessions.COOKIE]
    second = login(api, "sam@example.com").cookies[sessions.COOKIE]
    assert first != second
    assert db.one("SELECT count(*) AS n FROM sessions")["n"] == 1


def test_logout_deletes_session(api, db, make_user):
    make_user("sam@example.com")
    login(api, "sam@example.com")
    api.post("/api/auth/logout")
    assert db.one("SELECT count(*) AS n FROM sessions")["n"] == 0
    assert api.get("/api/auth/me").status_code == 401


def test_session_cookie_hash_only_in_db(api, db, make_user):
    make_user("sam@example.com")
    raw = login(api, "sam@example.com").cookies[sessions.COOKIE]
    assert db.one("SELECT count(*) AS n FROM sessions WHERE id_hash = ?", (raw,))["n"] == 0


def test_reset_token_single_use_30_min(api, make_user, mail):
    make_user("sam@example.com")
    api.post("/api/auth/forgot", json={"email": "sam@example.com"})
    token = token_from(mail().last_link("sam@example.com"))
    clock.advance(minutes=31)
    assert api.post("/api/auth/reset", json={"token": token, "password": NEW_PASSWORD}).status_code == 400
    clock.reset()
    assert api.post("/api/auth/reset", json={"token": token, "password": NEW_PASSWORD}).status_code == 200
    assert api.post("/api/auth/reset", json={"token": token, "password": NEW_PASSWORD}).status_code == 400
    login(api, "sam@example.com", NEW_PASSWORD)


def test_reset_with_weak_password_keeps_link_working(api, make_user, mail):
    make_user("sam@example.com")
    api.post("/api/auth/forgot", json={"email": "sam@example.com"})
    token = token_from(mail().last_link("sam@example.com"))
    assert api.post("/api/auth/reset", json={"token": token, "password": "short"}).status_code == 400
    assert api.post("/api/auth/reset", json={"token": token, "password": NEW_PASSWORD}).status_code == 200


def test_reset_ends_other_sessions(api, make_user, mail):
    make_user("sam@example.com")
    login(api, "sam@example.com")
    other = TestClient(api.app)
    api.post("/api/auth/forgot", json={"email": "sam@example.com"})
    other.post("/api/auth/reset", json={"token": token_from(mail().last_link("sam@example.com")), "password": NEW_PASSWORD})
    assert api.get("/api/auth/me").status_code == 401


def test_reset_rate_limit_3_per_hour(api, make_user, mail):
    make_user("sam@example.com")
    for _ in range(5):
        assert api.post("/api/auth/forgot", json={"email": "sam@example.com"}).status_code == 202
    assert len(mail().to("sam@example.com")) == 3


def test_forgot_unknown_email_same_answer(api, make_user, mail):
    make_user("sam@example.com")
    known = api.post("/api/auth/forgot", json={"email": "sam@example.com"})
    unknown = api.post("/api/auth/forgot", json={"email": "ghost@example.com"})
    assert known.json() == unknown.json() and known.status_code == unknown.status_code
    assert mail().to("ghost@example.com") == []


def test_change_password_keeps_this_session_only(api, make_user):
    make_user("sam@example.com")
    other = TestClient(api.app)
    login(other, "sam@example.com")
    login(api, "sam@example.com")
    r = api.post("/api/auth/password", json={"current": GOOD_PASSWORD, "new": NEW_PASSWORD})
    assert r.status_code == 200
    assert api.get("/api/auth/me").status_code == 200
    assert other.get("/api/auth/me").status_code == 401
    assert api.post("/api/auth/password", json={"current": "wrong", "new": NEW_PASSWORD + "!"}).status_code == 400


def test_suspend_kills_sessions(api, db, make_user):
    uid = make_user("sam@example.com")
    login(api, "sam@example.com")
    suspend(db, uid, "user:admin")
    assert api.get("/api/auth/me").status_code == 401


def test_suspended_status_blocks_existing_cookie(api, db, make_user):
    make_user("sam@example.com")
    login(api, "sam@example.com")
    db.execute("UPDATE users SET status = 'suspended'")  # even if sessions were somehow left behind
    assert api.get("/api/auth/me").status_code == 401


def test_password_rehash_on_login(api, db, make_user, monkeypatch):
    from seo_platform.auth import passwords

    make_user("sam@example.com")
    before = db.one("SELECT password_hash FROM users")["password_hash"]
    monkeypatch.setattr(passwords, "needs_rehash", lambda _h: True)
    login(api, "sam@example.com")
    assert db.one("SELECT password_hash FROM users")["password_hash"] != before


def test_new_device_email_after_first_login(api, make_user, mail):
    make_user("sam@example.com")
    login(api, "sam@example.com")  # first login: no alert
    TestClient(api.app, client=("198.51.100.7", 5000)).post(
        "/api/auth/login", json={"email": "sam@example.com", "password": GOOD_PASSWORD})
    subjects = [m["Subject"] for m in mail().to("sam@example.com")]
    assert subjects == ["New sign-in to your account"]


def test_sessions_list_and_end_other(api, make_user):
    make_user("sam@example.com")
    other = TestClient(api.app)
    login(other, "sam@example.com")
    login(api, "sam@example.com")
    listed = api.get("/api/auth/sessions").json()
    assert len(listed) == 2 and sum(s["current"] for s in listed) == 1
    target = next(s for s in listed if not s["current"])
    assert api.delete(f"/api/auth/sessions/{target['id']}").status_code == 200
    assert other.get("/api/auth/me").status_code == 401
    assert api.delete("/api/auth/sessions/not-a-real-id").status_code == 404


def test_last_seen_written_at_most_once_a_minute(api, db, make_user):
    make_user("sam@example.com")
    login(api, "sam@example.com")
    first = db.one("SELECT last_seen_at FROM sessions")["last_seen_at"]
    clock.advance(seconds=30)
    api.get("/api/auth/me")
    assert db.one("SELECT last_seen_at FROM sessions")["last_seen_at"] == first
    clock.advance(seconds=31)
    api.get("/api/auth/me")
    assert db.one("SELECT last_seen_at FROM sessions")["last_seen_at"] != first
