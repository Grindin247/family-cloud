"""Add person context columns to canonical family events.

Revision ID: 0013_family_event_person_context
Revises: 0012_family_identity_core
Create Date: 2026-03-17
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_family_event_person_context"
down_revision = "0012_family_identity_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("family_events", sa.Column("actor_person_id", sa.String(length=64), nullable=True))
    op.add_column("family_events", sa.Column("subject_person_id", sa.String(length=64), nullable=True))
    op.create_index("ix_family_events_actor_id", "family_events", ["actor_id"])
    op.create_index("ix_family_events_actor_person_id", "family_events", ["actor_person_id"])
    op.create_index("ix_family_events_subject_person_id", "family_events", ["subject_person_id"])


def downgrade() -> None:
    op.drop_index("ix_family_events_subject_person_id", table_name="family_events")
    op.drop_index("ix_family_events_actor_person_id", table_name="family_events")
    op.drop_index("ix_family_events_actor_id", table_name="family_events")
    op.drop_column("family_events", "subject_person_id")
    op.drop_column("family_events", "actor_person_id")
