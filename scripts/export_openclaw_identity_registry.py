#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the shared family identity registry for OpenClaw agents.")
    parser.add_argument(
        "--output",
        default=str(Path.home() / ".openclaw" / "family-identity.json"),
        help="Output path for the generated registry JSON.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    api_root = repo_root / "apps" / "decision-system" / "apps" / "api"
    sys.path.insert(0, str(api_root))

    from app.core.db import SessionLocal
    from app.services.identity import export_openclaw_identity_registry

    output_path = os.path.abspath(args.output)
    db = SessionLocal()
    try:
        export_openclaw_identity_registry(db, output_path=output_path)
        db.commit()
    finally:
        db.close()
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
