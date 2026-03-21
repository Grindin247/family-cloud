"""Scoped decision management cutover.

Revision ID: 0014_scoped_decision_cutover
Revises: 0013_family_event_person_context
Create Date: 2026-03-20
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0014_scoped_decision_cutover"
down_revision = "0013_family_event_person_context"
branch_labels = None
depends_on = None


scope_type_enum = postgresql.ENUM("family", "person", name="scopetypeenum", create_type=False)
visibility_scope_enum = postgresql.ENUM("family", "personal", "admins", name="visibilityscopeenum", create_type=False)
goal_status_enum = postgresql.ENUM("active", "paused", "completed", "archived", name="goalstatusenum", create_type=False)
goal_horizon_enum = postgresql.ENUM("immediate", "seasonal", "annual", "long_term", "ongoing", name="goalhorizonenum", create_type=False)
goal_policy_enum = postgresql.ENUM("family_only", "family_plus_person", name="goalpolicyenum", create_type=False)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_person_backfill(bind) -> None:
    rows = bind.execute(
        sa.text(
            """
            SELECT fm.id, fm.family_id, fm.email, fm.display_name, fm.role
            FROM family_members fm
            LEFT JOIN persons p ON p.legacy_member_id = fm.id
            WHERE p.person_id IS NULL
            ORDER BY fm.id ASC
            """
        )
    ).mappings().all()
    for row in rows:
        bind.execute(
            sa.text(
                """
                INSERT INTO persons (
                    person_id,
                    family_id,
                    legacy_member_id,
                    canonical_name,
                    display_name,
                    role_in_family,
                    is_admin,
                    status,
                    metadata_jsonb,
                    created_at,
                    updated_at
                )
                VALUES (
                    :person_id,
                    :family_id,
                    :legacy_member_id,
                    :canonical_name,
                    :display_name,
                    :role_in_family,
                    :is_admin,
                    'active',
                    :metadata_jsonb,
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "person_id": str(uuid.uuid4()),
                "family_id": row["family_id"],
                "legacy_member_id": row["id"],
                "canonical_name": (row["display_name"] or row["email"]).strip(),
                "display_name": row["display_name"],
                "role_in_family": row["role"],
                "is_admin": row["role"] == "admin",
                "metadata_jsonb": {"source": "cutover_migration"},
                "created_at": _utcnow(),
                "updated_at": _utcnow(),
            },
        )


def _has_table(bind, table_name: str) -> bool:
    return table_name in sa.inspect(bind).get_table_names()


def _goal_owner_person_id(bind, family_id: int, legacy_member_id: int | None) -> str | None:
    if legacy_member_id is None:
        return None
    row = bind.execute(
        sa.text("SELECT person_id FROM persons WHERE family_id = :family_id AND legacy_member_id = :member_id"),
        {"family_id": family_id, "member_id": legacy_member_id},
    ).scalar_one_or_none()
    return str(row) if row is not None else None


