"""Parsed sidecars keyed by CAS content hash and normalization config."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import ensure_document_layout, get_document_paths


PARSER_VERSION = "doc_search_v3"


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def cache_version_key() -> str:
    ocr_config = {
        "ocr_enabled": os.getenv("DOC_SEARCH_OCR_ENABLED", "1"),
        "ocr_language": os.getenv("DOC_SEARCH_OCR_LANGUAGE", "eng"),
        "ocr_server_url": os.getenv("DOC_SEARCH_OCR_SERVER_URL", ""),
        "liteparse_dpi": os.getenv("DOC_SEARCH_LITEPARSE_DPI", "150"),
        "liteparse_max_pages": os.getenv("DOC_SEARCH_LITEPARSE_MAX_PAGES", "250"),
    }
    encoded = json.dumps({"parser_version": PARSER_VERSION, "ocr": ocr_config}, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _sidecar_dir(sha256: str) -> Path:
    paths = ensure_document_layout(get_document_paths())
    return paths.parsed / sha256 / cache_version_key()


def current_sidecar_dir(sha256: str | None) -> Path | None:
    if not sha256:
        return None
    return _sidecar_dir(sha256)


def _write_atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _jsonl_rows_from_structured(structured: dict[str, Any] | None, text: str) -> list[dict[str, Any]]:
    if not isinstance(structured, dict):
        structured = {}
    for key in ("pages", "slides", "sheets"):
        rows = structured.get(key)
        if isinstance(rows, list) and rows:
            normalized: list[dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                normalized.append({k: row.get(k) for k in row.keys() if k in {"page", "sheet", "slide", "text"}})
            if normalized:
                return normalized
    if text:
        return [{"page": 1, "text": text}]
    return []


def _structured_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    if any("slide" in row for row in rows):
        return {"slides": rows}
    if any("sheet" in row for row in rows):
        return {"sheets": rows}
    return {"pages": rows}


def load_parse_cache(sha256: str | None) -> dict[str, Any] | None:
    if not sha256:
        return None
    base = _sidecar_dir(sha256)
    text_path = base / "text.txt"
    pages_path = base / "pages.jsonl"
    meta_path = base / "meta.json"
    if not text_path.exists() or not meta_path.exists():
        return None
    try:
        payload: dict[str, Any] = {
            "text": text_path.read_text(encoding="utf-8", errors="replace"),
            "meta": json.loads(meta_path.read_text(encoding="utf-8")),
            "sidecar_dir": str(base),
        }
        if pages_path.exists():
            rows = [
                json.loads(line)
                for line in pages_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            payload["structured"] = _structured_from_rows(rows)
        return payload
    except Exception:
        return None


def write_parse_cache(
    sha256: str | None,
    *,
    text: str,
    structured: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not sha256:
        return None
    base = _sidecar_dir(sha256)
    base.mkdir(parents=True, exist_ok=True)
    _write_atomic_text(base / "text.txt", text)
    rows = _jsonl_rows_from_structured(structured, text)
    _write_atomic_text(
        base / "pages.jsonl",
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
    )
    payload = dict(meta or {})
    payload.setdefault("parser_version", PARSER_VERSION)
    payload.setdefault("ocr_config_hash", cache_version_key())
    payload.setdefault("written_at", _utcnow())
    payload.setdefault("status", "success" if text else "empty")
    _write_atomic_text(base / "meta.json", json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return {"sidecar_dir": str(base), "meta": payload}
