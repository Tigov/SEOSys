"""Postgres persistence.

Every client-owned table carries client_id and all client access goes through `ClientRepo`, which filters by
the client it was created for and runs each statement with `app.client_id` set, so row-level security (a
second, database-side lock) only shows that client's rows. Agency-level code uses `Database` directly, which
runs with `app.scope = 'system'`.

Queries use `?` placeholders; values are always sent to Postgres as bound parameters, never pasted into SQL.
Single statements commit on their own. Wrap multi-step writes in `with db.transaction():`. Never hold a
transaction open across a call to an outside service.
"""
from __future__ import annotations

import ipaddress
import json
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Iterator

from psycopg.types.json import Jsonb
from sqlalchemy import Boolean, create_engine
from sqlalchemy.engine import Connection

from . import clock, crypto
from .config import settings
from .schema import CLIENT_TABLES, ENCRYPTED, JSON_COLUMNS, metadata

ENCRYPTED_NAMES = frozenset(col for _, col in ENCRYPTED)
_BOOL_COLUMNS = {(t.name, c.name) for t in metadata.tables.values() for c in t.columns if isinstance(c.type, Boolean)}
_HAS_ID = {t.name for t in metadata.tables.values() if "id" in t.c and t.c.id.identity is not None}


def now() -> str:
    return clock.now().isoformat(timespec="seconds")


def to_sql(sql: str) -> str:
    """Turn `?` placeholders into psycopg's `%s`, leaving quoted literals untouched and escaping literal `%`."""
    out, quote = [], ""
    for ch in sql:
        if quote:
            out.append("%%" if ch == "%" else ch)
            if ch == quote:
                quote = ""
        elif ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == "?":
            out.append("%s")
        elif ch == "%":
            out.append("%%")
        else:
            out.append(ch)
    return "".join(out)


def _param(value: Any) -> Any:
    return Jsonb(value) if isinstance(value, (dict, list)) else value


def _decode_value(key: str, val: Any) -> Any:
    if isinstance(val, datetime):
        return val.astimezone(timezone.utc).isoformat(timespec="seconds")
    if isinstance(val, date):
        return val.isoformat()
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        return str(val)
    if key in ENCRYPTED_NAMES and crypto.is_encrypted(val):
        return crypto.decrypt(val)
    return val


def _decode(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: _decode_value(key, val) for key, val in row._mapping.items()}


