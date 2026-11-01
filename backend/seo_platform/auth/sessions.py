"""Database-backed sessions. The browser holds a random token in an HttpOnly cookie; only its hash is stored."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .. import clock
from ..config import settings
from ..db import Database
from . import tokens

COOKIE = "seosys_session"
IDLE = timedelta(hours=12)
ABSOLUTE = timedelta(days=30)
ADMIN_ABSOLUTE = timedelta(hours=8)
TOUCH_EVERY = timedelta(minutes=1)


@dataclass(frozen=True)
class Principal:
    user_id: int
    email: str
    name: str
    is_admin: bool
    email_verified: bool
    totp_enabled: bool
    mfa_passed: bool
    session_hash: str
    csrf_token: str


def lifetime(is_admin: bool) -> timedelta:
    return ADMIN_ABSOLUTE if is_admin else ABSOLUTE


def create(db: Database, user: dict[str, Any], ip: str | None, user_agent: str, mfa_passed: bool) -> str:
    raw = tokens.new()
    db.insert("sessions", {"id_hash": tokens.digest(raw), "user_id": user["id"], "csrf_token": tokens.new(),
                           "mfa_passed": mfa_passed, "created_at": clock.now(), "last_seen_at": clock.now(),
                           "expires_at": clock.now() + lifetime(user["is_admin"]), "ip": ip, "user_agent": user_agent[:300]})
    return raw


def load(db: Database, raw: str | None) -> Principal | None:
    """The signed-in person for this cookie, or None if it is missing, expired, idle too long, or the user is suspended."""
    if not raw:
        return None
    digest = tokens.digest(raw)
    row = db.one(
        "SELECT s.id_hash, s.csrf_token, s.mfa_passed, s.last_seen_at, s.expires_at, u.id AS user_id, u.email, u.name, "
        "u.is_admin, u.email_verified_at, u.totp_enabled_at FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.id_hash = ? AND u.status = 'active'", (digest,))
    if row is None:
        return None
    now = clock.now()
    last_seen = datetime.fromisoformat(row["last_seen_at"])
    if datetime.fromisoformat(row["expires_at"]) <= now or last_seen + IDLE <= now:
        end(db, digest)
        return None
    if now - last_seen >= TOUCH_EVERY:
        db.execute("UPDATE sessions SET last_seen_at = ? WHERE id_hash = ?", (now, digest))
    return Principal(user_id=row["user_id"], email=row["email"], name=row["name"], is_admin=row["is_admin"],
                     email_verified=row["email_verified_at"] is not None, totp_enabled=row["totp_enabled_at"] is not None,
                     mfa_passed=row["mfa_passed"], session_hash=digest, csrf_token=row["csrf_token"])


def rotate(db: Database, principal: Principal, ip: str | None, user_agent: str, mfa_passed: bool) -> str:
    """Replace a session with a fresh one (after two-step login), keeping its absolute expiry."""
    with db.transaction():
        old = db.one("SELECT expires_at FROM sessions WHERE id_hash = ?", (principal.session_hash,))
        raw = tokens.new()
        db.insert("sessions", {"id_hash": tokens.digest(raw), "user_id": principal.user_id, "csrf_token": tokens.new(),
                               "mfa_passed": mfa_passed, "ip": ip, "user_agent": user_agent[:300],
                               "expires_at": old["expires_at"] if old else clock.now() + lifetime(principal.is_admin)})
        end(db, principal.session_hash)
    return raw


def end(db: Database, session_hash: str) -> None:
    db.execute("DELETE FROM sessions WHERE id_hash = ?", (session_hash,))


def end_all(db: Database, user_id: int, keep: str | None = None) -> int:
    if keep:
        return db.execute("DELETE FROM sessions WHERE user_id = ? AND id_hash <> ?", (user_id, keep))
    return db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def listing(db: Database, principal: Principal) -> list[dict[str, Any]]:
    rows = db.query("SELECT id_hash, created_at, last_seen_at, ip, user_agent FROM sessions WHERE user_id = ? "
                    "ORDER BY last_seen_at DESC", (principal.user_id,))
    # The public id is a prefix of the stored hash: enough to pick a session, useless as a credential.
    return [{"id": r["id_hash"][:16], "current": r["id_hash"] == principal.session_hash, "created_at": r["created_at"],
             "last_seen_at": r["last_seen_at"], "ip": r["ip"], "user_agent": r["user_agent"]} for r in rows]


def end_by_public_id(db: Database, principal: Principal, public_id: str) -> bool:
    if len(public_id) != 16 or not all(c in "0123456789abcdef" for c in public_id):
        return False
    return db.execute("DELETE FROM sessions WHERE user_id = ? AND left(id_hash, 16) = ?", (principal.user_id, public_id)) > 0


def cookie_args(is_admin: bool) -> dict[str, Any]:
    return {"key": COOKIE, "httponly": True, "samesite": "lax", "path": "/",
            "secure": settings.is_production or settings.app_base_url.startswith("https://"),
            "max_age": int(lifetime(is_admin).total_seconds())}
