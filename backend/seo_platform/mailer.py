"""Email through an outbox table.

`queue()` writes the email in the same transaction as the action that causes it, so a rolled-back action never
sends mail. `send_pending()` claims due rows with a short lease (so two senders never send the same email and a
crash doesn't lose one), sends them outside any transaction, then records the result.
"""
from __future__ import annotations

import logging
import smtplib
from datetime import timedelta
from email.message import EmailMessage
from typing import Any, Callable

from . import clock
from .config import settings
from .db import Database
from .email_copy import render

log = logging.getLogger("seo_platform.mailer")

MAX_ATTEMPTS = 5
LEASE = timedelta(minutes=5)
BATCH = 50

Transport = Callable[[EmailMessage], None]


def queue(db: Database, to_email: str, template: str, **context: Any) -> int:
    render(template, context)  # fail now, inside the caller's transaction, if the template or context is wrong
    return db.insert("email_outbox", {"to_email": to_email, "template": template, "context": context,
                                      "created_at": clock.now(), "next_attempt_at": clock.now()})


def build(row: dict[str, Any]) -> EmailMessage:
    email = render(row["template"], row["context"])
    msg = EmailMessage()
    msg["From"] = settings.mail_from
    msg["To"] = row["to_email"]
    msg["Subject"] = email.subject
    msg.set_content(email.text)
    msg.add_alternative(email.html, subtype="html")
    return msg


def smtp_transport(msg: EmailMessage) -> None:
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        if settings.smtp_tls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


def send_pending(db: Database, transport: Transport | None = None) -> int:
    send = transport or smtp_transport
    rows = db.query(
        "UPDATE email_outbox SET attempts = attempts + 1, next_attempt_at = ? "
        "WHERE id IN (SELECT id FROM email_outbox WHERE status = 'pending' AND next_attempt_at <= ? "
        "ORDER BY next_attempt_at, id LIMIT ? FOR UPDATE SKIP LOCKED) RETURNING *",
        (clock.now() + LEASE, clock.now(), BATCH))
    sent = 0
    for row in rows:
        try:
            send(build(row))
        except Exception as exc:  # any transport failure: retry later, then give up
            status = "failed" if row["attempts"] >= MAX_ATTEMPTS else "pending"
            backoff = clock.now() + timedelta(minutes=2 ** row["attempts"])
            db.update_row("email_outbox", "id = ?", (row["id"],),
                          {"status": status, "last_error": f"{type(exc).__name__}: {exc}"[:500], "next_attempt_at": backoff})
            log.warning("email %s to outbox row %s failed (attempt %s)", row["template"], row["id"], row["attempts"])
            continue
        db.update_row("email_outbox", "id = ?", (row["id"],), {"status": "sent", "sent_at": clock.now()})
        sent += 1
    return sent


class Outbox:
    """Test transport: keeps every message it is asked to send."""

    def __init__(self) -> None:
        self.messages: list[EmailMessage] = []

    def __call__(self, msg: EmailMessage) -> None:
        self.messages.append(msg)

    def to(self, email: str) -> list[EmailMessage]:
        return [m for m in self.messages if m["To"] == email]

    def last_link(self, email: str) -> str:
        """The last link in the newest email to this address (plain-text part)."""
        body = self.to(email)[-1].get_body(("plain",)).get_content()  # type: ignore[union-attr]
        links = [w for w in body.split() if w.startswith(("http://", "https://"))]
        return links[-1]
