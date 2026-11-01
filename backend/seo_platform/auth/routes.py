"""/api/auth: sign-up, login, logout, verification, password reset, profile and sessions."""
from __future__ import annotations

import ipaddress
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..db import Database
from . import service, sessions
from .sessions import Principal

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ---------- dependencies (also used by the rest of the API) ----------

def get_db(request: Request) -> Database:
    return request.app.state.db


def client_ip(request: Request) -> str | None:
    host = request.client.host if request.client else None
    try:
        return str(ipaddress.ip_address(host)) if host else None
    except ValueError:
        return None


def user_agent(request: Request) -> str:
    return request.headers.get("user-agent", "")[:300]


def current_principal(request: Request) -> Principal | None:
    if not hasattr(request.state, "principal"):
        request.state.principal = sessions.load(get_db(request), request.cookies.get(sessions.COOKIE))
    return request.state.principal


def require_login(principal: Principal | None = Depends(current_principal)) -> Principal:
    if principal is None:
        raise HTTPException(401, "Please log in.")
    return principal


def _start_session(response: Response, raw: str, is_admin: bool) -> None:
    response.set_cookie(value=raw, **sessions.cookie_args(is_admin))


def _clear_session(response: Response) -> None:
    response.delete_cookie(sessions.COOKIE, path="/")


# ---------- request bodies ----------

class SignupIn(BaseModel):
    email: str = Field(max_length=254)
    name: str = Field(max_length=120)
    password: str = Field(max_length=1024)


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=1024)


class TokenIn(BaseModel):
    token: str = Field(max_length=200)


class EmailIn(BaseModel):
    email: str = Field(max_length=254)


class ResetIn(BaseModel):
    token: str = Field(max_length=200)
    password: str = Field(max_length=1024)


class PasswordIn(BaseModel):
    current: str = Field("", max_length=1024)
    new: str = Field(max_length=1024)


class ProfileIn(BaseModel):
    name: str = Field(max_length=120)


# ---------- routes ----------

@router.post("/signup", status_code=202)
def signup(body: SignupIn, db: Database = Depends(get_db)) -> dict[str, str]:
    service.signup(db, body.email, body.name, body.password)
    return {"detail": "Check your email for a link to confirm your address, then log in."}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Database = Depends(get_db)) -> dict[str, Any]:
    old = current_principal(request)
    if old:
        sessions.end(db, old.session_hash)  # never carry a session across a login
    raw, user = service.login(db, body.email, body.password, client_ip(request), user_agent(request))
    _start_session(response, raw, user["is_admin"])
    return {"mfa_required": user["totp_enabled_at"] is not None}


@router.post("/logout")
def logout(request: Request, response: Response, db: Database = Depends(get_db)) -> dict[str, bool]:
    principal = current_principal(request)
    if principal:
        sessions.end(db, principal.session_hash)
    _clear_session(response)
    return {"ok": True}


@router.get("/me")
def me(principal: Principal = Depends(require_login), db: Database = Depends(get_db)) -> dict[str, Any]:
    return service.me(db, principal)


@router.patch("/me")
def update_me(body: ProfileIn, principal: Principal = Depends(require_login), db: Database = Depends(get_db)) -> dict[str, Any]:
    service.update_profile(db, principal, body.name)
    return {"ok": True}


@router.post("/verify")
def verify(body: TokenIn, db: Database = Depends(get_db)) -> dict[str, str]:
    service.verify_email(db, body.token)
    return {"detail": "Email address confirmed."}


@router.post("/verify/resend", status_code=202)
def resend(principal: Principal = Depends(require_login), db: Database = Depends(get_db)) -> dict[str, str]:
    service.resend_verification(db, principal)
    return {"detail": "If your address still needs confirming, we've sent a new link."}


@router.post("/forgot", status_code=202)
def forgot(body: EmailIn, db: Database = Depends(get_db)) -> dict[str, str]:
    service.forgot_password(db, body.email)
    return {"detail": "If that email has an account, we've sent a link to reset the password."}


@router.post("/reset")
def reset(body: ResetIn, response: Response, db: Database = Depends(get_db)) -> dict[str, str]:
    service.reset_password(db, body.token, body.password)
    _clear_session(response)
    return {"detail": "Password changed. Log in with your new password."}


@router.post("/password")
def change_password(body: PasswordIn, principal: Principal = Depends(require_login),
                    db: Database = Depends(get_db)) -> dict[str, str]:
    service.change_password(db, principal, body.current, body.new)
    return {"detail": "Password changed. You've been signed out everywhere else."}


@router.get("/sessions")
def list_sessions(principal: Principal = Depends(require_login), db: Database = Depends(get_db)) -> list[dict[str, Any]]:
    return sessions.listing(db, principal)


@router.delete("/sessions/{public_id}")
def end_session(public_id: str, principal: Principal = Depends(require_login), db: Database = Depends(get_db)) -> dict[str, bool]:
    if not sessions.end_by_public_id(db, principal, public_id):
        raise HTTPException(404, "That session has already ended.")
    return {"ok": True}
