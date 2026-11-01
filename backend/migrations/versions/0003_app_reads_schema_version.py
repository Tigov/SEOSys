"""Let the app role read the schema version, for the /readyz health check.

Revision ID: 0003
Revises: 0002
"""
from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("GRANT SELECT ON alembic_version TO seosys_app")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON alembic_version FROM seosys_app")
