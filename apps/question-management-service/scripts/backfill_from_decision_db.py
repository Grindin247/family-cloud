from __future__ import annotations

import os

import httpx
from sqlalchemy import create_engine, text


def main() -> None:
    decision_db_url = os.environ.get(
        "DECISION_DATABASE_URL",
        "postgresql+psycopg2://decision_user:change-me@localhost:5432/decision_system",
    )
    question_api_base_url = os.environ.get("QUESTION_API_BASE_URL", "http://localhost:8030/v1").rstrip("/")
    question_admin_token = os.environ.get("QUESTION_INTERNAL_ADMIN_TOKEN", "change-me")
    include_inactive = os.environ.get("BACKFILL_INCLUDE_INACTIVE", "").lower() in {"1", "true", "yes"}

    status_clause = "" if include_inactive else "WHERE q.status IN ('pending', 'asked', 'answered_partial')"
    query = text(
        f"""
        SELECT
          q.id,
          q.family_id,
          q.domain,
          q.source_agent,
          q.topic,
          q.summary,
          q.prompt,
          q.urgency,
          q.topic_type,
          q.status,
          q.created_at,
          q.updated_at,
          q.expires_at,
          q.due_at,
          q.last_asked_at,
          q.answer_sufficiency_state,
          q.context_json,
          q.artifact_refs,
          q.dedupe_key
        FROM agent_questions q
        {status_clause}
        ORDER BY q.family_id, q.updated_at
        """
    )

    engine = create_engine(decision_db_url)
    migrated = 0
    with engine.connect() as connection, httpx.Client(timeout=20.0) as client:
        rows = connection.execute(query).mappings().all()
        for row in rows:
            response = client.post(
                f"{question_api_base_url}/families/{int(row['family_id'])}/questions",
                headers={"X-Internal-Admin-Token": question_admin_token},
                json={
                    "domain": row["domain"],
                    "source_agent": row["source_agent"],
                    "topic": row["topic"],
                    "summary": row["summary"],
                    "prompt": row["prompt"],
                    "urgency": row["urgency"],
                    "category": row["topic_type"],
                    "topic_type": row["topic_type"],
                    "due_at": row["due_at"].isoformat() if row["due_at"] else None,
                    "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
                    "answer_sufficiency_state": row["answer_sufficiency_state"],
                    "context": row["context_json"] or {},
                    "dedupe_key": row["dedupe_key"],
                    "artifact_refs": row["artifact_refs"] or [],
                },
            )
            response.raise_for_status()
            migrated += 1

    print({"migrated": migrated})


if __name__ == "__main__":
    main()
