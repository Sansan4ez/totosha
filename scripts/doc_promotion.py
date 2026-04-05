#!/usr/bin/env python3
"""Promotion candidate reports and corp-db export helpers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from documents.promotion import export_document_for_corp_db  # noqa: E402
from documents.usage import write_promotion_candidates_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="doc_search promotion helpers")
    subparsers = parser.add_subparsers(dest="command", required=True)

    report_parser = subparsers.add_parser("report", help="Build promotion candidates from recorded usage stats")
    report_parser.add_argument("--min-hits", type=int, default=2)

    export_parser = subparsers.add_parser("export", help="Export one document into corp-db-ready JSONL chunks")
    export_parser.add_argument("document_id")

    args = parser.parse_args()
    if args.command == "report":
        payload = write_promotion_candidates_report(min_hits=args.min_hits)
    else:
        payload = export_document_for_corp_db(args.document_id)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
