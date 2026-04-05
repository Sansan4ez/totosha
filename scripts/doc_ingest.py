#!/usr/bin/env python3
"""Simple operator CLI for CAS-backed document intake."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from documents.storage import (  # noqa: E402
    ensure_document_layout,
    get_document_paths,
    ingest_document,
    purge_old_quarantine_objects,
    purge_old_rejected_records,
    sync_repo_inbox,
    sweep_unreferenced_blobs,
)


def _cmd_ingest(args: argparse.Namespace) -> int:
    manifest = ingest_document(args.path, source=args.source, logical_name=args.name)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def _cmd_scan_quarantine(args: argparse.Namespace) -> int:
    paths = ensure_document_layout(get_document_paths())
    candidates = sorted(path for path in paths.quarantine.iterdir() if path.is_file() and path.suffix.lower() != ".json")
    results = []
    for path in candidates:
        try:
            results.append({"path": str(path), "status": "ingested", "document_id": ingest_document(path, source=args.source)["document_id"]})
            if args.delete_source:
                path.unlink(missing_ok=True)
        except Exception as exc:
            results.append({"path": str(path), "status": "error", "error": str(exc)})
    print(json.dumps({"count": len(results), "results": results}, ensure_ascii=False, indent=2))
    return 0


def _cmd_sync_repo(args: argparse.Namespace) -> int:
    report = sync_repo_inbox(args.repo_root, source=args.source)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _cmd_sweep(args: argparse.Namespace) -> int:
    if args.target == "cas":
        payload = {"stale_blobs": sweep_unreferenced_blobs(dry_run=not args.apply)}
    elif args.target == "quarantine":
        payload = {"removed_quarantine_objects": purge_old_quarantine_objects(older_than_days=args.days)}
    else:
        payload = {"removed_rejected_records": purge_old_rejected_records(older_than_days=args.days)}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="CAS-backed document intake helpers")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Ingest one file into quarantine -> CAS -> live")
    ingest_parser.add_argument("path")
    ingest_parser.add_argument("--source", default="operator_upload")
    ingest_parser.add_argument("--name")
    ingest_parser.set_defaults(func=_cmd_ingest)

    scan_parser = subparsers.add_parser("scan-quarantine", help="Ingest every file currently present in quarantine")
    scan_parser.add_argument("--source", default="quarantine_scan")
    scan_parser.add_argument("--delete-source", action="store_true")
    scan_parser.set_defaults(func=_cmd_scan_quarantine)

    sync_parser = subparsers.add_parser("sync-repo", help="Ingest every eligible file from doc-corpus/inbox")
    sync_parser.add_argument("--repo-root")
    sync_parser.add_argument("--source", default="repo_inbox")
    sync_parser.set_defaults(func=_cmd_sync_repo)

    sweep_parser = subparsers.add_parser("sweep", help="Maintenance for rejected records or stale CAS blobs")
    sweep_parser.add_argument("target", choices=["cas", "quarantine", "rejected"])
    sweep_parser.add_argument("--apply", action="store_true")
    sweep_parser.add_argument("--days", type=int, default=14)
    sweep_parser.set_defaults(func=_cmd_sweep)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
