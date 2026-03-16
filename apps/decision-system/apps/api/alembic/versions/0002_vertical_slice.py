"""vertical slice schema

Revision ID: 0002_vertical_slice
Revises: 0001_initial
Create Date: 2026-02-08
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0002_vertical_slice"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


role_enum = postgresql.ENUM("admin", "editor", "viewer", name="roleenum", create_type=False)
decision_status_enum = postgresql.ENUM(
    "Draft",
    "Scored",
    "Queued",
    "Needs-Work",
    "Discretionary-Approved",
    "Rejected",
    "Scheduled",
    "In-Progress",
    "Done",
    "Archived",
    name="decisionstatusenum",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    role_enum.create(bind, checkfirst=True)
    decision_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "family_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("families.id"), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("role", role_enum, nullable=False),
    )

    op.create_table(
        "goals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("families.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("action_types", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    op.create_index("ix_goals_family_active", "goals", ["family_id", "active"], unique=False)

    op.create_table(
        "decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("families.id"), nullable=False),
        sa.Column("created_by_member_id", sa.Integer(), sa.ForeignKey("family_members.id"), nullable=False),
        sa.Column("owner_member_id", sa.Integer(), sa.ForeignKey("family_members.id"), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("cost", sa.Float(), nullable=True),
        sa.Column("urgency", sa.Integer(), nullable=True),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("tags", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", decision_status_enum, nullable=False, server_default="Draft"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("attachments", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("links", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_index("ix_decisions_family_status", "decisions", ["family_id", "status"], unique=False)

    op.create_table(
        "decision_scores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_id", sa.Integer(), sa.ForeignKey("decisions.id"), nullable=False),
        sa.Column("goal_id", sa.Integer(), sa.ForeignKey("goals.id"), nullable=False),
        sa.Column("score_1_to_5", sa.Integer(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("computed_by", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("score_1_to_5 >= 1 AND score_1_to_5 <= 5", name="ck_score_range"),
    )

    op.create_index(
        "ix_decision_scores_decision_goal_version",
        "decision_scores",
        ["decision_id", "goal_id", "version"],
        unique=False,
    )

    op.create_table(
        "decision_queue_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_id", sa.Integer(), sa.ForeignKey("decisions.id"), nullable=False, unique=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("decision_queue_items")
    op.drop_index("ix_decision_scores_decision_goal_version", table_name="decision_scores")
    op.drop_table("decision_scores")
    op.drop_index("ix_decisions_family_status", table_name="decisions")
    op.drop_table("decisions")
    op.drop_index("ix_goals_family_active", table_name="goals")
    op.drop_table("goals")
    op.drop_table("family_members")

    bind = op.get_bind()
    decision_status_enum.drop(bind, checkfirst=True)
    role_enum.drop(bind, checkfirst=True)
