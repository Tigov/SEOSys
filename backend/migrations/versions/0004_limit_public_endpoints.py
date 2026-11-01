"""Count sign-ups and free website checks per IP address, so they can be rate limited.

Revision ID: 0004
Revises: 0003
"""
from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_login_attempts_kind"), "login_attempts", type_="check")
    op.create_check_constraint(op.f("ck_login_attempts_kind"), "login_attempts",
                               "kind IN ('login', 'mfa', 'reset', 'verify', 'signup', 'grader')")


def downgrade() -> None:
    op.execute("DELETE FROM login_attempts WHERE kind IN ('signup', 'grader')")
    op.drop_constraint(op.f("ck_login_attempts_kind"), "login_attempts", type_="check")
    op.create_check_constraint(op.f("ck_login_attempts_kind"), "login_attempts", "kind IN ('login', 'mfa', 'reset', 'verify')")
