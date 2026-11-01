"""Housekeeping, safe to run any number of times: `python -m seo_platform maintenance`.

Moves cancelled accounts to closed after 30 days and deletes closed accounts' data 30 days after that, and clears
out expired sessions, links and old login attempts. Runs hourly inside the app locally; on a scheduler in
production.
"""
from __future__ import annotations

from datetime import timedelta

from . import clock
from .db import Database

READ_ONLY_DAYS = 30
EXPORT_DAYS = 30


def run(db: Database) -> dict[str, int]:
    now = clock.now()
    done: dict[str, int] = {}
    closing = db.query("SELECT id, name FROM clients WHERE status = 'cancelled' AND cancelled_at <= ?",
                       (now - timedelta(days=READ_ONLY_DAYS),))
    for client in closing:
        db.execute("UPDATE clients SET status = 'closed' WHERE id = ? AND status = 'cancelled'", (client["id"],))
        db.log(client["id"], "system", "client.closed", f"client:{client['id']}")
    done["closed"] = len(closing)

    expired = db.query("SELECT id, name FROM clients WHERE status = 'closed' AND cancelled_at <= ?",
                       (now - timedelta(days=READ_ONLY_DAYS + EXPORT_DAYS),))
    for client in expired:
        with db.transaction():
            db.log(None, "system", "client.deleted", f"client:{client['id']}", {"name": client["name"]})
            db.execute("DELETE FROM clients WHERE id = ? AND status = 'closed'", (client["id"],))
    done["deleted"] = len(expired)

    done["sessions"] = db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
    done["email_tokens"] = db.execute("DELETE FROM email_tokens WHERE expires_at <= ?", (now - timedelta(days=1),))
    done["oauth_states"] = db.execute("DELETE FROM oauth_states WHERE created_at <= ?", (now - timedelta(hours=1),))
    done["login_attempts"] = db.execute("DELETE FROM login_attempts WHERE at <= ?", (now - timedelta(days=90),))
    done["invites"] = db.execute("DELETE FROM invites WHERE accepted_at IS NULL AND expires_at <= ?",
                                 (now - timedelta(days=30),))
    return done
