"""Two-step login with an authenticator app (TOTP, RFC 6238) and one-time recovery codes."""
from __future__ import annotations

from typing import Any

import pyotp

from .. import clock, mailer
from ..config import settings
from ..db import Database
from . import passwords, sessions, tokens
from .service import AuthError, LOCK_WINDOW, _attempt, _recent

STEP_SECONDS = 30
WINDOW = 1  # accept the code before and after the current one, for clock drift
RECOVERY_CODES = 10
MFA_FAILURES = 5


def _user(db: Database, user_id: int) -> dict[str, Any]:
    row = db.one("SELECT * FROM users WHERE id = ?", (user_id,))
    assert row is not None
    return row


def _matching_step(secret: str, code: str, last_step: int | None) -> int | None:
    """The time step this code belongs to, if it is valid now and newer than the last one used (no replays)."""
    code = "".join(ch for ch in code if ch.isdigit())
    if len(code) != 6:
        return None
    totp = pyotp.TOTP(secret)
    now = clock.now().timestamp()
    for offset in range(-WINDOW, WINDOW + 1):
        moment = now + offset * STEP_SECONDS
        step = int(moment // STEP_SECONDS)
        if tokens.same(totp.at(moment), code) and (last_step is None or step > last_step):
            return step
    return None


def _check_budget(db: Database, email: str) -> None:
    if _recent(db, "email = ? AND kind = 'mfa' AND NOT ok", (email,), LOCK_WINDOW) >= MFA_FAILURES:
        raise AuthError("Too many wrong codes. Wait 15 minutes and try again.", 429)


def _new_recovery_codes(db: Database, user_id: int) -> list[str]:
    codes = [tokens.recovery_code() for _ in range(RECOVERY_CODES)]
    db.execute("DELETE FROM recovery_codes WHERE user_id = ?", (user_id,))
    for code in codes:
        db.insert("recovery_codes", {"user_id": user_id, "code_hash": tokens.digest(code)})
    return codes


def setup(db: Database, principal: sessions.Principal) -> dict[str, str]:
    if principal.totp_enabled:
        raise AuthError("Two-step login is already on.")
    secret = pyotp.random_base32()
    db.update_row("users", "id = ?", (principal.user_id,), {"totp_secret": secret})
    uri = pyotp.TOTP(secret).provisioning_uri(name=principal.email, issuer_name=settings.app_name)
    return {"otpauth_uri": uri, "secret": secret}


def enable(db: Database, principal: sessions.Principal, code: str, ip: str | None, user_agent: str) -> tuple[list[str], str]:
    """Turn two-step login on with a first code. Returns (recovery codes, new session token)."""
    user = _user(db, principal.user_id)
    if user["totp_enabled_at"]:
        raise AuthError("Two-step login is already on.")
    if not user["totp_secret"]:
        raise AuthError("Start the setup again.")
    step = _matching_step(user["totp_secret"], code, None)
    if step is None:
        raise AuthError("That code isn't right. Check the time on your phone and try the newest code.")
    with db.transaction():
        db.execute("UPDATE users SET totp_enabled_at = ?, totp_last_step = ? WHERE id = ?", (clock.now(), step, user["id"]))
        codes = _new_recovery_codes(db, user["id"])
        mailer.queue(db, user["email"], "mfa_changed", name=user["name"], state="on")
        db.log(None, f"user:{user['id']}", "user.mfa_enabled", f"user:{user['id']}", actor_user_id=user["id"])
        raw = sessions.rotate(db, principal, ip, user_agent, mfa_passed=True)
    return codes, raw


def verify(db: Database, principal: sessions.Principal, code: str, ip: str | None, user_agent: str) -> str:
    """Second step of login. Returns the new session token."""
    user = _user(db, principal.user_id)
    if not user["totp_enabled_at"]:
        raise AuthError("Two-step login isn't on for this account.")
    _check_budget(db, user["email"])
    step = _matching_step(user["totp_secret"], code, user["totp_last_step"])
    # Claim the step atomically: two requests racing with the same code can't both win.
    claimed = step is not None and db.execute(
        "UPDATE users SET totp_last_step = ? WHERE id = ? AND (totp_last_step IS NULL OR totp_last_step < ?)",
        (step, user["id"], step)) == 1
    if not claimed:
        _attempt(db, user["email"], ip, "mfa", False)
        raise AuthError("That code isn't right. Try the newest code from your app.", 401)
    _attempt(db, user["email"], ip, "mfa", True)
    return sessions.rotate(db, principal, ip, user_agent, mfa_passed=True)


def use_recovery_code(db: Database, principal: sessions.Principal, code: str, ip: str | None, user_agent: str) -> str:
    user = _user(db, principal.user_id)
    _check_budget(db, user["email"])
    used = db.execute("UPDATE recovery_codes SET used_at = ? WHERE user_id = ? AND code_hash = ? AND used_at IS NULL",
                      (clock.now(), user["id"], tokens.digest(tokens.normalise_recovery_code(code))))
    if not used:
        _attempt(db, user["email"], ip, "mfa", False)
        raise AuthError("That recovery code isn't right or was already used.", 401)
    _attempt(db, user["email"], ip, "mfa", True)
    db.log(None, f"user:{user['id']}", "user.recovery_code_used", f"user:{user['id']}", actor_user_id=user["id"])
    return sessions.rotate(db, principal, ip, user_agent, mfa_passed=True)


def _prove(db: Database, user: dict[str, Any], password: str, code: str) -> None:
    """Sensitive two-step changes need the password or a current code."""
    if password and user["password_hash"] and passwords.verify(user["password_hash"], password):
        return
    if code and user["totp_secret"] and _matching_step(user["totp_secret"], code, user["totp_last_step"]) is not None:
        return
    raise AuthError("Enter your password or a current code from your app.", 401)


def disable(db: Database, principal: sessions.Principal, password: str, code: str) -> None:
    if principal.is_admin:
        raise AuthError("Two-step login is required for the admin account.", 403)
    user = _user(db, principal.user_id)
    if not user["totp_enabled_at"]:
        return
    _prove(db, user, password, code)
    with db.transaction():
        db.execute("UPDATE users SET totp_secret = NULL, totp_enabled_at = NULL, totp_last_step = NULL WHERE id = ?",
                   (user["id"],))
        db.execute("DELETE FROM recovery_codes WHERE user_id = ?", (user["id"],))
        mailer.queue(db, user["email"], "mfa_changed", name=user["name"], state="off")
        db.log(None, f"user:{user['id']}", "user.mfa_disabled", f"user:{user['id']}", actor_user_id=user["id"])


def regenerate_codes(db: Database, principal: sessions.Principal, password: str, code: str) -> list[str]:
    user = _user(db, principal.user_id)
    if not user["totp_enabled_at"]:
        raise AuthError("Turn on two-step login first.")
    _prove(db, user, password, code)
    with db.transaction():
        codes = _new_recovery_codes(db, user["id"])
        db.log(None, f"user:{user['id']}", "user.recovery_codes_regenerated", f"user:{user['id']}", actor_user_id=user["id"])
    return codes


def remaining_codes(db: Database, user_id: int) -> int:
    row = db.one("SELECT count(*) AS n FROM recovery_codes WHERE user_id = ? AND used_at IS NULL", (user_id,))
    return int(row["n"]) if row else 0


def gate(principal: sessions.Principal) -> str | None:
    """What stands between this session and the app: 'mfa_required', 'mfa_setup_required', or None."""
    if principal.totp_enabled and not principal.mfa_passed:
        return "mfa_required"
    if principal.is_admin and not principal.totp_enabled:
        return "mfa_setup_required"
    return None

