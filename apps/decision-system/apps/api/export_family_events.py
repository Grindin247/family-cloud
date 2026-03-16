from __future__ import annotations

import argparse
from datetime import datetime

from app.core.db import SessionLocal
from app.services.family_events import export_family_events_jsonl


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Export canonical family events as anonymized JSONL.")
    parser.add_argument("--family-id", type=int, required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--start")
    parser.add_argument("--end")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        job = export_family_events_jsonl(
            db,
            family_id=args.family_id,
            actor=args.actor,
            output_path=args.output,
            start=_parse_dt(args.start),
            end=_parse_dt(args.end),
        )
        db.commit()
    finally:
        db.close()
    print(job.output_path)


if __name__ == "__main__":
    main()
