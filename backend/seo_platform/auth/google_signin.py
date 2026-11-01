"""Sign in with Google.

A Google account signs in to the user it is linked to. A new email gets a new, already-verified account. If the
email already belongs to a password account, the Google account is only linked after the owner confirms from
their inbox, so nobody can take over an account by creating a Google login with someone else's address.
"""
from __future__ import annotations

from typing import Any

from .. import clock, mailer
from ..adapters import google
from ..db import Database
from . import service, sessions, tokens
from .service import LINK_TTL, AuthError


async def finish_signin(db: Database, pending: dict[str, Any], code: str | None, error: str | None,
                        ip: str | None, user_agent: str) -> tuple[str, str | None]:
    """Returns (outcome, session token). Outcome: signed_in, mfa, link_sent, declined or failed."""
    if error or not code:
        return "declined", None
    resp = await google.exchange_code(pending, code)
    if resp.status_code != 200:
        return "failed", None
    claims = google.id_token_claims(resp.json().get("id_token"))
    sub, email = str(claims.get("sub") or ""), str(claims.get("email") or "").strip().lower()
    if not sub or not email or claims.get("email_verified") is not True:
        return "failed", None

    user = db.one("SELECT * FROM users WHERE google_sub = ?", (sub,))
    if user is None:
        existing = service.user_by_email(db, email)
        if existing is not None:
            if existing["status"] == "active" and service.email_budget_left(db, email, "verify"):
                raw = tokens.new()
                with db.transaction():
                    db.insert("email_tokens", {"token_hash": tokens.digest(raw), "user_id": existing["id"],
                                               "purpose": "link_google", "detail": {"sub": sub},
                                               "expires_at": clock.now() + LINK_TTL})
                    mailer.queue(db, email, "link_google", name=existing["name"], url=service.link("link-google", raw))
            return "link_sent", None
        name = str(claims.get("name") or email.split("@")[0])[:120]
        with db.transaction():
            user_id = db.insert("users", {"email": email, "name": name, "google_sub": sub,
                                          "email_verified_at": clock.now()})
            db.log(None, f"user:{user_id}", "user.signed_up", f"user:{user_id}", {"method": "google"},
                   actor_user_id=user_id)
        user = db.one("SELECT * FROM users WHERE id = ?", (user_id,))
    assert user is not None
    if user["status"] != "active":
        return "failed", None
    db.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (clock.now(), user["id"]))
    db.log(None, f"user:{user['id']}", "user.logged_in", f"user:{user['id']}", {"method": "google"},
           actor_user_id=user["id"], ip=ip, user_agent=user_agent[:300])
    mfa_on = user["totp_enabled_at"] is not None
    return ("mfa" if mfa_on else "signed_in"), sessions.create(db, user, ip, user_agent, mfa_passed=not mfa_on)


def confirm_link(db: Database, raw: str) -> None:
    with db.transaction():
        row = db.one("UPDATE email_tokens SET used_at = ? WHERE token_hash = ? AND purpose = 'link_google' "
                     "AND used_at IS NULL AND expires_at > ? RETURNING user_id, detail",
                     (clock.now(), tokens.digest(raw or ""), clock.now()))
        if row is None:
            raise AuthError("This link has expired or was already used. Try signing in with Google again.")
        sub = str(row["detail"].get("sub", ""))
        if db.one("SELECT id FROM users WHERE google_sub = ?", (sub,)):
            raise AuthError("That Google account is already linked to another account.")
        db.execute("UPDATE users SET google_sub = ?, email_verified_at = coalesce(email_verified_at, ?) WHERE id = ?",
                   (sub, clock.now(), row["user_id"]))
        db.log(None, f"user:{row['user_id']}", "user.google_linked", f"user:{row['user_id']}", actor_user_id=row["user_id"])
