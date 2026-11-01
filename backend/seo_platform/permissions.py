"""Who may do what. One table, enforced on every route through `require(action)`.

Roles: admin (the agency), owner / member / approver (people at a client company; an approver is a member the
owner ticked "can approve"), no_package (signed in, hasn't bought), public (anyone). The client's account status
narrows this further (see STATUS_ALLOWS).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from fastapi import Depends, HTTPException, Request

from .auth import mfa
from .auth.routes import current_principal, get_db
from .auth.sessions import Principal
from .db import ClientRepo, Database

CLIENT_ROLES = frozenset({"owner", "member", "approver"})
SIGNED_IN = frozenset({"admin", "owner", "member", "approver", "no_package"})
EVERYONE = SIGNED_IN | {"public"}

ACTIONS: dict[str, frozenset[str]] = {
    "public": EVERYONE,
    "account": SIGNED_IN,
    "billing.buy": frozenset({"no_package"}),  # anyone signed in who doesn't already own a client
    "client.view": frozenset({"admin"}) | CLIENT_ROLES,
    "change.approve": frozenset({"owner", "approver"}),  # sign-off stays with the client, never the agency
    "change.rollback": frozenset({"admin", "owner", "approver"}),
    "client.settings": frozenset({"admin", "owner"}),
    "google.manage": frozenset({"admin", "owner"}),
    "team.manage": frozenset({"admin", "owner"}),
    "billing.manage": frozenset({"owner"}),
    "client.export": frozenset({"admin", "owner"}),
    "work.run": frozenset({"admin"}),
    "admin": frozenset({"admin"}),
}

# Actions that need a client (the route has a {client_id} path parameter).
CLIENT_SCOPED = frozenset({"client.view", "change.approve", "change.rollback", "client.settings", "google.manage",
                           "team.manage", "billing.manage", "client.export", "work.run"})

# What each account status still allows. Anything else is refused with a message saying why.
STATUS_ALLOWS: dict[str, frozenset[str] | None] = {
    "active": None,  # everything
    "past_due": frozenset(ACTIONS) - {"work.run"},
    "cancelled": frozenset({"client.view", "client.export", "billing.manage"}),
    "closed": frozenset({"client.export", "billing.manage"}),
}
STATUS_MESSAGES = {
    "past_due": "The last payment didn't go through, so changes to the website are paused until it's paid.",
    "cancelled": "This account is cancelled, so it's read-only.",
    "closed": "This account is closed. The owner can still download its data.",
}

# Change-request actions and the permission each needs.
CHANGE_ACTIONS = {"submit": "work.run", "discard": "work.run", "deploy": "work.run",
                  "approve": "change.approve", "reject": "change.approve", "rollback": "change.rollback"}


@dataclass(frozen=True)
class Access:
    principal: Principal | None
    role: str
    client_id: int | None = None
    client: dict[str, Any] | None = None
    repo: ClientRepo | None = None

    @property
    def actor(self) -> str:
        """How this person appears in the activity log."""
        if self.principal is None:
            return "public"
        return f"{self.role}:{self.principal.name or self.principal.email}"

    @property
    def user_id(self) -> int | None:
        return self.principal.user_id if self.principal else None

    @property
    def change_role(self) -> str:
        """The change pipeline's view: the agency drafts and deploys, the client approves."""
        return "staff" if self.role == "admin" else "client"

    def can(self, action: str) -> bool:
        if self.role not in ACTIONS[action]:
            return False
        if self.client is None or (self.role == "admin" and action != "work.run"):
            return True  # the agency can always see and export; only its work on the site follows the status
        allowed = STATUS_ALLOWS[self.client["status"]]
        return allowed is None or action in allowed

    def check(self, action: str) -> None:
        if self.role not in ACTIONS[action]:
            raise HTTPException(403, "You don't have permission to do this.")
        if not self.can(action):
            raise HTTPException(403, STATUS_MESSAGES.get(self.client["status"] if self.client else "", "Not allowed."))


def role_in(db: Database, principal: Principal | None, client_id: int | None) -> tuple[str, dict[str, Any] | None]:
    """The principal's role for this client (or overall when client_id is None)."""
    if principal is None:
        return "public", None
    if principal.is_admin:
        return "admin", db.get_client(client_id) if client_id is not None else None
    if client_id is None:
        owner = db.one("SELECT 1 AS x FROM memberships WHERE user_id = ? AND role = 'owner'", (principal.user_id,))
        return ("owner" if owner else "no_package"), None
    row = db.one("SELECT m.role, m.can_approve, c.* FROM memberships m JOIN clients c ON c.id = m.client_id "
                 "WHERE m.user_id = ? AND m.client_id = ?", (principal.user_id, client_id))
    if row is None:
        return "none", None
    role = "approver" if row["role"] == "member" and row["can_approve"] else row["role"]
    client = {k: v for k, v in row.items() if k not in ("role", "can_approve")}
    return role, client


def require(action: str) -> Callable[..., Access]:
    """FastAPI dependency: resolve who is asking and refuse unless `action` is allowed for them here."""
    if action not in ACTIONS:
        raise ValueError(f"Unknown action {action}")

    def dependency(request: Request, principal: Principal | None = Depends(current_principal),
                   db: Database = Depends(get_db)) -> Access:
        if action == "public":
            return Access(principal, role_in(db, principal, None)[0])
        if principal is None:
            raise HTTPException(401, "Please log in.")
        if gate := mfa.gate(principal):
            raise HTTPException(403, gate)
        client_id = None
        if action in CLIENT_SCOPED:
            raw = request.path_params.get("client_id")
            if raw is None:
                raise RuntimeError(f"Route {request.url.path} uses {action} but has no client_id")
            client_id = int(raw)
        role, client = role_in(db, principal, client_id)
        if client_id is not None:
            if role == "none" or client is None:
                raise HTTPException(404, f"Client {client_id} was not found.")
            if client["require_mfa"] and role != "admin" and not principal.totp_enabled:
                raise HTTPException(403, "mfa_setup_required")
        access = Access(principal, role, client_id, client, ClientRepo(db, client_id) if client_id is not None else None)
        access.check(action)
        if action == "billing.buy" and not principal.email_verified:
            raise HTTPException(403, "Confirm your email address first. We sent you a link when you signed up.")
        return access

    dependency.action = action  # type: ignore[attr-defined]  # read by the route-coverage test
    return dependency
