"""SQLite persistence for the proof of concept.

Production target (TDD section 5) is Postgres with row-level security. Here every
client-owned table carries client_id and all access goes through `ClientRepo`,
which always filters by the client it was created for. Tests assert that one
client can never read another client's rows.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, city TEXT, region TEXT, phone TEXT, street TEXT, postal_code TEXT,
  services TEXT DEFAULT '[]', competitors TEXT DEFAULT '[]',
  auto_approve_low INTEGER DEFAULT 0, freeze_deploys INTEGER DEFAULT 0,
  monthly_budget_usd REAL DEFAULT 80, created_at TEXT
);
CREATE TABLE IF NOT EXISTS sites (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id),
  base_url TEXT NOT NULL, cms TEXT NOT NULL, adapter_secret TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS leads (
  id INTEGER PRIMARY KEY, url TEXT, email TEXT, business_name TEXT, city TEXT,
  score INTEGER, result TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS crawls (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL, site_id INTEGER, kind TEXT,
  started_at TEXT, finished_at TEXT, pages_crawled INTEGER, health_score INTEGER,
  robots_txt TEXT, ai_bots_blocked TEXT DEFAULT '[]', sitemap_urls TEXT DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS pages (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL, crawl_id INTEGER NOT NULL,
  url TEXT, path TEXT, status INTEGER, final_url TEXT, redirect_chain TEXT DEFAULT '[]',
  title TEXT, meta_description TEXT, h1s TEXT DEFAULT '[]', canonical TEXT, noindex INTEGER,
  word_count INTEGER, images TEXT DEFAULT '[]', links TEXT DEFAULT '[]', jsonld_types TEXT DEFAULT '[]',
  in_sitemap INTEGER
);
CREATE TABLE IF NOT EXISTS findings (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL, crawl_id INTEGER, fingerprint TEXT,
  rule_id TEXT, severity TEXT, title TEXT, urls TEXT DEFAULT '[]', evidence TEXT DEFAULT '{}',
  effort TEXT, impact INTEGER, fix_hint TEXT, fix_type TEXT, status TEXT DEFAULT 'open',
  first_seen TEXT, last_seen TEXT, resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS change_requests (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL, site_id INTEGER NOT NULL, finding_id INTEGER,
  type TEXT, target TEXT, before_value TEXT, after_value TEXT, risk TEXT, status TEXT,
  reason TEXT, author TEXT, approved_by TEXT, deploy_result TEXT, verification TEXT,
  policy_flags TEXT DEFAULT '[]', created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY, client_id INTEGER, actor TEXT, action TEXT, target TEXT,
  detail TEXT DEFAULT '{}', at TEXT
);
CREATE TABLE IF NOT EXISTS usage_events (
  id INTEGER PRIMARY KEY, client_id INTEGER, vendor TEXT, unit TEXT, qty REAL, cost_usd REAL, at TEXT
);
CREATE TABLE IF NOT EXISTS prompts (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL, text TEXT, cluster TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS ai_observations (
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL, prompt_id INTEGER, run_no INTEGER,
  engine TEXT, method TEXT, run_at TEXT, mentioned INTEGER, position INTEGER, cited_url TEXT,
  brands TEXT DEFAULT '[]', sources TEXT DEFAULT '[]', answer TEXT
);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY, client_id INTEGER, level TEXT, message TEXT, at TEXT, acknowledged INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_pages_crawl ON pages(client_id, crawl_id);
CREATE INDEX IF NOT EXISTS ix_findings_client ON findings(client_id, status);
CREATE INDEX IF NOT EXISTS ix_changes_client ON change_requests(client_id, status);
CREATE INDEX IF NOT EXISTS ix_obs_client ON ai_observations(client_id, run_no);
"""

