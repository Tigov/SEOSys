"""Allow Wix and Squarespace as website platforms.

Revision ID: 0005
Revises: 0004
"""
from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_sites_cms"), "sites", type_="check")
    op.create_check_constraint(op.f("ck_sites_cms"), "sites",
                               "cms IN ('wordpress', 'shopify', 'wix', 'squarespace', 'github', 'other')")


def downgrade() -> None:
    op.execute("UPDATE sites SET cms = 'other' WHERE cms IN ('wix', 'squarespace')")
    op.drop_constraint(op.f("ck_sites_cms"), "sites", type_="check")
    op.create_check_constraint(op.f("ck_sites_cms"), "sites", "cms IN ('wordpress', 'shopify', 'github', 'other')")
