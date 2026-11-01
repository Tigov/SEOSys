"""Row-level security on every client-owned table.

The app role sees a client's rows only when the statement runs with app.client_id set to that client, or with
app.scope = 'system' (agency-level code). With neither, it sees nothing, so a forgotten setting fails closed.

Revision ID: 0002
Revises: 0001
"""
from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# Frozen copy of schema.CLIENT_TABLES at the time of this migration.
TABLES = ("sites", "crawls", "pages", "findings", "change_requests", "audit_events", "usage_events", "prompts",
          "ai_observations", "alerts", "connections")
RULE = ("current_setting('app.scope', true) = 'system' "
        "OR client_id = nullif(current_setting('app.client_id', true), '')::bigint")


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY client_isolation ON {table} USING ({RULE}) WITH CHECK ({RULE})")


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS client_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