def _encode(table: str, values: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in values.items():
        if (table, key) in JSON_COLUMNS and isinstance(val, str):
            val = json.loads(val)
        if (table, key) in _BOOL_COLUMNS and isinstance(val, int):
            val = bool(val)
        if (table, key) in ENCRYPTED and val is not None and not crypto.is_encrypted(val):
            val = crypto.encrypt(str(val))
        out[key] = _param(val)
    return out


def _check_identifier(name: str) -> str:
    if name not in metadata.tables and not name.isidentifier():
        raise ValueError(f"Unsafe identifier: {name}")
    return name


@dataclass(frozen=True)
class Result:
    rows: list[Any]
    rowcount: int

    def fetchall(self) -> list[Any]:
        return self.rows

    def fetchone(self) -> Any:
        return self.rows[0] if self.rows else None

    def scalar_one(self) -> Any:
        return self.rows[0][0]


class Database:
    def __init__(self, url: str | None = None) -> None:
        self.url = url or settings.database_url
        self.engine = create_engine(self.url, pool_size=settings.db_pool_size, max_overflow=settings.db_pool_size,
                                    pool_pre_ping=True)
        self._tx: ContextVar[Connection | None] = ContextVar(f"tx_{id(self)}", default=None)

    def dispose(self) -> None:
        self.engine.dispose()

    # ---- execution ----
    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        """One atomic unit. Nested calls join the outer transaction."""
        current = self._tx.get()
        if current is not None:
            yield current
            return
        with self.engine.begin() as conn:
            token = self._tx.set(conn)
            try:
                yield conn
            finally:
                self._tx.reset(token)

    def run(self, sql: str, params: Iterable[Any] = (), client_id: int | None = None) -> Result:
        """Execute one statement with the row-level-security scope set; rows are fetched before returning."""
        scope = ("", str(client_id)) if client_id is not None else ("system", "")
        with self.transaction() as conn:
            conn.exec_driver_sql("SELECT set_config('app.scope', %s, true), set_config('app.client_id', %s, true)", scope)
            result = conn.exec_driver_sql(to_sql(sql), tuple(_param(p) for p in params))
            return Result(result.fetchall() if result.returns_rows else [], result.rowcount)

    # ---- low-level helpers (agency scope) ----
    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        return [_decode(r) for r in self.run(sql, params).fetchall()]  # type: ignore[misc]

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        return _decode(self.run(sql, params).fetchone())

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        return self.run(sql, params).rowcount

    def insert(self, table: str, values: dict[str, Any], client_id: int | None = None) -> int:
        vals = _encode(_check_identifier(table), values)
        cols = ", ".join(_check_identifier(k) for k in vals)
        marks = ", ".join("?" for _ in vals)
        returning = " RETURNING id" if table in _HAS_ID else ""
        result = self.run(f"INSERT INTO {table} ({cols}) VALUES ({marks}){returning}", tuple(vals.values()), client_id)
        return int(result.scalar_one()) if returning else 0

    def update_row(self, table: str, where: str, where_params: Iterable[Any], values: dict[str, Any],
                   client_id: int | None = None) -> int:
        vals = _encode(_check_identifier(table), values)
        sets = ", ".join(f"{_check_identifier(k)} = ?" for k in vals)
        return self.run(f"UPDATE {table} SET {sets} WHERE {where}", (*vals.values(), *where_params), client_id).rowcount

    def wipe(self) -> None:
        """Empty every table (tests and the local demo reset only). Needs the owner role."""
        tables = ", ".join(metadata.tables)
        owner = create_engine(settings.database_owner_url)
        try:
            with owner.begin() as conn:
                conn.exec_driver_sql(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")
        finally:
            owner.dispose()

    # ---- cross-client (agency-level) operations ----
    def list_clients(self) -> list[dict[str, Any]]:
        return self.query("SELECT * FROM clients ORDER BY id")

    def get_client(self, client_id: int) -> dict[str, Any] | None:
        return self.one("SELECT * FROM clients WHERE id = ?", (client_id,))

    def create_client(self, **values: Any) -> int:
        return self.insert("clients", values)

    def for_client(self, client_id: int) -> "ClientRepo":
        if self.get_client(client_id) is None:
            raise LookupError(f"Client {client_id} was not found.")
        return ClientRepo(self, client_id)

    def log(self, client_id: int | None, actor: str, action: str, target: str = "", detail: dict[str, Any] | None = None,
            **extra: Any) -> None:
        self.insert("audit_events", {"client_id": client_id, "actor": actor, "action": action, "target": target,
                                     "detail": detail or {}, "at": now(), **extra})

    # ---- OAuth sign-in handshakes (keyed by an unguessable state, not by client) ----
    def save_oauth_state(self, **values: Any) -> None:
        self.insert("oauth_states", {**values, "created_at": now()})

    def take_oauth_state(self, state: str, max_age_seconds: int) -> dict[str, Any] | None:
        """Return and delete a pending sign-in in one step, so a state can be used once. None if unknown or too old."""
        row = _decode(self.run("DELETE FROM oauth_states WHERE state = ? RETURNING *", (state,)).fetchone())
        if row is None:
            return None
        age = clock.now() - datetime.fromisoformat(row["created_at"])
        return row if age.total_seconds() <= max_age_seconds else None


class ClientRepo:
    """All reads and writes for one client. Every statement is filtered by client_id."""

    def __init__(self, db: Database, client_id: int) -> None:
        self.db = db
        self.client_id = client_id

    def _check(self, table: str) -> None:
        if table not in CLIENT_TABLES:
            raise ValueError(f"table not client-scoped: {table}")

    def _run(self, sql: str, params: Iterable[Any] = ()) -> Any:
        return self.db.run(sql, params, client_id=self.client_id)

    def client(self) -> dict[str, Any]:
        row = self.db.get_client(self.client_id)
        assert row is not None
        return row

    def update_client(self, **values: Any) -> None:
        self.db.update_row("clients", "id = ?", (self.client_id,), values)

    def insert(self, table: str, values: dict[str, Any]) -> int:
        self._check(table)
        return self.db.insert(table, {**values, "client_id": self.client_id}, client_id=self.client_id)

    def get(self, table: str, row_id: int) -> dict[str, Any] | None:
        self._check(table)
        return _decode(self._run(f"SELECT * FROM {table} WHERE id = ? AND client_id = ?", (row_id, self.client_id)).fetchone())

    def list(self, table: str, where: str = "", params: Iterable[Any] = (), order: str = "id") -> list[dict[str, Any]]:
        self._check(table)
        clause = f" AND ({where})" if where else ""
        rows = self._run(f"SELECT * FROM {table} WHERE client_id = ?{clause} ORDER BY {order}", (self.client_id, *params))
        return [_decode(r) for r in rows.fetchall()]  # type: ignore[misc]

    def update(self, table: str, row_id: int, **values: Any) -> None:
        self._check(table)
        self.db.update_row(table, "id = ? AND client_id = ?", (row_id, self.client_id), values, client_id=self.client_id)

    def site(self) -> dict[str, Any]:
        """Full site row, including the adapter secret. Only for server-side use (adapters)."""
        sites = self.list("sites")
        if not sites:
            raise LookupError("This client has no website connected.")
        return sites[0]

    def public_site(self) -> dict[str, Any]:
        """Site row safe to return to any caller: the signing secret is removed."""
        return {k: v for k, v in self.site().items() if k != "adapter_secret"}

    def claim(self, table: str, row_id: int, from_status: str, to_status: str, **values: Any) -> bool:
        """Atomically move a row from one status to another. False if another request got there first."""
        self._check(table)
        changed = self.db.update_row(table, "id = ? AND client_id = ? AND status = ?", (row_id, self.client_id, from_status),
                                     {"status": to_status, **values}, client_id=self.client_id)
        return changed == 1

    def latest_crawl(self, kinds: tuple[str, ...] = ("audit",)) -> dict[str, Any] | None:
        marks = ",".join("?" for _ in kinds)
        rows = self.list("crawls", f"kind IN ({marks}) AND finished_at IS NOT NULL", kinds, order="id DESC")
        return rows[0] if rows else None

    def log(self, actor: str, action: str, target: str = "", detail: dict[str, Any] | None = None, **extra: Any) -> None:
        self.insert("audit_events", {"actor": actor, "action": action, "target": target, "detail": detail or {},
                                     "at": now(), **extra})

    def meter(self, vendor: str, unit: str, qty: float, cost_usd: float) -> None:
        self.insert("usage_events", {"vendor": vendor, "unit": unit, "qty": qty, "cost_usd": cost_usd, "at": now()})

    def month_spend(self) -> float:
        start = clock.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        row = _decode(self._run("SELECT COALESCE(SUM(cost_usd), 0) AS s FROM usage_events WHERE client_id = ? AND at >= ?",
                                (self.client_id, start)).fetchone())
        return float(row["s"]) if row else 0.0

    def alert(self, level: str, message: str) -> None:
        self.insert("alerts", {"level": level, "message": message, "at": now()})
