from __future__ import annotations

import os

from sqlalchemy import MetaData, create_engine, text


TABLES = ("family_events", "family_event_dead_letters", "family_event_export_jobs")


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def main() -> None:
    source_url = _required_env("DECISION_LEGACY_DATABASE_URL")
    target_url = _required_env("FAMILY_EVENT_DATABASE_URL")
    source = create_engine(source_url)
    target = create_engine(target_url)
    target_metadata = MetaData()
    target_metadata.reflect(bind=target, only=list(TABLES))
    with source.connect() as source_conn, target.begin() as target_conn:
        for table in TABLES:
            rows = source_conn.execute(text(f"SELECT * FROM {table}")).mappings().all()
            if not rows:
                print(f"{table}: no rows")
                continue
            table_def = target_metadata.tables[table]
            target_conn.execute(text(f"DELETE FROM {table}"))
            target_conn.execute(table_def.insert(), [dict(row) for row in rows])
            print(f"{table}: copied {len(rows)} rows")


if __name__ == "__main__":
    main()