def _backfill_score_history(bind) -> None:
    thresholds = {
        row.family_id: float(row.threshold_1_to_5)
        for row in bind.execute(sa.text("SELECT family_id, threshold_1_to_5 FROM budget_policies")).mappings().all()
    }
    decisions = bind.execute(
        sa.text(
            """
            SELECT d.id, d.family_id, d.created_by_person_id, d.version, d.status, d.goal_policy
            FROM decisions d
            ORDER BY d.id ASC
            """
        )
    ).mappings().all()
    for decision in decisions:
        score_rows = bind.execute(
            sa.text(
                """
                SELECT ds.goal_id,
                       ds.score_1_to_5,
                       ds.rationale,
                       ds.computed_by,
                       g.name AS goal_name,
                       g.weight AS goal_weight,
                       g.goal_revision,
                       g.scope_type,
                       g.owner_person_id
                FROM decision_scores ds
                JOIN goals g ON g.id = ds.goal_id
                WHERE ds.decision_id = :decision_id
                  AND ds.version = :decision_version
                ORDER BY ds.id ASC
                """
            ),
            {"decision_id": decision["id"], "decision_version": decision["version"]},
        ).mappings().all()
        if not score_rows:
            continue

        total_weight = sum(float(row["goal_weight"]) for row in score_rows)
        if total_weight <= 0:
            continue
        weighted_sum = sum(float(row["goal_weight"]) * float(row["score_1_to_5"]) for row in score_rows)
        weighted_1_to_5 = round(weighted_sum / total_weight, 2)
        weighted_0_to_100 = round((weighted_1_to_5 - 1.0) * 25.0, 2)
        threshold = thresholds.get(int(decision["family_id"]), 4.0)
        routed_to = "queue" if weighted_1_to_5 >= threshold else "needs_work"
        computed_by = str(score_rows[0]["computed_by"] or "human")
        run_id = bind.execute(
            sa.text(
                """
                INSERT INTO decision_score_runs (
                    decision_id,
                    family_id,
                    scored_by_person_id,
                    computed_by,
                    decision_version,
                    goal_policy,
                    threshold_1_to_5,
                    family_weighted_total_1_to_5,
                    family_weighted_total_0_to_100,
                    person_weighted_total_1_to_5,
                    person_weighted_total_0_to_100,
                    weighted_total_1_to_5,
                    weighted_total_0_to_100,
                    routed_to,
                    status_after_run,
                    context_snapshot_json,
                    created_at
                )
                VALUES (
                    :decision_id,
                    :family_id,
                    :scored_by_person_id,
                    :computed_by,
                    :decision_version,
                    :goal_policy,
                    :threshold_1_to_5,
                    :family_weighted_total_1_to_5,
                    :family_weighted_total_0_to_100,
                    NULL,
                    NULL,
                    :weighted_total_1_to_5,
                    :weighted_total_0_to_100,
                    :routed_to,
                    :status_after_run,
                    '{}'::jsonb,
                    NOW()
                )
                RETURNING id
                """
            ),
            {
                "decision_id": decision["id"],
                "family_id": decision["family_id"],
                "scored_by_person_id": decision["created_by_person_id"],
                "computed_by": computed_by,
                "decision_version": decision["version"],
                "goal_policy": decision["goal_policy"],
                "threshold_1_to_5": threshold,
                "family_weighted_total_1_to_5": weighted_1_to_5,
                "family_weighted_total_0_to_100": weighted_0_to_100,
                "weighted_total_1_to_5": weighted_1_to_5,
                "weighted_total_0_to_100": weighted_0_to_100,
                "routed_to": routed_to,
                "status_after_run": decision["status"],
            },
        ).scalar_one()

        for row in score_rows:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO decision_score_components (
                        score_run_id,
                        decision_id,
                        goal_id,
                        goal_scope_type,
                        goal_owner_person_id,
                        goal_revision,
                        goal_name,
                        goal_weight,
                        score_1_to_5,
                        rationale,
                        created_at
                    )
                    VALUES (
                        :score_run_id,
                        :decision_id,
                        :goal_id,
                        :goal_scope_type,
                        :goal_owner_person_id,
                        :goal_revision,
                        :goal_name,
                        :goal_weight,
                        :score_1_to_5,
                        :rationale,
                        NOW()
                    )
                    """
                ),
                {
                    "score_run_id": run_id,
                    "decision_id": decision["id"],
                    "goal_id": row["goal_id"],
                    "goal_scope_type": row["scope_type"],
                    "goal_owner_person_id": row["owner_person_id"],
                    "goal_revision": row["goal_revision"],
                    "goal_name": row["goal_name"],
                    "goal_weight": float(row["goal_weight"]),
                    "score_1_to_5": int(row["score_1_to_5"]),
                    "rationale": row["rationale"],
                },
            )


def upgrade() -> None:
    bind = op.get_bind()
    scope_type_enum.create(bind, checkfirst=True)
    visibility_scope_enum.create(bind, checkfirst=True)
    goal_status_enum.create(bind, checkfirst=True)
    goal_horizon_enum.create(bind, checkfirst=True)
    goal_policy_enum.create(bind, checkfirst=True)

    _ensure_person_backfill(bind)

    op.add_column("goals", sa.Column("scope_type", scope_type_enum, nullable=False, server_default="family"))
    op.add_column("goals", sa.Column("owner_person_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("goals", sa.Column("visibility_scope", visibility_scope_enum, nullable=False, server_default="family"))
    op.add_column("goals", sa.Column("action_types_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("goals", sa.Column("status", goal_status_enum, nullable=False, server_default="active"))
    op.add_column("goals", sa.Column("priority", sa.Integer(), nullable=True))
    op.add_column("goals", sa.Column("horizon", goal_horizon_enum, nullable=True))
    op.add_column("goals", sa.Column("target_date", sa.Date(), nullable=True))
    op.add_column("goals", sa.Column("success_criteria", sa.Text(), nullable=True))
    op.add_column("goals", sa.Column("review_cadence_days", sa.Integer(), nullable=True))
    op.add_column("goals", sa.Column("next_review_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("goals", sa.Column("tags_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("goals", sa.Column("external_refs_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("goals", sa.Column("goal_revision", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("goals", sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.add_column("goals", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.add_column("goals", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_goals_owner_person", "goals", "persons", ["owner_person_id"], ["person_id"], ondelete="SET NULL")

    op.execute(
        """
        UPDATE goals
        SET scope_type = 'family',
            visibility_scope = 'family',
            action_types_json = CASE
                WHEN action_types IS NULL OR btrim(action_types) = '' THEN '[]'::jsonb
                ELSE action_types::jsonb
            END,
            status = CASE WHEN active THEN 'active'::goalstatusenum ELSE 'paused'::goalstatusenum END,
            priority = 3,
            horizon = 'ongoing'::goalhorizonenum,
            tags_json = '[]'::jsonb,
            external_refs_json = '[]'::jsonb,
            goal_revision = 1,
            created_at = NOW(),
            updated_at = NOW()
        """
    )

    op.add_column("decisions", sa.Column("scope_type", scope_type_enum, nullable=False, server_default="family"))
    op.add_column("decisions", sa.Column("created_by_person_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("decisions", sa.Column("owner_person_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("decisions", sa.Column("target_person_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("decisions", sa.Column("visibility_scope", visibility_scope_enum, nullable=False, server_default="family"))
    op.add_column("decisions", sa.Column("goal_policy", goal_policy_enum, nullable=False, server_default="family_only"))
    op.add_column("decisions", sa.Column("category", sa.String(length=64), nullable=True))
    op.add_column("decisions", sa.Column("desired_outcome", sa.Text(), nullable=True))
    op.add_column("decisions", sa.Column("constraints_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("decisions", sa.Column("options_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("decisions", sa.Column("confidence_1_to_5", sa.Integer(), nullable=True))
    op.add_column("decisions", sa.Column("next_review_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("decisions", sa.Column("tags_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("decisions", sa.Column("attachments_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("decisions", sa.Column("links_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("decisions", sa.Column("context_snapshot_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("decisions", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.add_column("decisions", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("decisions", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_decisions_created_by_person", "decisions", "persons", ["created_by_person_id"], ["person_id"])
    op.create_foreign_key("fk_decisions_owner_person", "decisions", "persons", ["owner_person_id"], ["person_id"], ondelete="SET NULL")
    op.create_foreign_key("fk_decisions_target_person", "decisions", "persons", ["target_person_id"], ["person_id"], ondelete="SET NULL")

    op.execute(
        """
        UPDATE decisions d
        SET scope_type = 'family',
            visibility_scope = 'family',
            goal_policy = 'family_only'::goalpolicyenum,
            constraints_json = '[]'::jsonb,
            options_json = '[]'::jsonb,
            tags_json = CASE WHEN tags IS NULL OR btrim(tags) = '' THEN '[]'::jsonb ELSE tags::jsonb END,
            attachments_json = CASE WHEN attachments IS NULL OR btrim(attachments) = '' THEN '[]'::jsonb ELSE attachments::jsonb END,
            links_json = CASE WHEN links IS NULL OR btrim(links) = '' THEN '[]'::jsonb ELSE links::jsonb END,
            context_snapshot_json = '{}'::jsonb,
            updated_at = created_at
        """
    )
    op.execute(
        """
        UPDATE decisions d
        SET created_by_person_id = p.person_id
        FROM persons p
        WHERE p.legacy_member_id = d.created_by_member_id
        """
    )
    op.execute(
        """
        UPDATE decisions d
        SET owner_person_id = p.person_id
        FROM persons p
        WHERE p.legacy_member_id = d.owner_member_id
        """
    )

    op.add_column("roadmap_items", sa.Column("dependencies_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.execute(
        """
        UPDATE roadmap_items
        SET dependencies_json = CASE
            WHEN dependencies IS NULL OR btrim(dependencies) = '' THEN '[]'::jsonb
            ELSE dependencies::jsonb
        END
        """
    )

    op.add_column("discretionary_budget_ledger", sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute(
        """
        UPDATE discretionary_budget_ledger l
        SET person_id = p.person_id
        FROM persons p
        WHERE p.legacy_member_id = l.member_id
        """
    )
    op.create_foreign_key("fk_discretionary_budget_ledger_person", "discretionary_budget_ledger", "persons", ["person_id"], ["person_id"])

    op.add_column("member_budget_settings", sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute(
        """
        UPDATE member_budget_settings s
        SET person_id = p.person_id
        FROM persons p
        WHERE p.legacy_member_id = s.member_id
        """
    )
    op.create_foreign_key("fk_member_budget_settings_person", "member_budget_settings", "persons", ["person_id"], ["person_id"])

    has_audit_logs = _has_table(bind, "audit_logs")
    if has_audit_logs:
        op.add_column("audit_logs", sa.Column("actor_person_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.execute(
            """
            UPDATE audit_logs a
            SET actor_person_id = p.person_id
            FROM persons p
            WHERE p.legacy_member_id = a.actor_member_id
            """
        )
        op.create_foreign_key("fk_audit_logs_actor_person", "audit_logs", "persons", ["actor_person_id"], ["person_id"], ondelete="SET NULL")

    op.create_table(
        "decision_score_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_id", sa.Integer(), sa.ForeignKey("decisions.id"), nullable=False),
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("families.id"), nullable=False),
        sa.Column("scored_by_person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("persons.person_id", ondelete="SET NULL"), nullable=True),
        sa.Column("computed_by", sa.String(length=20), nullable=False),
        sa.Column("decision_version", sa.Integer(), nullable=False),
        sa.Column("goal_policy", goal_policy_enum, nullable=False, server_default="family_only"),
        sa.Column("threshold_1_to_5", sa.Float(), nullable=False),
        sa.Column("family_weighted_total_1_to_5", sa.Float(), nullable=True),
        sa.Column("family_weighted_total_0_to_100", sa.Float(), nullable=True),
        sa.Column("person_weighted_total_1_to_5", sa.Float(), nullable=True),
        sa.Column("person_weighted_total_0_to_100", sa.Float(), nullable=True),
        sa.Column("weighted_total_1_to_5", sa.Float(), nullable=False),
        sa.Column("weighted_total_0_to_100", sa.Float(), nullable=False),
        sa.Column("routed_to", sa.String(length=32), nullable=False),
        sa.Column("status_after_run", sa.String(length=32), nullable=False),
        sa.Column("context_snapshot_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_decision_score_runs_decision_created", "decision_score_runs", ["decision_id", "created_at"], unique=False)

    op.create_table(
        "decision_score_components",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("score_run_id", sa.Integer(), sa.ForeignKey("decision_score_runs.id"), nullable=False),
        sa.Column("decision_id", sa.Integer(), sa.ForeignKey("decisions.id"), nullable=False),
        sa.Column("goal_id", sa.Integer(), sa.ForeignKey("goals.id"), nullable=False),
        sa.Column("goal_scope_type", scope_type_enum, nullable=False),
        sa.Column("goal_owner_person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("persons.person_id", ondelete="SET NULL"), nullable=True),
        sa.Column("goal_revision", sa.Integer(), nullable=False),
        sa.Column("goal_name", sa.String(length=255), nullable=False),
        sa.Column("goal_weight", sa.Float(), nullable=False),
        sa.Column("score_1_to_5", sa.Integer(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("score_1_to_5 >= 1 AND score_1_to_5 <= 5", name="ck_score_component_range"),
    )
    op.create_index("ix_decision_score_components_run_goal", "decision_score_components", ["score_run_id", "goal_id"], unique=True)

    _backfill_score_history(bind)

    op.execute("DROP TABLE decision_scores")

    op.drop_index("ix_member_budget_settings_family_member", table_name="member_budget_settings")
    op.drop_index("ix_ledger_member_period", table_name="discretionary_budget_ledger")

    op.drop_column("goals", "action_types")
    op.drop_column("goals", "active")

    op.drop_column("roadmap_items", "dependencies")

    op.drop_column("decisions", "created_by_member_id")
    op.drop_column("decisions", "owner_member_id")
    op.drop_column("decisions", "tags")
    op.drop_column("decisions", "attachments")
    op.drop_column("decisions", "links")

    op.drop_column("discretionary_budget_ledger", "member_id")
    op.drop_column("member_budget_settings", "member_id")
    if has_audit_logs:
        op.drop_column("audit_logs", "actor_member_id")

    op.alter_column("decisions", "created_by_person_id", nullable=False)
    op.alter_column("discretionary_budget_ledger", "person_id", nullable=False)
    op.alter_column("member_budget_settings", "person_id", nullable=False)

    op.create_index("ix_goals_family_scope_status", "goals", ["family_id", "scope_type", "status"], unique=False)
    op.create_index("ix_goals_owner_person", "goals", ["owner_person_id"], unique=False)
    op.create_index("ix_goals_deleted_at", "goals", ["deleted_at"], unique=False)
    op.create_index("ix_decisions_family_scope_status", "decisions", ["family_id", "scope_type", "status"], unique=False)
    op.create_index("ix_decisions_owner_person", "decisions", ["owner_person_id"], unique=False)
    op.create_index("ix_decisions_target_person", "decisions", ["target_person_id"], unique=False)
    op.create_index("ix_decisions_deleted_at", "decisions", ["deleted_at"], unique=False)
    op.create_index("ix_ledger_person_period", "discretionary_budget_ledger", ["person_id", "period_id"], unique=False)
    op.create_index("ix_member_budget_settings_family_person", "member_budget_settings", ["family_id", "person_id"], unique=True)


def downgrade() -> None:
    raise NotImplementedError("0014_scoped_decision_management_cutover is a one-way cutover migration")
