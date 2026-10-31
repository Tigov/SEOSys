import os
import sys
import tempfile
from pathlib import Path

# Force test settings even if start.ps1 or .env left other values in this shell.
os.environ.update({"SEO_DB_PATH": ":memory:", "DEMO_SITE_URL": "http://127.0.0.1:8001",
                   "DEMO_SITE_SECRET": "test-secret", "ALLOW_PRIVATE_HOSTS": "true", "SEED_DEMO_CLIENT": "true",
                   "DEMO_SITE_STATE": str(Path(tempfile.gettempdir()) / "seo_poc_test_site_state.json"),
                   "GOOGLE_OAUTH_CLIENT_ID": "test-client.apps.googleusercontent.com",
                   "GOOGLE_OAUTH_CLIENT_SECRET": "test-client-secret",
                   "GOOGLE_OAUTH_REDIRECT_URI": "http://localhost:8000/api/oauth/google/callback",
                   "GOOGLE_PAGESPEED_API_KEY": "test-psi-key"})
os.environ.pop("ANTHROPIC_API_KEY", None)  # tests always use the offline writer
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from demo_site.app import create_app as create_demo  # noqa: E402
from seo_platform import net  # noqa: E402
from seo_platform.api import create_app  # noqa: E402
from seo_platform.config import settings  # noqa: E402
from seo_platform.db import Database  # noqa: E402

STAFF = {"X-Role": "staff", "X-Actor": "staff:test"}
CLIENT = {"X-Role": "client", "X-Actor": "client:owner"}


@pytest.fixture()
def demo():
    """Fresh in-memory demo client site; platform HTTP calls are routed to it in-process."""
    demo_app = create_demo(state_path=None, secret=settings.demo_site_secret)
    original = net.transport_factory
    net.transport_factory = lambda: httpx.ASGITransport(app=demo_app)
    yield demo_app
    net.transport_factory = original


@pytest.fixture()
def api(demo):
    app = create_app(Database(":memory:"))
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def audited(api):
    r = api.post("/api/clients/1/audits", headers=STAFF)
    assert r.status_code == 200, r.text
    return api
