#!/usr/bin/env python3
"""Operator-side document worker for RFC-010."""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_REPO_CORE = _HERE.parent / "core"
for candidate in (_HERE, _REPO_CORE):
    candidate_str = str(candidate)
    if candidate.exists() and candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from documents.normalize import rebuild_parsed_sidecars
from documents.routing import build_routing_index
from documents.storage import ensure_document_layout, get_document_paths, ingest_document, iter_live_documents, sync_repo_inbox
from documents.cache import load_parse_cache


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("doc_worker")


REQUIRED_BINARIES = ("lit", "soffice", "magick", "rg", "fd", "jq")


@dataclass(frozen=True)
class WorkerContext:
    repo_root: Path
    docs_root: Path


def _ctx() -> WorkerContext:
    return WorkerContext(
        repo_root=Path(os.getenv("DOC_REPO_ROOT", "/repo")),
        docs_root=Path(os.getenv("CORP_DOCS_ROOT", "/data/corp_docs")),
    )


def _json_dump(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _binary_status(name: str) -> dict[str, Any]:
    resolved = shutil.which(name)
    return {"name": name, "available": bool(resolved), "path": resolved}


def _doctor_payload() -> dict[str, Any]:
    context = _ctx()
    binaries = [_binary_status(name) for name in REQUIRED_BINARIES]
    paths = ensure_document_layout(get_document_paths())
    live_records = list(iter_live_documents(paths))
    parsed_current = 0
    missing_current: list[str] = []
    for record in live_records:
        if load_parse_cache(record.get("sha256")):
            parsed_current += 1
        else:
            missing_current.append(str(record.get("document_id") or ""))
    route_index_path = paths.manifests / "routes" / "index.json"
    route_count = 0
    if route_index_path.exists():
        try:
            route_count = int(json.loads(route_index_path.read_text(encoding="utf-8")).get("route_count") or 0)
        except Exception:
            route_count = 0
    corpus = {
        "live_documents": len(live_records),
        "parsed_current": parsed_current,
        "missing_current": len(missing_current),
        "missing_current_document_ids": missing_current[:20],
        "rejected_records": sum(1 for _ in paths.rejected.glob("*.json")) if paths.rejected.exists() else 0,
        "sync_reports": sum(1 for _ in paths.sync_reports.glob("*.json")) if paths.sync_reports.exists() else 0,
        "route_index_present": route_index_path.exists(),
        "route_count": route_count,
    }
    return {
        "status": "ok" if all(item["available"] for item in binaries) and corpus["missing_current"] == 0 else "warn",
        "repo_root": str(context.repo_root),
        "docs_root": str(context.docs_root),
        "binaries": binaries,
        "corpus": corpus,
        "paths": {
            "repo_exists": context.repo_root.exists(),
            "docs_root_exists": context.docs_root.exists(),
        },
    }


def _cmd_doctor(args: argparse.Namespace) -> int:
    payload = _doctor_payload()
    _json_dump(payload)
    if args.strict and payload["status"] != "ok":
        return 1
    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    manifest = ingest_document(args.path, source=args.source, logical_name=args.name)
    _json_dump({"status": "ok", "command": "ingest", "manifest": manifest})
    return 0


def _placeholder(command: str, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "status": "ok",
        "command": command,
        "mode": "foundation",
        "message": "Command interface is ready; full RFC-010 behavior is implemented in dependent tasks.",
    }
    if extra:
        payload.update(extra)
    return payload


def _cmd_sync_repo(args: argparse.Namespace) -> int:
    report = sync_repo_inbox(args.repo_root, source=args.source)
    report["command"] = "sync-repo"
    _json_dump(report)
    return 0


def _cmd_rebuild_parsed(args: argparse.Namespace) -> int:
    report = rebuild_parsed_sidecars(force=args.force)
    report["command"] = "rebuild-parsed"
    report["corpus_root"] = str(ensure_document_layout(get_document_paths()).root)
    _json_dump(report)
    return 0


def _cmd_rebuild_routes(args: argparse.Namespace) -> int:
    payload = build_routing_index()
    payload["command"] = "rebuild-routes"
    payload["route_dir"] = str(ensure_document_layout(get_document_paths()).manifests / "routes")
    _json_dump(payload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operator-side document worker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor_parser = subparsers.add_parser("doctor", help="Check whether doc-worker runtime dependencies are available")
    doctor_parser.add_argument("--strict", action="store_true", help="Exit non-zero if required binaries are missing")
    doctor_parser.set_defaults(func=_cmd_doctor)

    ingest_parser = subparsers.add_parser("ingest", help="Ingest one file into the managed document corpus")
    ingest_parser.add_argument("path")
    ingest_parser.add_argument("--source", default="doc_worker_ingest")
    ingest_parser.add_argument("--name")
    ingest_parser.set_defaults(func=_cmd_ingest)

    sync_parser = subparsers.add_parser("sync-repo", help="Sync repo inbox into the managed corpus")
    sync_parser.add_argument("--repo-root")
    sync_parser.add_argument("--source", default="repo_inbox")
    sync_parser.set_defaults(func=_cmd_sync_repo)

    parsed_parser = subparsers.add_parser("rebuild-parsed", help="Rebuild parsed sidecars for live documents")
    parsed_parser.add_argument("--force", action="store_true")
    parsed_parser.set_defaults(func=_cmd_rebuild_parsed)

    routes_parser = subparsers.add_parser("rebuild-routes", help="Rebuild document routing cards")
    routes_parser.set_defaults(func=_cmd_rebuild_routes)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
