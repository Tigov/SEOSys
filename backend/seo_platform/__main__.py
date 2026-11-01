"""Command line: python -m seo_platform <command>

  seed [--demo]   Create the admin account from SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD. With --demo (never in
                  production) also create the demo client and one demo person for each client role.
  maintenance     Run the housekeeping job once (see maintenance.py).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import clock, maintenance
from .auth import passwords
from .config import settings
from .db import Database

DEMO_PASSWORD_ENV = "SEED_DEMO_PASSWORD"
DEMO_PEOPLE = (("owner", "Olivia Owner", "owner", False), ("member", "Max Member", "member", False),
               ("approver", "Ava Approver", "member", True))


def seed(db: Database, demo: bool) -> list[str]:
    from .api import seed_demo  # the demo client definition lives with the API

    done = []
    if settings.seed_admin_email:
        email = settings.seed_admin_email.strip().lower()
        if db.one("SELECT id FROM users WHERE email = ?", (email,)) is None:
            if problem := passwords.problem(settings.seed_admin_password, email):
                raise SystemExit(f"SEED_ADMIN_PASSWORD can't be used: {problem}")
            db.insert("users", {"email": email, "name": "Admin", "is_admin": True, "email_verified_at": clock.now(),
                                "password_hash": passwords.hash(settings.seed_admin_password)})
            done.append(f"admin {email}")
    if demo:
        if settings.is_production:
            raise SystemExit("Demo data is never created in production.")
        password = os.environ.get(DEMO_PASSWORD_ENV, "demo people share this password")
        seed_demo(db)
        client_id = db.list_clients()[0]["id"]
        for key, name, role, can_approve in DEMO_PEOPLE:
            email = f"{key}@demo.seosys.local"
            if db.one("SELECT id FROM users WHERE email = ?", (email,)):
                continue
            uid = db.insert("users", {"email": email, "name": name, "password_hash": passwords.hash(password),
                                      "email_verified_at": clock.now()})
            db.insert("memberships", {"user_id": uid, "client_id": client_id, "role": role, "can_approve": can_approve})
            done.append(f"demo {email}")
    return done


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m seo_platform")
    sub = parser.add_subparsers(dest="command", required=True)
    seed_cmd = sub.add_parser("seed")
    seed_cmd.add_argument("--demo", action="store_true")
    sub.add_parser("maintenance")
    args = parser.parse_args(argv)
    db = Database(settings.database_url)
    try:
        if args.command == "seed":
            for line in seed(db, args.demo):
                print(f"created {line}")
        else:
            print(json.dumps(maintenance.run(db)))
    finally:
        db.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
