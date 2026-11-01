"""Security headers, health checks, production start-up checks and logging."""
import json
import logging

import pytest
from alembic.script import ScriptDirectory

from seo_platform import api as api_module
from seo_platform.config import Settings, production_problems
from seo_platform.middleware import JsonFormatter
from tests.conftest import STAFF, alembic_config


def test_security_headers_present(api):
    r = api.get("/api/plans")
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp and "script-src 'self';" in csp
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert r.headers["cache-control"] == "no-store" and len(r.headers["x-request-id"]) == 32
    assert "strict-transport-security" not in r.headers  # only in production, behind HTTPS


def test_hsts_in_production(api, override):
    override(app_env="production")
    assert "max-age" in api.get("/api/plans").headers["strict-transport-security"]


def test_error_responses_get_headers_too(api):
    r = api.patch("/api/clients/1/settings", json={}, headers={**STAFF, "X-CSRF-Token": "wrong"})
    assert r.status_code == 403 and r.headers["x-frame-options"] == "DENY"


def test_request_id_is_echoed_when_safe(api):
    assert api.get("/healthz", headers={"X-Request-ID": "abc-123"}).headers["x-request-id"] == "abc-123"
    assert api.get("/healthz", headers={"X-Request-ID": "<script>"}).headers["x-request-id"] != "<script>"


def test_healthz_and_readyz(api):
    assert api.get("/healthz").json() == {"ok": True}
    ready = api.get("/readyz")
    assert ready.status_code == 200 and ready.json()["schema"] == api_module.HEAD_REVISION


def test_readyz_fails_when_schema_is_behind(api, db):
    from seo_platform.db import Database
    from seo_platform.config import settings
    owner = Database(settings.database_owner_url)
    try:
        owner.execute("UPDATE alembic_version SET version_num = '0002'")
        assert api.get("/readyz").status_code == 503
    finally:
        owner.execute("UPDATE alembic_version SET version_num = ?", (api_module.HEAD_REVISION,))
        owner.dispose()


def test_head_revision_matches_migrations():
    assert ScriptDirectory.from_config(alembic_config()).get_current_head() == api_module.HEAD_REVISION


def test_production_refuses_example_settings(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    problems = production_problems(Settings())
    assert any("DATABASE_URL" in p for p in problems) and any("APP_ENCRYPTION_KEY" in p for p in problems)
    assert any("https://" in p for p in problems) and any("ALLOW_PRIVATE_HOSTS" in p for p in problems)


def test_production_requires_https_base_url(monkeypatch):
    good = {"APP_ENV": "production", "DATABASE_URL": "postgresql+psycopg://app:s3cret@db.internal:5432/seosys",
            "APP_ENCRYPTION_KEY": "q" * 43 + "=", "APP_BASE_URL": "https://app.seosys.com", "ALLOW_PRIVATE_HOSTS": "false",
            "DEMO_SITE_SECRET": "not-the-default", "SMTP_HOST": "smtp.example.com", "SMTP_TLS": "true",
            "STRIPE_SECRET_KEY": "sk_live_x", "STRIPE_WEBHOOK_SECRET": "whsec_x"}
    for k, v in good.items():
        monkeypatch.setenv(k, v)
    assert production_problems(Settings()) == []
    monkeypatch.setenv("APP_BASE_URL", "http://app.seosys.com")
    assert production_problems(Settings()) == ["APP_BASE_URL must start with https://."]


def test_app_will_not_start_in_production_with_problems(override, db):
    override(app_env="production")
    with pytest.raises(RuntimeError, match="Refusing to start"):
        api_module.create_app(db)


def test_docs_hidden_in_production(override, db, demo, monkeypatch):
    from fastapi.testclient import TestClient
    override(app_env="production")
    monkeypatch.setattr(api_module, "production_problems", lambda _s: [])
    with TestClient(api_module.create_app(db)) as client:
        assert client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404
        assert client.post("/api/demo/reset", json={}).status_code in (404, 405)


def test_logs_are_json_and_never_contain_the_session_cookie(api, caplog):
    caplog.set_level(logging.INFO, logger="seo_platform.http")
    raw = api.identities["owner"][0]
    api.get("/api/clients/1", headers={"X-Test-As": "owner"})
    lines = [JsonFormatter().format(r) for r in caplog.records]
    assert lines and all(json.loads(line)["request_id"] for line in lines)
    assert not any(raw in line for line in lines)
