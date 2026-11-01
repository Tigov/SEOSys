"""Row-level security: the database itself keeps one client's rows away from another."""
import psycopg
import pytest

from seo_platform.config import settings
from seo_platform.db import now
from seo_platform.schema import CLIENT_TABLES


def app_conn():
    return psycopg.connect(settings.database_url.replace("postgresql+psycopg://", "postgresql://"), autocommit=True)


@pytest.fixture()
def two_clients(db):
    a, b = db.create_client(name="A"), db.create_client(name="B")
    for cid in (a, b):
        db.for_client(cid).insert("alerts", {"level": "info", "message": f"for {cid}", "at": now()})
    return a, b


def test_app_role_without_setting_sees_nothing(two_clients):
    with app_conn() as conn:
        assert conn.execute("SELECT count(*) FROM alerts").fetchone()[0] == 0


def test_app_role_sees_only_its_client(two_clients):
    a, _ = two_clients
    with app_conn() as conn:
        conn.execute("SELECT set_config('app.client_id', %s, false)", (str(a),))
        rows = conn.execute("SELECT client_id FROM alerts").fetchall()
    assert rows == [(a,)]


def test_system_scope_sees_all(two_clients):
    with app_conn() as conn:
        conn.execute("SELECT set_config('app.scope', 'system', false)")
        assert conn.execute("SELECT count(*) FROM alerts").fetchone()[0] == 2


def test_cannot_write_into_another_client(two_clients):
    a, b = two_clients
    with app_conn() as conn:
        conn.execute("SELECT set_config('app.client_id', %s, false)", (str(a),))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("INSERT INTO alerts (client_id, level, message) VALUES (%s, 'info', 'sneaky')", (b,))
        assert conn.execute("UPDATE alerts SET message = 'x' WHERE client_id = %s", (b,)).rowcount == 0


def test_every_client_table_has_row_level_security(db):
    rows = db.query("SELECT c.relname AS name, c.relrowsecurity AS rls FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind = 'r'")
    protected = {r["name"] for r in rows if r["rls"]}
    assert protected == set(CLIENT_TABLES)


def test_client_repo_still_works_under_rls(two_clients, db):
    a, b = two_clients
    assert [r["message"] for r in db.for_client(a).list("alerts")] == [f"for {a}"]
    assert db.for_client(b).get("alerts", 1) is None
