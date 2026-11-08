"""Two-step login is each person's own choice, so a client can no longer require it for its whole team.

Revision ID: 0006
Revises: 0005
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("clients", "require_mfa")


def downgrade() -> None:
    op.add_column("clients", sa.Column("require_mfa", sa.Boolean(), server_default=sa.text("false"), nullable=False))
