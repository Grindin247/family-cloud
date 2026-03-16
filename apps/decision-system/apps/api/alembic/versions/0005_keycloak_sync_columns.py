"""keycloak sync columns and family member uniqueness

Revision ID: 0005_keycloak_sync_columns
Revises: 0004_budget_policy_and_periods
Create Date: 2026-02-14
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_keycloak_sync_columns"
down_revision = "0004_budget_policy_and_periods"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Families: mark external origin (e.g. Keycloak group) without impacting local families.
    op.add_column("families", sa.Column("external_source", sa.String(length=32), nullable=True))
    op.add_column("families", sa.Column("external_id", sa.String(length=255), nullable=True))
    op.add_column("families", sa.Column("external_name", sa.String(length=255), nullable=True))
    op.create_index("ix_families_external", "families", ["external_source", "external_id"], unique=True)

    # Family members: allow a user to exist in multiple families. Email becomes unique per-family.
    op.drop_constraint("family_members_email_key", "family_members", type_="unique")
    op.create_index("ix_family_members_family_email", "family_members", ["family_id", "email"], unique=True)

    op.add_column("family_members", sa.Column("external_source", sa.String(length=32), nullable=True))
    op.add_column("family_members", sa.Column("external_id", sa.String(length=255), nullable=True))
    op.create_index(
        "ix_family_members_family_external",
        "family_members",
        ["family_id", "external_source", "external_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_family_members_family_external", table_name="family_members")
    op.drop_column("family_members", "external_id")
    op.drop_column("family_members", "external_source")

    op.drop_index("ix_family_members_family_email", table_name="family_members")
    op.create_unique_constraint("family_members_email_key", "family_members", ["email"])

    op.drop_index("ix_families_external", table_name="families")
    op.drop_column("families", "external_name")
    op.drop_column("families", "external_id")
    op.drop_column("families", "external_source")

