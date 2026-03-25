"""conversation workspace initial schema

Revision ID: 0001_conversation_ws
Revises:
Create Date: 2026-03-24 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_conversation_ws"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("conversation_id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("slug", sa.String(length=255), nullable=True),
        sa.Column("visibility_scope", sa.String(length=32), nullable=False),
        sa.Column("space_type", sa.String(length=32), nullable=False),
        sa.Column("linked_records_json", sa.JSON(), nullable=False),
        sa.Column("primary_assistant_id", sa.String(length=36), nullable=True),
        sa.Column("latest_summary", sa.Text(), nullable=True),
        sa.Column("latest_message_preview", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_conversations_family_id", "conversations", ["family_id"])
    op.create_index("ix_conversations_kind", "conversations", ["kind"])
    op.create_index("ix_conversations_space_type", "conversations", ["space_type"])
    op.create_index("ix_conversations_primary_assistant_id", "conversations", ["primary_assistant_id"])
    op.create_index("ix_conversations_family_updated", "conversations", ["family_id", "updated_at"])

    op.create_table(
        "conversation_participants",
        sa.Column("participant_id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("conversation_id", sa.String(length=36), sa.ForeignKey("conversations.conversation_id", ondelete="CASCADE"), nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("participant_kind", sa.String(length=24), nullable=False),
        sa.Column("actor_email", sa.String(length=255), nullable=True),
        sa.Column("person_id", sa.String(length=64), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("top_level_assistant", sa.String(length=32), nullable=True),
        sa.Column("assistant_mode", sa.String(length=16), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("conversation_id", "actor_email", "top_level_assistant", name="uq_conversation_participants_identity"),
    )
    op.create_index("ix_conversation_participants_conversation_id", "conversation_participants", ["conversation_id"])
    op.create_index("ix_conversation_participants_family_id", "conversation_participants", ["family_id"])
    op.create_index("ix_conversation_participants_participant_kind", "conversation_participants", ["participant_kind"])
    op.create_index("ix_conversation_participants_actor_email", "conversation_participants", ["actor_email"])
    op.create_index("ix_conversation_participants_person_id", "conversation_participants", ["person_id"])
    op.create_index("ix_conversation_participants_top_level_assistant", "conversation_participants", ["top_level_assistant"])

    op.create_table(
        "messages",
        sa.Column("message_id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("conversation_id", sa.String(length=36), sa.ForeignKey("conversations.conversation_id", ondelete="CASCADE"), nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("sender_kind", sa.String(length=24), nullable=False),
        sa.Column("sender_participant_id", sa.String(length=36), sa.ForeignKey("conversation_participants.participant_id", ondelete="SET NULL"), nullable=True),
        sa.Column("sender_label", sa.String(length=255), nullable=False),
        sa.Column("top_level_assistant", sa.String(length=32), nullable=True),
        sa.Column("reply_to_message_id", sa.String(length=36), sa.ForeignKey("messages.message_id", ondelete="SET NULL"), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_family_id", "messages", ["family_id"])
    op.create_index("ix_messages_sender_kind", "messages", ["sender_kind"])
    op.create_index("ix_messages_sender_participant_id", "messages", ["sender_participant_id"])
    op.create_index("ix_messages_top_level_assistant", "messages", ["top_level_assistant"])
    op.create_index("ix_messages_reply_to_message_id", "messages", ["reply_to_message_id"])
    op.create_index("ix_messages_created_at", "messages", ["created_at"])
    op.create_index("ix_messages_conversation_created", "messages", ["conversation_id", "created_at"])

    op.create_table(
        "message_blocks",
        sa.Column("block_id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("message_id", sa.String(length=36), sa.ForeignKey("messages.message_id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("block_type", sa.String(length=32), nullable=False),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column("data_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("message_id", "position", name="uq_message_blocks_position"),
    )
    op.create_index("ix_message_blocks_message_id", "message_blocks", ["message_id"])
    op.create_index("ix_message_blocks_block_type", "message_blocks", ["block_type"])

    op.create_table(
        "attachments",
        sa.Column("attachment_id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("conversation_id", sa.String(length=36), sa.ForeignKey("conversations.conversation_id", ondelete="CASCADE"), nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.String(length=36), sa.ForeignKey("messages.message_id", ondelete="SET NULL"), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("preview_url", sa.Text(), nullable=True),
        sa.Column("uploaded_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_attachments_conversation_id", "attachments", ["conversation_id"])
    op.create_index("ix_attachments_family_id", "attachments", ["family_id"])
    op.create_index("ix_attachments_message_id", "attachments", ["message_id"])

    op.create_table(
        "conversation_summaries",
        sa.Column("summary_id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("conversation_id", sa.String(length=36), sa.ForeignKey("conversations.conversation_id", ondelete="CASCADE"), nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("summary_type", sa.String(length=24), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("decisions_json", sa.JSON(), nullable=False),
        sa.Column("open_questions_json", sa.JSON(), nullable=False),
        sa.Column("referenced_files_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_conversation_summaries_conversation_id", "conversation_summaries", ["conversation_id"])
    op.create_index("ix_conversation_summaries_family_id", "conversation_summaries", ["family_id"])

    op.create_table(
        "agent_runs",
        sa.Column("run_id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("conversation_id", sa.String(length=36), sa.ForeignKey("conversations.conversation_id", ondelete="CASCADE"), nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("trigger_message_id", sa.String(length=36), sa.ForeignKey("messages.message_id", ondelete="CASCADE"), nullable=False),
        sa.Column("top_level_assistant", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agent_runs_conversation_id", "agent_runs", ["conversation_id"])
    op.create_index("ix_agent_runs_family_id", "agent_runs", ["family_id"])
    op.create_index("ix_agent_runs_trigger_message_id", "agent_runs", ["trigger_message_id"])
    op.create_index("ix_agent_runs_top_level_assistant", "agent_runs", ["top_level_assistant"])
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])

    op.create_table(
        "domain_activity",
        sa.Column("activity_id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("conversation_id", sa.String(length=36), sa.ForeignKey("conversations.conversation_id", ondelete="CASCADE"), nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("agent_runs.run_id", ondelete="SET NULL"), nullable=True),
        sa.Column("message_id", sa.String(length=36), sa.ForeignKey("messages.message_id", ondelete="SET NULL"), nullable=True),
        sa.Column("agent_name", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("detail_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_domain_activity_conversation_id", "domain_activity", ["conversation_id"])
    op.create_index("ix_domain_activity_family_id", "domain_activity", ["family_id"])
    op.create_index("ix_domain_activity_run_id", "domain_activity", ["run_id"])
    op.create_index("ix_domain_activity_message_id", "domain_activity", ["message_id"])
    op.create_index("ix_domain_activity_agent_name", "domain_activity", ["agent_name"])
    op.create_index("ix_domain_activity_state", "domain_activity", ["state"])

    op.create_table(
        "action_proposals",
        sa.Column("action_id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("conversation_id", sa.String(length=36), sa.ForeignKey("conversations.conversation_id", ondelete="CASCADE"), nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("source_message_id", sa.String(length=36), sa.ForeignKey("messages.message_id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("source_conversation_id", sa.String(length=36), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_action_proposals_conversation_id", "action_proposals", ["conversation_id"])
    op.create_index("ix_action_proposals_family_id", "action_proposals", ["family_id"])
    op.create_index("ix_action_proposals_source_message_id", "action_proposals", ["source_message_id"])
    op.create_index("ix_action_proposals_action_type", "action_proposals", ["action_type"])
    op.create_index("ix_action_proposals_status", "action_proposals", ["status"])

    op.create_table(
        "share_events",
        sa.Column("share_id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("family_id", sa.Integer(), nullable=False),
        sa.Column("source_conversation_id", sa.String(length=36), nullable=False),
        sa.Column("source_message_id", sa.String(length=36), nullable=False),
        sa.Column("target_conversation_id", sa.String(length=36), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_share_events_family_id", "share_events", ["family_id"])
    op.create_index("ix_share_events_source_conversation_id", "share_events", ["source_conversation_id"])
    op.create_index("ix_share_events_source_message_id", "share_events", ["source_message_id"])
    op.create_index("ix_share_events_target_conversation_id", "share_events", ["target_conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_share_events_target_conversation_id", table_name="share_events")
    op.drop_index("ix_share_events_source_message_id", table_name="share_events")
    op.drop_index("ix_share_events_source_conversation_id", table_name="share_events")
    op.drop_index("ix_share_events_family_id", table_name="share_events")
    op.drop_table("share_events")

    op.drop_index("ix_action_proposals_status", table_name="action_proposals")
    op.drop_index("ix_action_proposals_action_type", table_name="action_proposals")
    op.drop_index("ix_action_proposals_source_message_id", table_name="action_proposals")
    op.drop_index("ix_action_proposals_family_id", table_name="action_proposals")
    op.drop_index("ix_action_proposals_conversation_id", table_name="action_proposals")
    op.drop_table("action_proposals")

    op.drop_index("ix_domain_activity_state", table_name="domain_activity")
    op.drop_index("ix_domain_activity_agent_name", table_name="domain_activity")
    op.drop_index("ix_domain_activity_message_id", table_name="domain_activity")
    op.drop_index("ix_domain_activity_run_id", table_name="domain_activity")
    op.drop_index("ix_domain_activity_family_id", table_name="domain_activity")
    op.drop_index("ix_domain_activity_conversation_id", table_name="domain_activity")
    op.drop_table("domain_activity")

    op.drop_index("ix_agent_runs_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_top_level_assistant", table_name="agent_runs")
    op.drop_index("ix_agent_runs_trigger_message_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_family_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_conversation_id", table_name="agent_runs")
    op.drop_table("agent_runs")

    op.drop_index("ix_conversation_summaries_family_id", table_name="conversation_summaries")
    op.drop_index("ix_conversation_summaries_conversation_id", table_name="conversation_summaries")
    op.drop_table("conversation_summaries")

    op.drop_index("ix_attachments_message_id", table_name="attachments")
    op.drop_index("ix_attachments_family_id", table_name="attachments")
    op.drop_index("ix_attachments_conversation_id", table_name="attachments")
    op.drop_table("attachments")

    op.drop_index("ix_message_blocks_block_type", table_name="message_blocks")
    op.drop_index("ix_message_blocks_message_id", table_name="message_blocks")
    op.drop_table("message_blocks")

    op.drop_index("ix_messages_conversation_created", table_name="messages")
    op.drop_index("ix_messages_created_at", table_name="messages")
    op.drop_index("ix_messages_reply_to_message_id", table_name="messages")
    op.drop_index("ix_messages_top_level_assistant", table_name="messages")
    op.drop_index("ix_messages_sender_participant_id", table_name="messages")
    op.drop_index("ix_messages_sender_kind", table_name="messages")
    op.drop_index("ix_messages_family_id", table_name="messages")
    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_table("messages")

    op.drop_index("ix_conversation_participants_top_level_assistant", table_name="conversation_participants")
    op.drop_index("ix_conversation_participants_person_id", table_name="conversation_participants")
    op.drop_index("ix_conversation_participants_actor_email", table_name="conversation_participants")
    op.drop_index("ix_conversation_participants_participant_kind", table_name="conversation_participants")
    op.drop_index("ix_conversation_participants_family_id", table_name="conversation_participants")
    op.drop_index("ix_conversation_participants_conversation_id", table_name="conversation_participants")
    op.drop_table("conversation_participants")

    op.drop_index("ix_conversations_family_updated", table_name="conversations")
    op.drop_index("ix_conversations_primary_assistant_id", table_name="conversations")
    op.drop_index("ix_conversations_space_type", table_name="conversations")
    op.drop_index("ix_conversations_kind", table_name="conversations")
    op.drop_index("ix_conversations_family_id", table_name="conversations")
    op.drop_table("conversations")
