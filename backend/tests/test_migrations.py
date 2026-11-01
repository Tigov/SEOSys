"""Migrations: reversible, in step with schema.py, and enforcing the rules the database owns."""
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError

from seo_platform.config import settings
from seo_platform.schema import metadata
from tests.conftest import alembic_config


def test_upgrade_downgrade_upgrade():
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


def test_schema_matches_metadata():
    engine = create_engine(settings.database_owner_url)
    try:
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_server_default": True}), metadata)
    finally:
        engine.dispose()
    assert diff == []


def test_one_owner_per_client(db):
    cid = db.create_client(name="A")
    a = db.insert("users", {"email": "a@example.com"})
    b = db.insert("users", {"email": "b@example.com"})
    db.insert("memberships", {"user_id": a, "client_id": cid, "role": "owner"})
    with pytest.raises(IntegrityError):
        db.insert("memberships", {"user_id": b, "client_id": cid, "role": "owner"})
    db.insert("memberships", {"user_id": b, "client_id": cid, "role": "member"})


def test_email_must_be_lowercase(db):
    with pytest.raises(IntegrityError):
        db.insert("users", {"email": "Mixed@Example.com"})


def test_unknown_status_rejected(db):
    with pytest.raises(IntegrityError):
        db.create_client(name="A", status="paused")


def test_app_role_cannot_rewrite_audit_log(db):
    db.log(None, "system", "test.event")
    with pytest.raises(Exception, match="permission denied"):
        db.execute("UPDATE audit_events SET action = 'tampered'")
    with pytest.raises(Exception, match="permission denied"):
        db.execute("DELETE FROM audit_events")