JSON_COLUMNS = {
    "services", "competitors", "result", "ai_bots_blocked", "sitemap_urls", "redirect_chain", "h1s", "images",
    "links", "jsonld_types", "urls", "evidence", "target", "deploy_result", "verification", "policy_flags",
    "detail", "brands", "sources",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out: dict[str, Any] = {}
    for key in row.keys():
        val = row[key]
        if key in JSON_COLUMNS and isinstance(val, str):
            try:
                val = json.loads(val)
            except json.JSONDecodeError:
                pass
        out[key] = val
    return out


def _encode(values: dict[str, Any]) -> dict[str, Any]:
    return {k: (json.dumps(v) if k in JSON_COLUMNS and not isinstance(v, str) else v) for k, v in values.items()}


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---- low-level helpers ----
    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [_decode(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]  # type: ignore[misc]

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        with self._lock:
            return _decode(self.conn.execute(sql, tuple(params)).fetchone())

    def insert(self, table: str, values: dict[str, Any]) -> int:
        vals = _encode(values)
        cols = ", ".join(vals)
        marks = ", ".join("?" for _ in vals)
        with self._lock:
            cur = self.conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(vals.values()))
            self.conn.commit()
            return int(cur.lastrowid)

    def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self._lock:
            self.conn.execute(sql, tuple(params))
            self.conn.commit()

    def wipe(self) -> None:
        with self._lock:
            for (name,) in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                self.conn.execute(f"DELETE FROM {name}")
            self.conn.commit()

    # ---- cross-client (agency-level) operations ----
    def list_clients(self) -> list[dict[str, Any]]:
        return self.query("SELECT * FROM clients ORDER BY id")

    def get_client(self, client_id: int) -> dict[str, Any] | None:
        return self.one("SELECT * FROM clients WHERE id = ?", (client_id,))

    def create_client(self, **values: Any) -> int:
        values.setdefault("created_at", now())
        return self.insert("clients", values)

    def for_client(self, client_id: int) -> "ClientRepo":
        if self.get_client(client_id) is None:
            raise LookupError(f"Client {client_id} was not found.")
        return ClientRepo(self, client_id)

    def log(self, client_id: int | None, actor: str, action: str, target: str = "", detail: dict[str, Any] | None = None) -> None:
        self.insert("audit_events", {"client_id": client_id, "actor": actor, "action": action, "target": target,
                                     "detail": detail or {}, "at": now()})


ALLOWED_TABLES = {"sites", "crawls", "pages", "findings", "change_requests", "audit_events", "usage_events",
                  "prompts", "ai_observations", "alerts"}


class ClientRepo:
    """All reads and writes for one client. Every statement is filtered by client_id."""

    def __init__(self, db: Database, client_id: int) -> None:
        self.db = db
        self.client_id = client_id

    def _check(self, table: str) -> None:
        if table not in ALLOWED_TABLES:
            raise ValueError(f"table not client-scoped: {table}")

    def client(self) -> dict[str, Any]:
        row = self.db.get_client(self.client_id)
        assert row is not None
        return row

    def update_client(self, **values: Any) -> None:
        vals = _encode(values)
        sets = ", ".join(f"{k} = ?" for k in vals)
        self.db.execute(f"UPDATE clients SET {sets} WHERE id = ?", (*vals.values(), self.client_id))

    def insert(self, table: str, values: dict[str, Any]) -> int:
        self._check(table)
        return self.db.insert(table, {**values, "client_id": self.client_id})

    def get(self, table: str, row_id: int) -> dict[str, Any] | None:
        self._check(table)
        return self.db.one(f"SELECT * FROM {table} WHERE id = ? AND client_id = ?", (row_id, self.client_id))

    def list(self, table: str, where: str = "", params: Iterable[Any] = (), order: str = "id") -> list[dict[str, Any]]:
        self._check(table)
        clause = f" AND ({where})" if where else ""
        return self.db.query(f"SELECT * FROM {table} WHERE client_id = ?{clause} ORDER BY {order}",
                             (self.client_id, *params))

    def update(self, table: str, row_id: int, **values: Any) -> None:
        self._check(table)
        vals = _encode(values)
        sets = ", ".join(f"{k} = ?" for k in vals)
        self.db.execute(f"UPDATE {table} SET {sets} WHERE id = ? AND client_id = ?", (*vals.values(), row_id, self.client_id))

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
        vals = _encode({"status": to_status, **values})
        sets = ", ".join(f"{k} = ?" for k in vals)
        with self.db._lock:
            cur = self.db.conn.execute(
                f"UPDATE {table} SET {sets} WHERE id = ? AND client_id = ? AND status = ?",
                (*vals.values(), row_id, self.client_id, from_status))
            self.db.conn.commit()
            return cur.rowcount == 1

    def latest_crawl(self, kinds: tuple[str, ...] = ("audit",)) -> dict[str, Any] | None:
        marks = ",".join("?" for _ in kinds)
        rows = self.list("crawls", f"kind IN ({marks}) AND finished_at IS NOT NULL", kinds, order="id DESC")
        return rows[0] if rows else None

    def log(self, actor: str, action: str, target: str = "", detail: dict[str, Any] | None = None) -> None:
        self.db.log(self.client_id, actor, action, target, detail)

    def meter(self, vendor: str, unit: str, qty: float, cost_usd: float) -> None:
        self.insert("usage_events", {"vendor": vendor, "unit": unit, "qty": qty, "cost_usd": cost_usd, "at": now()})

    def month_spend(self) -> float:
        month = now()[:7]
        row = self.db.one("SELECT COALESCE(SUM(cost_usd), 0) AS s FROM usage_events WHERE client_id = ? AND substr(at, 1, 7) = ?",
                          (self.client_id, month))
        return float(row["s"]) if row else 0.0

    def alert(self, level: str, message: str) -> None:
        self.insert("alerts", {"level": level, "message": message, "at": now()})
