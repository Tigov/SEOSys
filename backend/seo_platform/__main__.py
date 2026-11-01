"""Command line: python -m seo_platform <command>

  seed [--demo]   Create the admin account from SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD. With --demo (never in
                  production) also create the demo client and one demo person for each client role.
  maintenance     Run the housekeeping job once (see maintenance.py).
  stripe-setup [--write-env PATH]
                  Create the packages in a Stripe *test* account (skips any that exist) and print their price IDs,
                  or write them into the .env file at PATH. Refuses live keys.
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


def stripe_setup(write_env: str | None) -> dict[str, str]:
    import stripe

    from .plans import PLANS

    if not settings.stripe_secret_key.startswith("sk_test_"):
        raise SystemExit("stripe-setup only works with a test key (sk_test_...).")
    client = stripe.StripeClient(settings.stripe_secret_key)
    found: dict[str, str] = {}
    for plan in PLANS.values():
        key = f"seosys_{plan.id}"
        existing = client.v1.prices.list(params={"lookup_keys": [key], "limit": 1}).data
        if existing:
            found[plan.price_env] = existing[0].id
            continue
        product = client.v1.products.create(params={"name": f"SEOSys {plan.name}", "description": plan.summary,
                                                    "metadata": {"seosys_plan": plan.id}})
        price: dict = {"product": product.id, "currency": "usd", "unit_amount": plan.amount_cents, "lookup_key": key}
        if plan.mode == "subscription":
            price["recurring"] = {"interval": "month"}
        found[plan.price_env] = client.v1.prices.create(params=price).id  # type: ignore[arg-type]
    if write_env:
        lines = open(write_env, encoding="utf-8").read().splitlines()
        lines = [l for l in lines if l.split("=", 1)[0].strip() not in found]
        lines += [f"{k}={v}" for k, v in found.items()]
        with open(write_env, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m seo_platform")
    sub = parser.add_subparsers(dest="command", required=True)
    seed_cmd = sub.add_parser("seed")
    seed_cmd.add_argument("--demo", action="store_true")
    sub.add_parser("maintenance")
    stripe_cmd = sub.add_parser("stripe-setup")
    stripe_cmd.add_argument("--write-env")
    args = parser.parse_args(argv)
    if args.command == "stripe-setup":
        for name, price in stripe_setup(args.write_env).items():
            print(f"{name}={price}")
        return 0
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
