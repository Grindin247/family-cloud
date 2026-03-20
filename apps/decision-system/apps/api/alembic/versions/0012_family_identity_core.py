"""Family identity core.

Revision ID: 0012_family_identity_core
Revises: 0011_family_events
Create Date: 2026-03-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0012_family_identity_core"
down_revision = "0011_family_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("families", sa.Column("slug", sa.String(length=255), nullable=True))
    op.create_unique_constraint("uq_families_slug", "families", ["slug"])

    op.create_table(
        "persons",
        sa.Column("person_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("legacy_member_id", sa.Integer(), sa.ForeignKey("family_members.id", ondelete="SET NULL"), nullable=True, unique=True),
        sa.Column("canonical_name", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("role_in_family", sa.String(length=64), nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("metadata_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_persons_family_id", "persons", ["family_id"])
    op.create_index("ix_persons_family_display_name", "persons", ["family_id", "display_name"])

    op.create_table(
        "person_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("persons.person_id", ondelete="CASCADE"), nullable=False),
        sa.Column("alias", sa.String(length=255), nullable=False),
        sa.Column("normalized_alias", sa.String(length=255), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("family_id", "person_id", "normalized_alias", name="uq_person_aliases_person_alias"),
    )
    op.create_index("ix_person_aliases_family_id", "person_aliases", ["family_id"])
    op.create_index("ix_person_aliases_person_id", "person_aliases", ["person_id"])
    op.create_index("ix_person_aliases_family_normalized", "person_aliases", ["family_id", "normalized_alias"])

    op.create_table(
        "person_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("persons.person_id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_type", sa.String(length=64), nullable=False),
        sa.Column("account_value", sa.String(length=255), nullable=False),
        sa.Column("normalized_value", sa.String(length=255), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("metadata_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("account_type", "normalized_value", name="uq_person_accounts_type_value"),
    )
    op.create_index("ix_person_accounts_family_id", "person_accounts", ["family_id"])
    op.create_index("ix_person_accounts_person_id", "person_accounts", ["person_id"])
    op.create_index("ix_person_accounts_family_type_value", "person_accounts", ["family_id", "account_type", "normalized_value"])

    op.create_table(
        "family_features",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("feature_key", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("config_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("family_id", "feature_key", name="uq_family_features_family_feature"),
    )
    op.create_index("ix_family_features_family_id", "family_features", ["family_id"])

    op.add_column("note_documents", sa.Column("owner_person_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("note_documents", sa.Column("visibility_scope", sa.String(length=32), nullable=False, server_default="family"))
    op.create_foreign_key("fk_note_documents_owner_person", "note_documents", "persons", ["owner_person_id"], ["person_id"], ondelete="SET NULL")
    op.create_index("ix_note_documents_owner_person", "note_documents", ["owner_person_id"])

    op.add_column("file_documents", sa.Column("owner_person_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("file_documents", sa.Column("visibility_scope", sa.String(length=32), nullable=False, server_default="family"))
    op.create_foreign_key("fk_file_documents_owner_person", "file_documents", "persons", ["owner_person_id"], ["person_id"], ondelete="SET NULL")
    op.create_index("ix_file_documents_owner_person", "file_documents", ["owner_person_id"])

    op.add_column("memory_documents", sa.Column("owner_person_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("memory_documents", sa.Column("visibility_scope", sa.String(length=32), nullable=False, server_default="family"))
    op.create_foreign_key("fk_memory_documents_owner_person", "memory_documents", "persons", ["owner_person_id"], ["person_id"], ondelete="SET NULL")
    op.create_index("ix_memory_documents_owner_person", "memory_documents", ["owner_person_id"])

    op.add_column("agent_session_states", sa.Column("actor_person_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_agent_session_states_actor_person", "agent_session_states", "persons", ["actor_person_id"], ["person_id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_agent_session_states_actor_person", "agent_session_states", type_="foreignkey")
    op.drop_column("agent_session_states", "actor_person_id")

    op.drop_index("ix_memory_documents_owner_person", table_name="memory_documents")
    op.drop_constraint("fk_memory_documents_owner_person", "memory_documents", type_="foreignkey")
    op.drop_column("memory_documents", "visibility_scope")
    op.drop_column("memory_documents", "owner_person_id")

    op.drop_index("ix_file_documents_owner_person", table_name="file_documents")
    op.drop_constraint("fk_file_documents_owner_person", "file_documents", type_="foreignkey")
    op.drop_column("file_documents", "visibility_scope")
    op.drop_column("file_documents", "owner_person_id")

    op.drop_index("ix_note_documents_owner_person", table_name="note_documents")
    op.drop_constraint("fk_note_documents_owner_person", "note_documents", type_="foreignkey")
    op.drop_column("note_documents", "visibility_scope")
    op.drop_column("note_documents", "owner_person_id")

    op.drop_index("ix_family_features_family_id", table_name="family_features")
    op.drop_table("family_features")

    op.drop_index("ix_person_accounts_family_type_value", table_name="person_accounts")
    op.drop_index("ix_person_accounts_person_id", table_name="person_accounts")
    op.drop_index("ix_person_accounts_family_id", table_name="person_accounts")
    op.drop_table("person_accounts")

    op.drop_index("ix_person_aliases_family_normalized", table_name="person_aliases")
    op.drop_index("ix_person_aliases_person_id", table_name="person_aliases")
    op.drop_index("ix_person_aliases_family_id", table_name="person_aliases")
    op.drop_table("person_aliases")

    op.drop_index("ix_persons_family_display_name", table_name="persons")
    op.drop_index("ix_persons_family_id", table_name="persons")
    op.drop_table("persons")

    op.drop_constraint("uq_families_slug", "families", type_="unique")
    op.drop_column("families", "slug")
