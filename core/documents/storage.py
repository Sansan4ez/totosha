"""CAS-backed document intake and discovery."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Any


DEFAULT_CORP_DOCS_ROOT = "/data/corp_docs"
DEFAULT_DOC_REPO_ROOT = "/repo"
DEFAULT_MAX_FILE_BYTES = 32 * 1024 * 1024
DEFAULT_REJECT_RETENTION_DAYS = 14

ALLOWED_EXTENSIONS = {
    ".md",
    ".txt",
    ".csv",
    ".json",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
}
LEGACY_BINARY_OFFICE_EXTENSIONS = {".doc", ".xls", ".ppt"}

MACRO_ENTRY_RE = re.compile(r"(^|/)(vbaproject\.bin|macros/)", re.IGNORECASE)


@dataclass(frozen=True)
class DocumentPaths:
    root: Path
    quarantine: Path
    live: Path
    cache: Path
    parsed: Path
    rejected: Path
    manifests: Path
    cas: Path
    usage_stats: Path
    promotion_candidates: Path
    sync_reports: Path


@dataclass(frozen=True)
class RepoPaths:
    root: Path
    doc_corpus: Path
    inbox: Path
    manifests: Path


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip())
    return cleaned[:180] or "document"


def detect_file_type(path: str | Path) -> str:
    suffix = Path(path).suffix.lower().lstrip(".")
    return suffix or "unknown"


def get_document_paths() -> DocumentPaths:
    root = Path(os.getenv("CORP_DOCS_ROOT", DEFAULT_CORP_DOCS_ROOT))
    manifests = root / "manifests"
    return DocumentPaths(
        root=root,
        quarantine=root / "quarantine",
        live=root / "live",
        cache=root / "cache",
        parsed=root / "parsed",
        rejected=root / "rejected",
        manifests=manifests,
        cas=root / "cas",
        usage_stats=manifests / "usage_stats.jsonl",
        promotion_candidates=manifests / "promotion_candidates.json",
        sync_reports=manifests / "sync_reports",
    )


def get_repo_paths(repo_root: str | Path | None = None) -> RepoPaths:
    root = Path(repo_root or os.getenv("DOC_REPO_ROOT", DEFAULT_DOC_REPO_ROOT))
    doc_corpus = root / "doc-corpus"
    return RepoPaths(
        root=root,
        doc_corpus=doc_corpus,
        inbox=doc_corpus / "inbox",
        manifests=doc_corpus / "manifests",
    )


def ensure_document_layout(paths: DocumentPaths | None = None) -> DocumentPaths:
    paths = paths or get_document_paths()
    for path in (
        paths.root,
        paths.quarantine,
        paths.live,
        paths.cache,
        paths.parsed,
        paths.rejected,
        paths.manifests,
        paths.manifests / "documents",
        paths.manifests / "promotion",
        paths.sync_reports,
        paths.cas / "sha256",
    ):
        path.mkdir(parents=True, exist_ok=True)
    return paths


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cas_blob_path(paths: DocumentPaths, sha256: str) -> Path:
    return paths.cas / "sha256" / sha256[:2] / sha256[2:4] / sha256


def _full_manifest_path(paths: DocumentPaths, document_id: str) -> Path:
    return paths.manifests / "documents" / f"{document_id}.json"


def _live_record_path(paths: DocumentPaths, document_id: str) -> Path:
    return paths.live / f"{document_id}.json"


def _base_manifest(
    *,
    document_id: str,
    sha256: str,
    cas_path: Path,
    filename: str,
    media_type: str,
    size_bytes: int,
    source: str,
) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "sha256": sha256,
        "cas_path": str(cas_path),
        "cas_relpath": str(cas_path.relative_to(cas_path.parents[3])),
        "original_filename": filename,
        "media_type": media_type,
        "size_bytes": size_bytes,
        "file_type": detect_file_type(filename),
        "status": "live",
        "created_at": _utcnow(),
        "updated_at": _utcnow(),
        "source": source,
        "sources": [],
        "aliases": [],
        "normalization": {"status": "pending", "backend": None, "sidecar_dir": None, "updated_at": None},
        "promotion": {"state": "pending", "last_promoted_sha256": None, "updated_at": None},
    }


def _thin_live_record(manifest: dict[str, Any]) -> dict[str, Any]:
    aliases = manifest.get("aliases") or []
    primary_alias = aliases[0] if aliases else {}
    return {
        "document_id": manifest["document_id"],
        "sha256": manifest["sha256"],
        "cas_path": manifest["cas_path"],
        "file_type": manifest.get("file_type", "unknown"),
        "media_type": manifest.get("media_type"),
        "size_bytes": manifest.get("size_bytes"),
        "status": "live",
        "relative_path": primary_alias.get("relative_path") or primary_alias.get("name") or manifest.get("original_filename"),
        "original_filename": manifest.get("original_filename"),
        "aliases": aliases,
        "routing": manifest.get("routing") if isinstance(manifest.get("routing"), dict) else {},
        "normalization": manifest.get("normalization") or {},
        "promotion": manifest.get("promotion") or {},
        "updated_at": manifest.get("updated_at"),
    }


def _write_json_atomic(target: Path, payload: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=target.name, suffix=".tmp", dir=str(target.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp_path.chmod(0o644)
        os.replace(tmp_path, target)
        target.chmod(0o644)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def _sniff_media_type(path: Path) -> str:
    media_type, _ = mimetypes.guess_type(str(path))
    return media_type or "application/octet-stream"


def _append_unique_entry(items: list[dict[str, Any]], candidate: dict[str, Any], unique_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    for item in items:
        if all(item.get(key) == candidate.get(key) for key in unique_keys):
            item.update(candidate)
            return items
    items.append(candidate)
    return items


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        lowered = text.lower()
        if not text or lowered in seen:
            continue
        seen.add(lowered)
        result.append(text)
    return result


def _routing_metadata_payload(
    metadata: dict[str, Any] | None,
    *,
    document_id: str,
    relative_path: str,
    filename: str,
) -> dict[str, Any] | None:
    if not isinstance(metadata, dict):
        return None
    payload: dict[str, Any] = {}
    for key in ("title", "summary", "route_id", "route_family"):
        value = str(metadata.get(key) or "").strip()
        if value:
            payload[key] = value
    for key in ("tags", "topics", "keywords", "patterns"):
        values = _string_list(metadata.get(key))
        if values:
            payload[key] = values
    if not payload:
        return None
    payload["document_id"] = document_id
    payload["relative_path"] = relative_path
    payload["original_filename"] = filename
    return payload


def _detect_macro_or_unsafe_zip(path: Path) -> str | None:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if any(MACRO_ENTRY_RE.search(name) for name in names):
                return "office_macros_not_allowed"
    except zipfile.BadZipFile:
        return "malformed_zip"
    return None


def _legacy_office_runtime_available() -> bool:
    if os.getenv("DOC_SEARCH_ENABLE_LEGACY_OFFICE", "0").lower() not in {"1", "true", "yes"}:
        return False
    return shutil.which("lit") is not None and shutil.which("soffice") is not None


def _is_pdf_encrypted(path: Path) -> bool:
    try:
        head = path.read_bytes()[:64 * 1024]
    except Exception:
        return False
    return b"/Encrypt" in head


def _validate_document(path: Path, *, original_name: str) -> tuple[bool, str]:
    suffix = path.suffix.lower()
    if suffix in LEGACY_BINARY_OFFICE_EXTENSIONS:
        if not _legacy_office_runtime_available():
            return False, "legacy_office_binary_requires_doc_worker_runtime"
    if suffix not in ALLOWED_EXTENSIONS:
        return False, "unsupported_extension"

    max_bytes = int(os.getenv("CORP_DOCS_MAX_FILE_BYTES", str(DEFAULT_MAX_FILE_BYTES)))
    if path.stat().st_size > max_bytes:
        return False, "file_too_large"

    if suffix == ".pdf" and _is_pdf_encrypted(path):
        return False, "encrypted_pdf_not_allowed"

    if suffix in {".docx", ".xlsx", ".pptx"}:
        issue = _detect_macro_or_unsafe_zip(path)
        if issue:
            return False, issue

    if original_name.startswith("."):
        return False, "hidden_file_not_allowed"

    return True, "ok"


def _write_rejection_record(paths: DocumentPaths, *, source_path: Path, filename: str, reason: str, source: str) -> dict[str, Any]:
    record = {
        "status": "rejected",
        "filename": filename,
        "source_path": str(source_path),
        "reason": reason,
        "source": source,
        "created_at": _utcnow(),
    }
    reject_id = f"reject_{uuid.uuid4().hex[:12]}"
    target = paths.rejected / f"{reject_id}.json"
    _write_json_atomic(target, record)
    return record


def _load_metadata_sidecar(source_path: Path) -> tuple[dict[str, Any] | None, str | None]:
    sidecar_path = Path(f"{source_path}.meta.json")
    if not sidecar_path.exists():
        return None, None
    try:
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except Exception:
        return None, "invalid_metadata_json"
    if payload is None:
        return None, None
    if not isinstance(payload, dict):
        return None, "invalid_metadata_type"
    return payload, None


def _ingest_document_impl(
    source_path: str | Path,
    *,
    source: str,
    logical_name: str | None,
    metadata: dict[str, Any] | None,
    relative_path: str | None,
) -> dict[str, Any]:
    source_path = Path(source_path)
    paths = ensure_document_layout()

    if not source_path.exists() or not source_path.is_file():
        raise FileNotFoundError(source_path)

    filename = _normalize_filename(logical_name or source_path.name)
    alias_relative_path = (relative_path or filename).replace("\\", "/")
    quarantine_path = paths.quarantine / f"{uuid.uuid4().hex}_{filename}"
    shutil.copy2(source_path, quarantine_path)

    is_valid, reason = _validate_document(quarantine_path, original_name=filename)
    if not is_valid:
        record = _write_rejection_record(paths, source_path=source_path, filename=filename, reason=reason, source=source)
        quarantine_path.unlink(missing_ok=True)
        return {
            "status": "rejected",
            "reason": reason,
            "record": record,
        }

    sha256 = _sha256_file(quarantine_path)
    document_id = f"doc_{sha256[:16]}"
    media_type = _sniff_media_type(source_path)
    cas_path = _cas_blob_path(paths, sha256)
    cas_path.parent.mkdir(parents=True, exist_ok=True)
    cas_preexisting = cas_path.exists()

    if cas_preexisting:
        quarantine_path.unlink(missing_ok=True)
    else:
        os.replace(quarantine_path, cas_path)

    manifest_path = _full_manifest_path(paths, document_id)
    manifest_preexisting = manifest_path.exists()
    if manifest_preexisting:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = _base_manifest(
            document_id=document_id,
            sha256=sha256,
            cas_path=cas_path,
            filename=filename,
            media_type=media_type,
            size_bytes=cas_path.stat().st_size,
            source=source,
        )

    alias_entry = {
        "name": filename,
        "relative_path": alias_relative_path,
        "source": source,
        "ingested_at": _utcnow(),
    }
    source_entry = {
        "source": source,
        "filename": filename,
        "relative_path": alias_relative_path,
        "ingested_at": _utcnow(),
    }
    if metadata:
        alias_entry["metadata"] = metadata
        source_entry["metadata"] = metadata
        routing_payload = _routing_metadata_payload(
            metadata,
            document_id=document_id,
            relative_path=alias_relative_path,
            filename=filename,
        )
        if routing_payload:
            manifest["routing"] = routing_payload

    manifest["aliases"] = _append_unique_entry(list(manifest.get("aliases") or []), alias_entry, ("relative_path", "source"))
    manifest["sources"] = _append_unique_entry(list(manifest.get("sources") or []), source_entry, ("source", "relative_path"))
    manifest["updated_at"] = _utcnow()
    try:
        from .normalize import normalize_record

        normalization = normalize_record(manifest)
        normalization["updated_at"] = _utcnow()
        manifest["normalization"] = normalization
    except Exception as exc:
        manifest["normalization"] = {
            "status": "error",
            "backend": "error",
            "error_type": type(exc).__name__,
            "error": str(exc)[:200],
            "updated_at": _utcnow(),
        }

    _write_json_atomic(manifest_path, manifest)
    _write_json_atomic(_live_record_path(paths, document_id), _thin_live_record(manifest))
    return {
        "status": "duplicate" if manifest_preexisting or cas_preexisting else "ingested",
        "reason": None,
        "manifest": manifest,
    }


def ingest_document(
    source_path: str | Path,
    *,
    source: str = "operator_upload",
    logical_name: str | None = None,
    metadata: dict[str, Any] | None = None,
    relative_path: str | None = None,
) -> dict[str, Any]:
    """Copy a document into quarantine, validate it, deduplicate into CAS, and publish a live record."""
    outcome = _ingest_document_impl(
        source_path,
        source=source,
        logical_name=logical_name,
        metadata=metadata,
        relative_path=relative_path,
    )
    if outcome["status"] == "rejected":
        raise ValueError(json.dumps(outcome["record"], ensure_ascii=False))
    return dict(outcome["manifest"])


def ingest_document_with_report(
    source_path: str | Path,
    *,
    source: str = "operator_upload",
    logical_name: str | None = None,
    metadata: dict[str, Any] | None = None,
    relative_path: str | None = None,
) -> dict[str, Any]:
    return _ingest_document_impl(
        source_path,
        source=source,
        logical_name=logical_name,
        metadata=metadata,
        relative_path=relative_path,
    )


def sync_repo_inbox(
    repo_root: str | Path | None = None,
    *,
    source: str = "repo_inbox",
) -> dict[str, Any]:
    repo_paths = get_repo_paths(repo_root)
    runtime_paths = ensure_document_layout(get_document_paths())
    results: list[dict[str, Any]] = []
    counts = {"ingested": 0, "duplicate": 0, "rejected": 0, "skipped": 0}

    if repo_paths.inbox.exists():
        candidates = sorted(
            path
            for path in repo_paths.inbox.rglob("*")
            if path.is_file() and not path.name.endswith(".meta.json") and not path.name.startswith(".")
        )
    else:
        candidates = []

    for path in candidates:
        relative_path = str(path.relative_to(repo_paths.inbox)).replace("\\", "/")
        metadata, metadata_error = _load_metadata_sidecar(path)
        if metadata_error:
            record = _write_rejection_record(
                runtime_paths,
                source_path=path,
                filename=path.name,
                reason=metadata_error,
                source=source,
            )
            outcome = {
                "status": "rejected",
                "reason": metadata_error,
                "relative_path": relative_path,
                "record": record,
            }
        else:
            outcome = ingest_document_with_report(
                path,
                source=source,
                logical_name=path.name,
                metadata=metadata,
                relative_path=relative_path,
            )
            outcome["relative_path"] = relative_path

        counts[outcome["status"]] = counts.get(outcome["status"], 0) + 1
        if outcome["status"] in {"ingested", "duplicate"}:
            manifest = dict(outcome["manifest"])
            results.append(
                {
                    "status": outcome["status"],
                    "document_id": manifest["document_id"],
                    "sha256": manifest["sha256"],
                    "relative_path": relative_path,
                    "metadata_present": metadata is not None,
                }
            )
        else:
            results.append(
                {
                    "status": "rejected",
                    "reason": outcome["reason"],
                    "relative_path": relative_path,
                }
            )

    report = {
        "status": "ok",
        "source": source,
        "repo_root": str(repo_paths.root),
        "inbox": str(repo_paths.inbox),
        "result_count": len(results),
        "counts": counts,
        "results": results,
        "generated_at": _utcnow(),
    }
    report_path = runtime_paths.sync_reports / f"sync_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    _write_json_atomic(report_path, report)
    report["report_path"] = str(report_path)
    try:
        from .routing import build_routing_index

        built = build_routing_index()
        report["route_count"] = built.get("route_count", 0)
    except Exception:
        report["route_count"] = 0
    return report


def load_live_document(document_id: str, paths: DocumentPaths | None = None) -> dict[str, Any]:
    paths = paths or get_document_paths()
    live_path = _live_record_path(paths, document_id)
    return json.loads(live_path.read_text(encoding="utf-8"))


def iter_live_documents(paths: DocumentPaths | None = None) -> Iterator[dict[str, Any]]:
    paths = paths or get_document_paths()
    if not paths.live.exists():
        return
    for path in sorted(paths.live.glob("*.json")):
        try:
            yield json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue


def find_document_by_sha256(sha256: str, paths: DocumentPaths | None = None) -> dict[str, Any] | None:
    paths = paths or get_document_paths()
    manifest_path = _full_manifest_path(paths, f"doc_{sha256[:16]}")
    if not manifest_path.exists():
        return None
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def sweep_unreferenced_blobs(paths: DocumentPaths | None = None, *, dry_run: bool = True) -> list[str]:
    paths = ensure_document_layout(paths)
    referenced = {
        str(Path(record.get("cas_path")))
        for record in iter_live_documents(paths)
        if record.get("cas_path")
    }
    stale: list[str] = []
    for blob in sorted(path for path in (paths.cas / "sha256").rglob("*") if path.is_file()):
        if str(blob) not in referenced:
            stale.append(str(blob))
            if not dry_run:
                blob.unlink(missing_ok=True)
    return stale


def purge_old_rejected_records(paths: DocumentPaths | None = None, *, older_than_days: int = DEFAULT_REJECT_RETENTION_DAYS) -> list[str]:
    paths = ensure_document_layout(paths)
    threshold = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    removed: list[str] = []
    for record_path in sorted(paths.rejected.glob("*.json")):
        try:
            payload = json.loads(record_path.read_text(encoding="utf-8"))
            created_at = payload.get("created_at", "")
            created_dt = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        except Exception:
            created_dt = datetime.now(timezone.utc)
        if created_dt < threshold:
            record_path.unlink(missing_ok=True)
            removed.append(str(record_path))
    return removed


def purge_old_quarantine_objects(paths: DocumentPaths | None = None, *, older_than_days: int = DEFAULT_REJECT_RETENTION_DAYS) -> list[str]:
    paths = ensure_document_layout(paths)
    threshold = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    removed: list[str] = []
    for file_path in sorted(path for path in paths.quarantine.iterdir() if path.is_file()):
        modified = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
        if modified < threshold:
            file_path.unlink(missing_ok=True)
            removed.append(str(file_path))
    return removed
