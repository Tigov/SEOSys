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
from seo_platform.api import create_app  # noqa: E402
from seo_platform.config import settings  # noqa: E402
from seo_platform.db import Database  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
STAFF = {"X-Role": "staff", "X-Actor": "staff:test"}
CLIENT = {"X-Role": "client", "X-Actor": "client:owner"}


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


@pytest.fixture()
def api(demo, db):
    app = create_app(db)
    with TestClient(app) as client:
        yield client


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
