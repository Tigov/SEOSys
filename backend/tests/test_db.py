"""Data layer on Postgres: binding, transactions, client scoping, type conversion and encryption at rest."""
import psycopg
import pytest

from seo_platform import crypto
from seo_platform.config import settings
from seo_platform.db import now


def _raw(sql: str):
    """Read with the owner role, bypassing the data layer, to see what is really stored."""
    url = settings.database_owner_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn:
        return conn.execute(sql).fetchall()


def test_placeholders_bind_safely(db):
    name = "x'; DROP TABLE clients;--"
    cid = db.create_client(name=name)
    assert db.get_client(cid)["name"] == name


def test_question_mark_and_percent_inside_literals(db):
    assert db.query("SELECT 'a?b%c' AS s WHERE 1 = ?", (1,)) == [{"s": "a?b%c"}]


def test_transaction_rolls_back(db):
    with pytest.raises(RuntimeError):
        with db.transaction():
            db.create_client(name="Rolled back")
            raise RuntimeError("boom")
    assert db.list_clients() == []


def test_nested_transaction_joins_outer(db):
    with db.transaction():
        cid = db.create_client(name="Outer")
        with db.transaction():
            db.for_client(cid).insert("alerts", {"level": "info", "message": "inner", "at": now()})
    assert len(db.for_client(cid).list("alerts")) == 1


def test_repo_cannot_read_other_client(db):
    a, b = db.create_client(name="A"), db.create_client(name="B")
    alert = db.for_client(a).insert("alerts", {"level": "info", "message": "only A", "at": now()})
    assert db.for_client(b).get("alerts", alert) is None
    assert db.for_client(b).list("alerts") == []


def test_unscoped_table_refused(db):
    cid = db.create_client(name="A")
    with pytest.raises(ValueError):
        db.for_client(cid).list("users")


def test_timestamps_are_iso_utc_strings(db):
    cid = db.create_client(name="A")
    created = db.get_client(cid)["created_at"]
    assert isinstance(created, str) and created.endswith("+00:00")


def test_money_is_float_and_flags_are_bool(db):
    cid = db.create_client(name="A", monthly_budget_usd=80, auto_approve_low=1)
    row = db.get_client(cid)
    assert row["monthly_budget_usd"] == 80.0 and isinstance(row["monthly_budget_usd"], float)
    assert row["auto_approve_low"] is True


def test_claim_is_atomic(db):
    cid = db.create_client(name="A")
    repo = db.for_client(cid)
    site = repo.insert("sites", {"base_url": "https://a.example", "cms": "wordpress"})
    cr = repo.insert("change_requests", {"site_id": site, "type": "title", "risk": "low", "status": "approved"})
    assert repo.claim("change_requests", cr, "approved", "deploying") is True
    assert repo.claim("change_requests", cr, "approved", "deploying") is False


def test_secrets_encrypted_at_rest(db):
    cid = db.create_client(name="A")
    db.for_client(cid).insert("sites", {"base_url": "https://a.example", "cms": "wordpress", "adapter_secret": "s3cret"})
    stored = _raw("SELECT adapter_secret FROM sites")[0][0]
    assert stored.startswith("v1:") and "s3cret" not in stored
    assert db.for_client(cid).site()["adapter_secret"] == "s3cret"


def test_crypto_round_trip_and_tamper():
    token = crypto.encrypt("hello")
    assert crypto.decrypt(token) == "hello"
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt(tampered)


def test_crypto_old_key_still_decrypts(override):
    old_key = crypto.generate_key()
    override(encryption_key=old_key, encryption_key_version=1)
    token = crypto.encrypt("rotate me")
    override(encryption_key=crypto.generate_key(), encryption_key_version=2, encryption_keys_old=(f"v1={old_key}",))
    assert crypto.decrypt(token) == "rotate me"
    assert crypto.encrypt("x").startswith("v2:")
