"""Two-step login: setup, codes, replay, recovery codes and the admin requirement."""
import pyotp
import pytest

from seo_platform import clock
from tests.conftest import GOOD_PASSWORD, login


@pytest.fixture()
def api(bare_api):
    """These tests start with no accounts at all."""
    return bare_api


def code_for(secret: str, offset_steps: int = 0) -> str:
    return pyotp.TOTP(secret).at(clock.now().timestamp() + 30 * offset_steps)


@pytest.fixture()
def with_mfa(api, make_user):
    """A signed-in user with two-step login on. Returns (secret, recovery codes)."""
    clock.set(clock.now().replace(microsecond=0))
    make_user("sam@example.com")
    login(api, "sam@example.com")
    secret = api.post("/api/auth/mfa/setup").json()["secret"]
    r = api.post("/api/auth/mfa/enable", json={"code": code_for(secret)})
    assert r.status_code == 200, r.text
    return secret, r.json()["recovery_codes"]


def test_setup_gives_otpauth_uri(api, make_user):
    make_user("sam@example.com")
    login(api, "sam@example.com")
    uri = api.post("/api/auth/mfa/setup").json()["otpauth_uri"]
    assert uri.startswith("otpauth://totp/SEOSys:sam%40example.com?") and "issuer=SEOSys" in uri


def test_enable_returns_ten_recovery_codes_and_emails(with_mfa, mail):
    _, codes = with_mfa
    assert len(codes) == 10 and len(set(codes)) == 10
    assert mail().to("sam@example.com")[-1]["Subject"] == "Two-step login was turned on"


def test_secret_encrypted_at_rest(with_mfa, db):
    from tests.test_db import _raw
    stored = _raw("SELECT totp_secret FROM users")[0][0]
    assert stored.startswith("v1:") and stored != with_mfa[0]


def test_login_requires_code_after_enable(api, with_mfa):
    secret, _ = with_mfa
    api.post("/api/auth/logout")
    assert login(api, "sam@example.com").json() == {"mfa_required": True}
    assert api.get("/api/auth/me").json()["gate"] == "mfa_required"
    clock.advance(seconds=30)
    assert api.post("/api/auth/mfa/verify", json={"code": code_for(secret)}).status_code == 200
    me = api.get("/api/auth/me").json()
    assert me["mfa_passed"] is True and me["gate"] is None


def test_code_replay_rejected(api, with_mfa):
    secret, _ = with_mfa
    api.post("/api/auth/logout")
    login(api, "sam@example.com")
    used_at_enable = code_for(secret)  # the enable step already used this time step
    assert api.post("/api/auth/mfa/verify", json={"code": used_at_enable}).status_code == 401
    clock.advance(seconds=30)
    fresh = code_for(secret)
    assert api.post("/api/auth/mfa/verify", json={"code": fresh}).status_code == 200
    api.post("/api/auth/logout")
    login(api, "sam@example.com")
    assert api.post("/api/auth/mfa/verify", json={"code": fresh}).status_code == 401


def test_window_plus_minus_one_step(api, with_mfa):
    secret, _ = with_mfa
    clock.advance(seconds=90)
    api.post("/api/auth/logout")
    login(api, "sam@example.com")
    assert api.post("/api/auth/mfa/verify", json={"code": code_for(secret, 2)}).status_code == 401  # too far ahead
    assert api.post("/api/auth/mfa/verify", json={"code": code_for(secret, 1)}).status_code == 200


def test_wrong_codes_lock_after_5(api, with_mfa):
    secret, _ = with_mfa
    api.post("/api/auth/logout")
    login(api, "sam@example.com")
    for _ in range(5):
        api.post("/api/auth/mfa/verify", json={"code": "000000"})
    clock.advance(seconds=30)
    assert api.post("/api/auth/mfa/verify", json={"code": code_for(secret)}).status_code == 429


def test_recovery_code_single_use(api, with_mfa):
    _, codes = with_mfa
    api.post("/api/auth/logout")
    login(api, "sam@example.com")
    r = api.post("/api/auth/mfa/recovery", json={"code": codes[0].upper()})
    assert r.status_code == 200 and r.json()["codes_left"] == 9
    api.post("/api/auth/logout")
    login(api, "sam@example.com")
    assert api.post("/api/auth/mfa/recovery", json={"code": codes[0]}).status_code == 401


def test_session_rotates_when_mfa_passes(api, with_mfa):
    secret, _ = with_mfa
    api.post("/api/auth/logout")
    before = login(api, "sam@example.com").cookies["seosys_session"]
    clock.advance(seconds=30)
    after = api.post("/api/auth/mfa/verify", json={"code": code_for(secret)}).cookies["seosys_session"]
    assert before != after


def test_disable_needs_password_or_code(api, with_mfa, mail):
    secret, _ = with_mfa
    assert api.post("/api/auth/mfa/disable", json={"password": "wrong"}).status_code == 401
    assert api.post("/api/auth/mfa/disable", json={"password": GOOD_PASSWORD}).status_code == 200
    assert api.get("/api/auth/me").json()["user"]["totp_enabled"] is False
    assert mail().to("sam@example.com")[-1]["Subject"] == "Two-step login was turned off"


def test_regenerate_codes_replaces_old_ones(api, with_mfa):
    _, old = with_mfa
    new = api.post("/api/auth/mfa/recovery-codes", json={"password": GOOD_PASSWORD}).json()["recovery_codes"]
    assert set(new).isdisjoint(old)
    api.post("/api/auth/logout")
    login(api, "sam@example.com")
    assert api.post("/api/auth/mfa/recovery", json={"code": old[0]}).status_code == 401
    assert api.post("/api/auth/mfa/recovery", json={"code": new[0]}).status_code == 200


def test_admin_must_set_up_mfa(api, make_user):
    make_user("admin@example.com", admin=True)
    login(api, "admin@example.com")
    assert api.get("/api/auth/me").json()["gate"] == "mfa_setup_required"


def test_admin_cannot_disable_mfa(api, make_user):
    make_user("admin@example.com", admin=True)
    login(api, "admin@example.com")
    secret = api.post("/api/auth/mfa/setup").json()["secret"]
    api.post("/api/auth/mfa/enable", json={"code": code_for(secret)})
    assert api.post("/api/auth/mfa/disable", json={"password": GOOD_PASSWORD}).status_code == 403
