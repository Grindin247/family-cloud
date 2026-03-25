#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.common.retrieval import summarize_search_result, search_index


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query the Family Cloud indexed retrieval service for top-level agents.")
    parser.add_argument("kind", choices=("documents", "files", "notes"))
    parser.add_argument("--query", required=True, help="User-facing search query text.")
    parser.add_argument("--speaker", help="Current speaker display name or alias.")
    parser.add_argument("--actor-id", help="Resolved actor account id/email.")
    parser.add_argument("--family-id", type=int, help="Explicit family id override.")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--base-url", help="Override FILE_API_BASE_URL.")
    parser.add_argument("--owner-person-id")
    parser.add_argument("--date-from")
    parser.add_argument("--date-to")
    parser.add_argument("--document-kind", action="append", dest="document_kinds", default=[])
    parser.add_argument("--item-type", action="append", dest="preferred_item_types", default=[])
    parser.add_argument("--content-type", action="append", dest="content_types", default=[])
    parser.add_argument("--tag", action="append", dest="query_tags", default=[])
    parser.add_argument("--no-content", action="store_false", dest="include_content")
    parser.set_defaults(include_content=True)
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    result = search_index(
        args.kind,
        query_text=args.query,
        speaker=args.speaker,
        actor_id=args.actor_id,
        family_id=args.family_id,
        top_k=args.top_k,
        include_content=args.include_content,
        owner_person_id=args.owner_person_id,
        date_from=args.date_from,
        date_to=args.date_to,
        document_kinds=args.document_kinds,
        preferred_item_types=args.preferred_item_types,
        content_types=args.content_types,
        query_tags=args.query_tags,
        base_url=args.base_url,
    )
    print(json.dumps(summarize_search_result(result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
