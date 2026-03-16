"""add budget policy and period tables

Revision ID: 0004_budget_policy_and_periods
Revises: 0003_roadmap_items
Create Date: 2026-02-08
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_budget_policy_and_periods"
down_revision = "0003_roadmap_items"
branch_labels = None
depends_on = None


period_type_enum = postgresql.ENUM("quarterly", "custom", name="periodtypeenum", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    period_type_enum.create(bind, checkfirst=True)

    op.create_table(
        "periods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("families.id"), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("type", period_type_enum, nullable=False, server_default="custom"),
    )
    op.create_index("ix_periods_family_dates", "periods", ["family_id", "start_date", "end_date"], unique=False)

    op.create_table(
        "discretionary_budget_ledger",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("family_members.id"), nullable=False),
        sa.Column("period_id", sa.Integer(), sa.ForeignKey("periods.id"), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("decision_id", sa.Integer(), sa.ForeignKey("decisions.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_ledger_member_period", "discretionary_budget_ledger", ["member_id", "period_id"], unique=False)

    op.create_table(
        "budget_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("families.id"), nullable=False, unique=True),
        sa.Column("threshold_1_to_5", sa.Float(), nullable=False, server_default="4.0"),
        sa.Column("period_days", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("default_allowance", sa.Integer(), nullable=False, server_default="2"),
    )

    op.create_table(
        "member_budget_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("families.id"), nullable=False),
        sa.Column("member_id", sa.Integer(), sa.ForeignKey("family_members.id"), nullable=False),
        sa.Column("allowance", sa.Integer(), nullable=False, server_default="2"),
    )
    op.create_index(
        "ix_member_budget_settings_family_member",
        "member_budget_settings",
        ["family_id", "member_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_member_budget_settings_family_member", table_name="member_budget_settings")
    op.drop_table("member_budget_settings")
    op.drop_table("budget_policies")
    op.drop_index("ix_ledger_member_period", table_name="discretionary_budget_ledger")
    op.drop_table("discretionary_budget_ledger")
    op.drop_index("ix_periods_family_dates", table_name="periods")
    op.drop_table("periods")

    bind = op.get_bind()
    period_type_enum.drop(bind, checkfirst=True)

