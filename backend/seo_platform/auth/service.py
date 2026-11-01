"""Sign-up, login, email verification, password reset and password change.

Nothing here reveals whether an email address has an account: the same answers, the same emails-or-not to the
caller, and (for login) the same time spent checking a password.
"""
from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from .. import clock, mailer
from ..config import settings
from ..db import Database
from . import passwords, sessions, tokens

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
VERIFY_TTL = timedelta(hours=24)
RESET_TTL = timedelta(minutes=30)
LINK_TTL = timedelta(minutes=30)
LOCK_WINDOW = timedelta(minutes=15)
EMAIL_FAILURES = 5
IP_FAILURES = 20
EMAILS_PER_HOUR = 3


class AuthError(Exception):
    """Shown to the person as-is, so the message never says whether an account exists."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


GENERIC_LOGIN = "That email and password don't match an account."
LOCKED = "Too many attempts. Wait 15 minutes and try again."


def normalise_email(email: str) -> str:
    cleaned = (email or "").strip().lower()
    if len(cleaned) > 254 or not EMAIL.match(cleaned):
        raise AuthError("Enter a valid email address.")
    return cleaned


def link(path: str, token: str) -> str:
    return f"{settings.app_base_url}/#/{path}?token={token}"


def user_by_email(db: Database, email: str) -> dict[str, Any] | None:
    return db.one("SELECT * FROM users WHERE email = ?", (email,))


def _attempt(db: Database, email: str, ip: str | None, kind: str, ok: bool) -> None:
    db.insert("login_attempts", {"email": email, "ip": ip, "kind": kind, "ok": ok, "at": clock.now()})


def _recent(db: Database, where: str, params: tuple[Any, ...], window: timedelta) -> int:
    row = db.one(f"SELECT count(*) AS n FROM login_attempts WHERE {where} AND at > ?", (*params, clock.now() - window))
    return int(row["n"]) if row else 0


def _issue(db: Database, user_id: int, purpose: str, ttl: timedelta) -> str:
    raw = tokens.new()
    db.insert("email_tokens", {"token_hash": tokens.digest(raw), "user_id": user_id, "purpose": purpose,
                               "expires_at": clock.now() + ttl})
    return raw


def _take(db: Database, raw: str, purpose: str) -> dict[str, Any] | None:
    """Use a token once. None if unknown, already used, expired, or for another purpose."""
    return db.one("UPDATE email_tokens SET used_at = ? WHERE token_hash = ? AND purpose = ? AND used_at IS NULL "
                  "AND expires_at > ? RETURNING user_id", (clock.now(), tokens.digest(raw or ""), purpose, clock.now()))


def _email_budget_left(db: Database, email: str, kind: str) -> bool:
    if _recent(db, "email = ? AND kind = ?", (email, kind), timedelta(hours=1)) >= EMAILS_PER_HOUR:
        return False
    _attempt(db, email, None, kind, True)
    return True


# ---------- sign-up and verification ----------

def signup(db: Database, email: str, name: str, password: str) -> None:
    email = normalise_email(email)
    name = (name or "").strip()[:120]
    if not name:
        raise AuthError("Enter your name.")
    if problem := passwords.problem(password, email):
        raise AuthError(problem)
    existing = user_by_email(db, email)
    if existing:
        passwords.hash(password)  # same work as a real sign-up, so timing doesn't reveal the account
        if _email_budget_left(db, email, "verify"):
            mailer.queue(db, email, "already_registered", name=existing["name"], url=f"{settings.app_base_url}/#/login")
        return
    with db.transaction():
        user_id = db.insert("users", {"email": email, "name": name, "password_hash": passwords.hash(password),
                                      "password_changed_at": clock.now()})
        _attempt(db, email, None, "verify", True)
        mailer.queue(db, email, "verify", name=name, url=link("verify", _issue(db, user_id, "verify", VERIFY_TTL)))
        db.log(None, f"user:{user_id}", "user.signed_up", f"user:{user_id}", actor_user_id=user_id)


def verify_email(db: Database, raw: str) -> None:
    with db.transaction():
        row = _take(db, raw, "verify")
        if row is None:
            raise AuthError("This link has expired or was already used. Log in and ask for a new one.")
        db.execute("UPDATE users SET email_verified_at = coalesce(email_verified_at, ?) WHERE id = ?",
                   (clock.now(), row["user_id"]))
        db.log(None, f"user:{row['user_id']}", "user.email_verified", f"user:{row['user_id']}", actor_user_id=row["user_id"])


def resend_verification(db: Database, principal: sessions.Principal) -> None:
    if principal.email_verified or not _email_budget_left(db, principal.email, "verify"):
        return
    mailer.queue(db, principal.email, "verify", name=principal.name,
                 url=link("verify", _issue(db, principal.user_id, "verify", VERIFY_TTL)))


# ---------- login ----------

def login(db: Database, email: str, password: str, ip: str | None, user_agent: str) -> tuple[str, dict[str, Any]]:
    """Check the password and open a session. Returns (cookie token, user). Two-step login, if on, comes next."""
    if _recent(db, "ip = ? AND NOT ok AND kind = 'login'", (ip,), LOCK_WINDOW) >= IP_FAILURES:
        raise AuthError(LOCKED, 429)
    try:
        email = normalise_email(email)
    except AuthError:
        raise AuthError(GENERIC_LOGIN, 401)
    if _recent(db, "email = ? AND NOT ok AND kind = 'login'", (email,), LOCK_WINDOW) >= EMAIL_FAILURES:
        raise AuthError(LOCKED, 429)
    user = user_by_email(db, email)
    ok = passwords.verify(user["password_hash"] if user else None, password)
    if not ok or user is None or user["status"] != "active":
        _attempt(db, email, ip, "login", False)
        raise AuthError(GENERIC_LOGIN, 401)
    known_ip = _recent(db, "email = ? AND ip = ? AND ok AND kind = 'login'", (email, ip), timedelta(days=90)) > 0
    first_login = user["last_login_at"] is None
    _attempt(db, email, ip, "login", True)
    if passwords.needs_rehash(user["password_hash"]):
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (passwords.hash(password), user["id"]))
    db.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (clock.now(), user["id"]))
    if not known_ip and not first_login:
        mailer.queue(db, email, "new_device", name=user["name"], device=_device(user_agent), ip=ip or "unknown address")
    db.log(None, f"user:{user['id']}", "user.logged_in", f"user:{user['id']}", actor_user_id=user["id"], ip=ip,
           user_agent=user_agent[:300])
    raw = sessions.create(db, user, ip, user_agent, mfa_passed=user["totp_enabled_at"] is None)
    return raw, user


def _device(user_agent: str) -> str:
    ua = user_agent or ""
    browser = next((b for b in ("Edge", "Firefox", "Chrome", "Safari") if b in ua), "a browser")
    system = next((s for k, s in (("Windows", "Windows"), ("Mac OS", "a Mac"), ("iPhone", "an iPhone"),
                                  ("Android", "Android"), ("Linux", "Linux")) if k in ua), "an unknown device")
    return f"{browser} on {system}"


# ---------- password reset and change ----------

def forgot_password(db: Database, email: str) -> None:
    try:
        email = normalise_email(email)
    except AuthError:
        return
    user = user_by_email(db, email)
    if user is None or user["status"] != "active" or not _email_budget_left(db, email, "reset"):
        return
    mailer.queue(db, email, "reset", name=user["name"], url=link("reset", _issue(db, user["id"], "reset", RESET_TTL)))


def reset_password(db: Database, raw: str, password: str) -> None:
    with db.transaction():
        row = _take(db, raw, "reset")
        if row is None:
            raise AuthError("This link has expired or was already used. Ask for a new one.")
        user = db.one("SELECT * FROM users WHERE id = ?", (row["user_id"],))
        if problem := passwords.problem(password, user["email"]):
            raise AuthError(problem)  # rolls back, so the link still works for a better password
        _set_password(db, user["id"], password)
        db.execute("UPDATE email_tokens SET used_at = ? WHERE user_id = ? AND purpose = 'reset' AND used_at IS NULL",
                   (clock.now(), user["id"]))
        sessions.end_all(db, user["id"])
        db.log(None, f"user:{user['id']}", "user.password_reset", f"user:{user['id']}", actor_user_id=user["id"])


def change_password(db: Database, principal: sessions.Principal, current: str, new: str) -> None:
    user = db.one("SELECT * FROM users WHERE id = ?", (principal.user_id,))
    if user["password_hash"] and not passwords.verify(user["password_hash"], current):
        raise AuthError("Your current password isn't right.")
    if problem := passwords.problem(new, principal.email):
        raise AuthError(problem)
    with db.transaction():
        _set_password(db, principal.user_id, new)
        sessions.end_all(db, principal.user_id, keep=principal.session_hash)
        db.log(None, f"user:{principal.user_id}", "user.password_changed", f"user:{principal.user_id}",
               actor_user_id=principal.user_id)


def _set_password(db: Database, user_id: int, password: str) -> None:
    db.execute("UPDATE users SET password_hash = ?, password_changed_at = ? WHERE id = ?",
               (passwords.hash(password), clock.now(), user_id))


def update_profile(db: Database, principal: sessions.Principal, name: str) -> None:
    name = (name or "").strip()[:120]
    if not name:
        raise AuthError("Enter your name.")
    db.execute("UPDATE users SET name = ? WHERE id = ?", (name, principal.user_id))


# ---------- who is signed in ----------

def me(db: Database, principal: sessions.Principal) -> dict[str, Any]:
    memberships = db.query(
        "SELECT m.client_id, c.name AS client_name, m.role, m.can_approve, c.status, c.plan, c.require_mfa "
        "FROM memberships m JOIN clients c ON c.id = m.client_id WHERE m.user_id = ? ORDER BY c.name", (principal.user_id,))
    return {"user": {"id": principal.user_id, "email": principal.email, "name": principal.name,
                     "is_admin": principal.is_admin, "email_verified": principal.email_verified,
                     "totp_enabled": principal.totp_enabled},
            "mfa_passed": principal.mfa_passed, "csrf_token": principal.csrf_token, "memberships": memberships}


def suspend(db: Database, user_id: int, actor: str) -> None:
    with db.transaction():
        db.execute("UPDATE users SET status = 'suspended' WHERE id = ?", (user_id,))
        sessions.end_all(db, user_id)
        db.log(None, actor, "user.suspended", f"user:{user_id}")


def reactivate(db: Database, user_id: int, actor: str) -> None:
    db.execute("UPDATE users SET status = 'active' WHERE id = ?", (user_id,))
    db.log(None, actor, "user.reactivated", f"user:{user_id}")
