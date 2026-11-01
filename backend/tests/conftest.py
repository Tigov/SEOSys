import os
import sys
import tempfile
from pathlib import Path

# Force test settings even if start.ps1 or .env left other values in this shell.
_PG = "postgresql+psycopg://{user}:{password}@127.0.0.1:5432/seosys_test"
os.environ.update({"APP_ENV": "test",
                   "DATABASE_URL": _PG.format(user="seosys_app", password="seosys_app_local"),
                   "DATABASE_OWNER_URL": _PG.format(user="seosys_owner", password="seosys_owner_local"),
                   "DEMO_SITE_URL": "http://127.0.0.1:8001",
                   "DEMO_SITE_SECRET": "test-secret", "ALLOW_PRIVATE_HOSTS": "true", "SEED_DEMO_CLIENT": "true",
                   "DEMO_SITE_STATE": str(Path(tempfile.gettempdir()) / "seo_poc_test_site_state.json"),
                   "GOOGLE_OAUTH_CLIENT_ID": "test-client.apps.googleusercontent.com",
                   "GOOGLE_OAUTH_CLIENT_SECRET": "test-client-secret",
                   "GOOGLE_OAUTH_REDIRECT_URI": "http://localhost:8000/api/oauth/google/callback",
                   "GOOGLE_PAGESPEED_API_KEY": "test-psi-key"})
for _name in ("ANTHROPIC_API_KEY", "APP_ENCRYPTION_KEY", "APP_ENCRYPTION_KEYS_OLD", "APP_ENCRYPTION_KEY_VERSION"):
    os.environ.pop(_name, None)  # tests always use the offline writer and the development key
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
import psycopg  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from demo_site.app import create_app as create_demo  # noqa: E402
from seo_platform import clock, net  # noqa: E402
from seo_platform.auth import sessions, tokens  # noqa: E402
from seo_platform.api import create_app  # noqa: E402
from seo_platform.config import settings  # noqa: E402
from seo_platform.db import Database  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
# Act as one of the people seeded by the `api` fixture: api.get(url, headers=STAFF). The harness swaps this for that
# person's real session cookie and CSRF token, so tests exercise the same auth path as the browser.
STAFF = {"X-Test-As": "admin"}
CLIENT = {"X-Test-As": "owner"}
MEMBER = {"X-Test-As": "member"}
APPROVER = {"X-Test-As": "approver"}
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def alembic_config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    return cfg


def pytest_sessionstart(session):
    url = settings.database_owner_url.replace("postgresql+psycopg://", "postgresql://")
    try:
        psycopg.connect(url, connect_timeout=3).close()
    except psycopg.OperationalError as exc:
        pytest.exit(f"Postgres is not reachable ({exc}). Start Docker Desktop and run: docker compose up -d --wait", 2)
    command.upgrade(alembic_config(), "head")


@pytest.fixture()
def db():
    database = Database(settings.database_url)
    database.wipe()
    yield database
    database.dispose()


@pytest.fixture(autouse=True)
def _real_time():
    clock.reset()
    yield
    clock.reset()


@pytest.fixture()
def override():
    """Temporarily change frozen settings: override(name=value, ...). Restored after the test."""
    original = {}

    def apply(**values):
        for name, value in values.items():
            original.setdefault(name, getattr(settings, name))
            object.__setattr__(settings, name, value)

    yield apply
    for name, value in original.items():
        object.__setattr__(settings, name, value)


@pytest.fixture()
def demo():
    """Fresh in-memory demo client site; platform HTTP calls are routed to it in-process."""
    demo_app = create_demo(state_path=None, secret=settings.demo_site_secret)
    original = net.transport_factory
    net.transport_factory = lambda: httpx.ASGITransport(app=demo_app)
    yield demo_app
    net.transport_factory = original


class RoleClient(TestClient):
    """TestClient that understands STAFF / CLIENT / MEMBER / APPROVER and adds the CSRF token for its own session."""

    identities: dict[str, tuple[str, str]]

    def request(self, method, url, **kwargs):
        headers = dict(kwargs.pop("headers", None) or {})
        who = headers.pop("X-Test-As", None)
        if who:
            raw, csrf = self.identities[who]
            headers["Cookie"] = f"{sessions.COOKIE}={raw}"
            headers.setdefault("X-CSRF-Token", csrf)
        elif method.upper() in UNSAFE and "X-CSRF-Token" not in headers and self.cookies.get(sessions.COOKIE):
            row = self.app.state.db.one("SELECT csrf_token FROM sessions WHERE id_hash = ?",
                                        (tokens.digest(self.cookies[sessions.COOKIE]),))
            if row:
                headers["X-CSRF-Token"] = row["csrf_token"]
        return super().request(method, url, headers=headers, **kwargs)


def seed_people(db, client_id=1):
    """The agency admin (two-step login done) plus an owner, a member and an approver of the demo client."""
    from seo_platform.auth import passwords

    people = {}
    for who, admin in (("admin", True), ("owner", False), ("member", False), ("approver", False)):
        uid = db.insert("users", {"email": f"{who}@seosys.test", "name": who.title(), "is_admin": admin,
                                  "password_hash": passwords.hash(GOOD_PASSWORD),
                                  "email_verified_at": "2026-01-01T00:00:00+00:00",
                                  **({"totp_secret": "JBSWY3DPEHPK3PXP", "totp_enabled_at": "2026-01-01T00:00:00+00:00"}
                                     if admin else {})})
        if not admin:
            db.insert("memberships", {"user_id": uid, "client_id": client_id, "role": "owner" if who == "owner" else "member",
                                      "can_approve": who == "approver"})
        user = db.one("SELECT * FROM users WHERE id = ?", (uid,))
        raw = sessions.create(db, user, None, "pytest", mfa_passed=True)
        csrf = db.one("SELECT csrf_token FROM sessions WHERE id_hash = ?", (tokens.digest(raw),))["csrf_token"]
        people[who] = (raw, csrf)
    return people


@pytest.fixture()
def bare_api(demo, db):
    """The app with the demo client but no people: for tests about accounts themselves."""
    with RoleClient(create_app(db)) as client:
        client.identities = {}
        yield client


@pytest.fixture()
def api(bare_api, db):
    bare_api.identities = seed_people(db)
    return bare_api


@pytest.fixture()
def audited(api):
    r = api.post("/api/clients/1/audits", headers=STAFF)
    assert r.status_code == 200, r.text
    return api


GOOD_PASSWORD = "purple tractor sings loudly"


@pytest.fixture()
def mail(db):
    """Sends whatever is queued to an in-memory outbox and returns it: out = mail(); out.last_link(email)."""
    from seo_platform import mailer

    box = mailer.Outbox()

    def flush():
        mailer.send_pending(db, box)
        return box

    return flush


@pytest.fixture()
def make_user(db):
    """Create an account directly: make_user("a@example.com", admin=False, verified=True) -> user id."""
    from seo_platform.auth import passwords

    def create(email, password=GOOD_PASSWORD, name="Test User", admin=False, verified=True, status="active"):
        return db.insert("users", {"email": email, "name": name, "password_hash": passwords.hash(password),
                                   "is_admin": admin, "status": status,
                                   "email_verified_at": "2026-01-01T00:00:00+00:00" if verified else None})

    return create


def login(client, email, password=GOOD_PASSWORD):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r
