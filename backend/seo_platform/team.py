"""People at a client company: invitations, the "can approve" tick, removal and ownership transfer.

A client always has exactly one owner (a partial unique index enforces it). The owner can't leave or be removed;
they transfer ownership first.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from . import clock, mailer
from .auth import service, tokens
from .auth.service import AuthError
from .db import Database
from .permissions import Access

INVITE_TTL = timedelta(days=7)


def listing(db: Database, client_id: int) -> dict[str, Any]:
    members = db.query(
        "SELECT u.id AS user_id, u.name, u.email, m.role, m.can_approve, (u.totp_enabled_at IS NOT NULL) AS two_step, "
        "m.created_at AS joined_at FROM memberships m JOIN users u ON u.id = m.user_id WHERE m.client_id = ? "
        "ORDER BY m.role DESC, u.name", (client_id,))
    invites = db.query("SELECT id, email, can_approve, expires_at, created_at FROM invites WHERE client_id = ? "
                       "AND accepted_at IS NULL AND expires_at > ? ORDER BY created_at", (client_id, clock.now()))
    return {"members": members, "invites": invites}


def invite(db: Database, a: Access, email: str, can_approve: bool) -> dict[str, Any]:
    email = service.normalise_email(email)
    assert a.client_id is not None and a.client is not None
    if db.one("SELECT 1 AS x FROM memberships m JOIN users u ON u.id = m.user_id WHERE m.client_id = ? AND u.email = ?",
              (a.client_id, email)):
        raise AuthError(f"{email} is already on the team.", 409)
    raw = tokens.new()
    with db.transaction():
        db.execute("DELETE FROM invites WHERE client_id = ? AND email = ? AND accepted_at IS NULL", (a.client_id, email))
        invite_id = db.insert("invites", {"token_hash": tokens.digest(raw), "client_id": a.client_id, "email": email,
                                          "role": "member", "can_approve": can_approve, "invited_by": a.user_id,
                                          "expires_at": clock.now() + INVITE_TTL, "created_at": clock.now()})
        mailer.queue(db, email, "invite", inviter=a.principal.name if a.principal else "Your team",
                     client=a.client["name"], url=service.link("invite", raw))
        db.log(a.client_id, a.actor, "team.invited", f"client:{a.client_id}", {"email": email, "can_approve": can_approve},
               actor_user_id=a.user_id)
    return {"id": invite_id, "email": email}


def cancel_invite(db: Database, a: Access, invite_id: int) -> None:
    if not db.execute("DELETE FROM invites WHERE id = ? AND client_id = ? AND accepted_at IS NULL", (invite_id, a.client_id)):
        raise LookupError("That invitation was not found.")
    db.log(a.client_id, a.actor, "team.invite_cancelled", f"client:{a.client_id}", actor_user_id=a.user_id)


def accept(db: Database, a: Access, raw: str) -> int:
    """The signed-in person joins the client they were invited to. Returns the client id."""
    assert a.principal is not None
    with db.transaction():
        row = db.one("UPDATE invites SET accepted_at = ? WHERE token_hash = ? AND accepted_at IS NULL AND expires_at > ? "
                     "AND email = ? RETURNING client_id, can_approve",
                     (clock.now(), tokens.digest(raw or ""), clock.now(), a.principal.email))
        if row is None:
            raise AuthError("This invitation has expired, was already used, or was sent to a different email address. "
                            "Ask for a new one, and log in with the address it was sent to.")
        db.execute("INSERT INTO memberships (user_id, client_id, role, can_approve) VALUES (?, ?, 'member', ?) "
                   "ON CONFLICT (user_id, client_id) DO NOTHING", (a.principal.user_id, row["client_id"], row["can_approve"]))
        if not a.principal.email_verified:  # the invitation email proves they own the address
            db.execute("UPDATE users SET email_verified_at = ? WHERE id = ?", (clock.now(), a.principal.user_id))
        db.log(row["client_id"], a.actor, "team.joined", f"client:{row['client_id']}", actor_user_id=a.user_id)
    return int(row["client_id"])


def _member(db: Database, client_id: int, user_id: int) -> dict[str, Any]:
    row = db.one("SELECT * FROM memberships WHERE client_id = ? AND user_id = ?", (client_id, user_id))
    if row is None:
        raise LookupError("That person isn't on this team.")
    return row


def set_can_approve(db: Database, a: Access, user_id: int, can_approve: bool) -> None:
    member = _member(db, a.client_id, user_id)  # type: ignore[arg-type]
    if member["role"] == "owner":
        raise AuthError("The owner can always approve.", 409)
    db.execute("UPDATE memberships SET can_approve = ? WHERE client_id = ? AND user_id = ?", (can_approve, a.client_id, user_id))
    db.log(a.client_id, a.actor, "team.updated", f"client:{a.client_id}", {"user": user_id, "can_approve": can_approve},
           actor_user_id=a.user_id)


def remove(db: Database, a: Access, user_id: int) -> None:
    member = _member(db, a.client_id, user_id)  # type: ignore[arg-type]
    if member["role"] == "owner":
        raise AuthError("The owner can't be removed. Transfer ownership to someone else first.", 409)
    db.execute("DELETE FROM memberships WHERE client_id = ? AND user_id = ?", (a.client_id, user_id))
    db.log(a.client_id, a.actor, "team.removed", f"client:{a.client_id}", {"user": user_id}, actor_user_id=a.user_id)


def transfer(db: Database, a: Access, user_id: int) -> None:
    target = _member(db, a.client_id, user_id)  # type: ignore[arg-type]
    if target["role"] == "owner":
        return
    with db.transaction():
        # Demote first: the one-owner index is checked per statement.
        db.execute("UPDATE memberships SET role = 'member', can_approve = true WHERE client_id = ? AND role = 'owner'",
                   (a.client_id,))
        db.execute("UPDATE memberships SET role = 'owner', can_approve = false WHERE client_id = ? AND user_id = ?",
                   (a.client_id, user_id))
        db.log(a.client_id, a.actor, "team.ownership_transferred", f"client:{a.client_id}", {"to": user_id},
               actor_user_id=a.user_id)
