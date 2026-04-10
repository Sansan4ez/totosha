"""Normalization helpers for ingest-time parsed sidecars."""

from __future__ import annotations

from contextlib import contextmanager
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any
from xml.etree import ElementTree as ET

try:
    import resource
except Exception:  # pragma: no cover - non-POSIX fallback
    resource = None

from .cache import cache_version_key, current_sidecar_dir, load_parse_cache, write_parse_cache
from .storage import detect_file_type, iter_live_documents


logger = logging.getLogger(__name__)

WORD_RE = re.compile(r"[\wА-Яа-яЁё]+", re.UNICODE)
XML_NS_RE = re.compile(r"\{[^}]+\}")
TEXT_FILE_TYPES = {"md", "txt", "csv", "json"}
OFFICE_XML_FILE_TYPES = {"docx", "xlsx", "pptx"}
PARSER_FIRST_FILE_TYPES = {"pdf", "doc", "xls", "ppt", "png", "jpg", "jpeg", "tiff", "tif"}
MAX_TEXT_BYTES = 1_000_000
_PROCESS_SEMAPHORE = threading.BoundedSemaphore(
    max(1, min(int(os.getenv("DOC_SEARCH_MAX_CONCURRENT_PROCESSES", "2")), 8))
)


@dataclass
class SearchLimits:
    max_results: int
    max_context_chars: int
    max_documents: int
    max_file_bytes: int
    command_timeout_s: float
    liteparse_max_pages: int


def load_search_limits() -> SearchLimits:
    return SearchLimits(
        max_results=max(1, min(int(os.getenv("DOC_SEARCH_MAX_RESULTS", "8")), 20)),
        max_context_chars=max(80, min(int(os.getenv("DOC_SEARCH_CONTEXT_CHARS", "220")), 600)),
        max_documents=max(1, min(int(os.getenv("DOC_SEARCH_MAX_DOCUMENTS", "200")), 2000)),
        max_file_bytes=max(1024, int(os.getenv("DOC_SEARCH_MAX_FILE_BYTES", str(16 * 1024 * 1024)))),
        command_timeout_s=max(1.0, min(float(os.getenv("DOC_SEARCH_COMMAND_TIMEOUT_S", "15")), 120.0)),
        liteparse_max_pages=max(1, min(int(os.getenv("DOC_SEARCH_LITEPARSE_MAX_PAGES", "250")), 10000)),
    )


def _collapse_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _strip_xml_namespaces(root: ET.Element) -> None:
    for elem in root.iter():
        elem.tag = XML_NS_RE.sub("", str(elem.tag))


def _read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")[:MAX_TEXT_BYTES]


def _extract_docx_text(path: Path) -> str:
    texts: list[str] = []
    with zipfile.ZipFile(path) as archive:
        for name in ("word/document.xml", "word/footnotes.xml", "word/header1.xml", "word/footer1.xml"):
            if name not in archive.namelist():
                continue
            root = ET.fromstring(archive.read(name))
            _strip_xml_namespaces(root)
            texts.extend(node.text or "" for node in root.iter("t"))
    return "\n".join(part for part in texts if part).strip()


def _extract_pptx_text(path: Path) -> tuple[str, dict[str, Any]]:
    slides: list[dict[str, Any]] = []
    with zipfile.ZipFile(path) as archive:
        slide_names = sorted(name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml"))
        for slide_index, name in enumerate(slide_names, start=1):
            root = ET.fromstring(archive.read(name))
            _strip_xml_namespaces(root)
            parts = [node.text or "" for node in root.iter("t") if (node.text or "").strip()]
            slide_text = " ".join(parts).strip()
            if slide_text:
                slides.append({"slide": slide_index, "text": slide_text})
    return "\n".join(item["text"] for item in slides), {"slides": slides}


def _extract_xlsx_text(path: Path) -> tuple[str, dict[str, Any]]:
    sheets: list[dict[str, Any]] = []
    with zipfile.ZipFile(path) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            _strip_xml_namespaces(root)
            shared_strings = [(node.text or "") for node in root.iter("t")]

        sheet_names = sorted(name for name in archive.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"))
        for sheet_index, name in enumerate(sheet_names, start=1):
            root = ET.fromstring(archive.read(name))
            _strip_xml_namespaces(root)
            values: list[str] = []
            for cell in root.iter("c"):
                cell_type = cell.attrib.get("t")
                value = ""
                v_node = cell.find("v")
                if cell_type == "s" and v_node is not None and (v_node.text or "").isdigit():
                    idx = int(v_node.text or "0")
                    if 0 <= idx < len(shared_strings):
                        value = shared_strings[idx]
                elif v_node is not None and v_node.text:
                    value = v_node.text
                if value:
                    values.append(value)
            sheet_text = " ".join(values).strip()
            if sheet_text:
                sheets.append({"sheet": sheet_index, "text": sheet_text})
    return "\n".join(item["text"] for item in sheets), {"sheets": sheets}


def _decode_pdf_literal(value: str) -> str:
    return (
        value.replace(r"\(", "(")
        .replace(r"\)", ")")
        .replace(r"\n", " ")
        .replace(r"\r", " ")
        .replace(r"\t", " ")
    )


def _extract_pdf_text_heuristic(path: Path) -> str:
    raw = path.read_bytes()[: MAX_TEXT_BYTES]
    text = raw.decode("latin-1", errors="ignore")
    parts = re.findall(r"\(([^()]*)\)\s*Tj", text)
    for block in re.findall(r"\[(.*?)\]\s*TJ", text, flags=re.DOTALL):
        parts.extend(re.findall(r"\(([^()]*)\)", block))
    decoded = [_decode_pdf_literal(item) for item in parts if item.strip()]
    return " ".join(decoded).strip()


def _safe_run(args: list[str], *, timeout_s: float) -> subprocess.CompletedProcess[str]:
    def _preexec_limits() -> None:
        if resource is None:
            return
        cpu_s = max(1, min(int(float(os.getenv("DOC_SEARCH_MAX_CPU_S", "20"))), 300))
        memory_mb = max(64, min(int(float(os.getenv("DOC_SEARCH_MAX_MEMORY_MB", "512"))), 4096))
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s))
        except Exception:
            pass
        try:
            bytes_limit = memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (bytes_limit, bytes_limit))
        except Exception:
            pass

    with _PROCESS_SEMAPHORE:
        return subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            preexec_fn=_preexec_limits if resource is not None else None,
        )


def _liteparse_available() -> bool:
    return shutil.which("lit") is not None


@contextmanager
def _liteparse_input_path(path: Path, *, file_type: str, original_filename: str | None) -> Path:
    expected_suffix = Path(str(original_filename or "")).suffix.lower()
    if not expected_suffix and file_type:
        expected_suffix = f".{file_type.lower()}"

    if expected_suffix and path.suffix.lower() != expected_suffix:
        with tempfile.TemporaryDirectory(prefix="liteparse_") as tmpdir:
            tmp_path = Path(tmpdir) / f"source{expected_suffix}"
            try:
                os.symlink(path, tmp_path)
            except Exception:
                shutil.copy2(path, tmp_path)
            yield tmp_path
        return

    yield path


def _parse_with_liteparse(path: Path, *, limits: SearchLimits) -> tuple[str, dict[str, Any]] | None:
    if not _liteparse_available():
        return None
    args = ["lit", "parse", str(path), "--format", "json", "--max-pages", str(limits.liteparse_max_pages), "-q"]
    if os.getenv("DOC_SEARCH_OCR_ENABLED", "1") in {"0", "false", "False"}:
        args.append("--no-ocr")
    else:
        ocr_language = os.getenv("DOC_SEARCH_OCR_LANGUAGE", "").strip()
        if ocr_language:
            args.extend(["--ocr-language", ocr_language])
        ocr_server_url = os.getenv("DOC_SEARCH_OCR_SERVER_URL", "").strip()
        if ocr_server_url:
            args.extend(["--ocr-server-url", ocr_server_url])
    dpi = os.getenv("DOC_SEARCH_LITEPARSE_DPI", "").strip()
    if dpi:
        args.extend(["--dpi", dpi])
    completed = _safe_run(args, timeout_s=limits.command_timeout_s)
    if completed.returncode != 0:
        logger.warning("liteparse failed for %s: %s", path, completed.stderr.strip()[:300])
        return None
    try:
        payload = json.loads(completed.stdout or "{}")
    except Exception:
        return None

    pages = payload.get("pages") if isinstance(payload, dict) else None
    page_texts: list[str] = []
    structured_pages: list[dict[str, Any]] = []
    if isinstance(pages, list):
        for page in pages:
            if not isinstance(page, dict):
                continue
            page_text = _collapse_space(str(page.get("text") or ""))
            if page_text:
                page_number = page.get("page") or page.get("pageNumber")
                structured_pages.append({"page": page_number, "text": page_text})
                page_texts.append(page_text)
    full_text = _collapse_space(payload.get("text") or "\n".join(page_texts))
    return full_text, {"pages": structured_pages, "liteparse": payload}


def parse_record(record: dict[str, Any], *, limits: SearchLimits | None = None) -> dict[str, Any]:
    limits = limits or load_search_limits()
    path = Path(record["cas_path"])
    file_type = str(record.get("file_type") or detect_file_type(path))
    started_at = perf_counter()

    if not path.exists() or path.stat().st_size > limits.max_file_bytes:
        return {
            "status": "skipped",
            "backend": "skipped",
            "text": "",
            "structured": None,
            "duration_ms": round((perf_counter() - started_at) * 1000, 2),
        }

    if file_type in TEXT_FILE_TYPES:
        text = _read_text_file(path)
        return {
            "status": "success",
            "backend": "direct_text",
            "text": text,
            "structured": {"pages": [{"page": 1, "text": _collapse_space(text)}]} if text else None,
            "duration_ms": round((perf_counter() - started_at) * 1000, 2),
        }
    if file_type == "docx":
        text = _extract_docx_text(path)
        return {
            "status": "success" if text else "empty",
            "backend": "office_xml",
            "text": text,
            "structured": {"pages": [{"page": 1, "text": _collapse_space(text)}]} if text else None,
            "duration_ms": round((perf_counter() - started_at) * 1000, 2),
        }
    if file_type == "pptx":
        text, structured = _extract_pptx_text(path)
        return {
            "status": "success" if text else "empty",
            "backend": "office_xml",
            "text": text,
            "structured": structured,
            "duration_ms": round((perf_counter() - started_at) * 1000, 2),
        }
    if file_type == "xlsx":
        text, structured = _extract_xlsx_text(path)
        return {
            "status": "success" if text else "empty",
            "backend": "office_xml",
            "text": text,
            "structured": structured,
            "duration_ms": round((perf_counter() - started_at) * 1000, 2),
        }
    if file_type == "pdf":
        text = _extract_pdf_text_heuristic(path)
        if text:
            return {
                "status": "success",
                "backend": "pdf_heuristic",
                "text": text,
                "structured": {"pages": [{"page": 1, "text": _collapse_space(text)}]},
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            }

    if file_type in PARSER_FIRST_FILE_TYPES or file_type in OFFICE_XML_FILE_TYPES:
        with _liteparse_input_path(path, file_type=file_type, original_filename=str(record.get("original_filename") or "")) as parse_path:
            parsed = _parse_with_liteparse(parse_path, limits=limits)
        if parsed:
            text, structured = parsed
            return {
                "status": "success" if text else "empty",
                "backend": "liteparse",
                "text": text,
                "structured": structured,
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            }
        if file_type in PARSER_FIRST_FILE_TYPES:
            return {
                "status": "missing_backend",
                "backend": "liteparse_missing",
                "text": "",
                "structured": None,
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            }

    return {
        "status": "unsupported",
        "backend": "unsupported",
        "text": "",
        "structured": None,
        "duration_ms": round((perf_counter() - started_at) * 1000, 2),
    }


def normalize_record(record: dict[str, Any], *, force: bool = False, limits: SearchLimits | None = None) -> dict[str, Any]:
    sha256 = record.get("sha256")
    limits = limits or load_search_limits()
    cached = load_parse_cache(sha256)
    if cached and not force:
        meta = dict(cached.get("meta") or {})
        return {
            "status": "cached",
            "backend": meta.get("backend", "parsed_sidecar"),
            "sidecar_dir": cached.get("sidecar_dir"),
            "text_bytes": len(str(cached.get("text") or "").encode("utf-8")),
            "parser_version": meta.get("parser_version"),
            "ocr_config_hash": meta.get("ocr_config_hash"),
        }

    parsed = parse_record(record, limits=limits)
    relative_path = str(record.get("relative_path") or record.get("original_filename") or "")
    routing = dict(record.get("routing") or {}) if isinstance(record.get("routing"), dict) else {}
    payload = write_parse_cache(
        sha256,
        text=str(parsed.get("text") or ""),
        structured=parsed.get("structured") if isinstance(parsed.get("structured"), dict) else None,
        meta={
            "backend": parsed.get("backend"),
            "status": parsed.get("status"),
            "source_sha256": sha256,
            "file_type": record.get("file_type"),
            "document_id": record.get("document_id"),
            "relative_path": relative_path,
            "original_filename": record.get("original_filename"),
            "duration_ms": parsed.get("duration_ms"),
            "routing": routing,
        },
    )
    return {
        "status": parsed.get("status"),
        "backend": parsed.get("backend"),
        "sidecar_dir": payload["sidecar_dir"] if payload else None,
        "text_bytes": len(str(parsed.get("text") or "").encode("utf-8")),
        "parser_version": cache_version_key(),
        "ocr_config_hash": cache_version_key(),
    }


def rebuild_parsed_sidecars(*, force: bool = False) -> dict[str, Any]:
    limits = load_search_limits()
    results: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for record in iter_live_documents():
        try:
            outcome = normalize_record(record, force=force, limits=limits)
            status = str(outcome.get("status") or "unknown")
        except Exception as exc:
            status = "error"
            outcome = {
                "status": "error",
                "backend": "error",
                "error_type": type(exc).__name__,
                "error": str(exc)[:200],
                "document_id": record.get("document_id"),
            }
        counts[status] = counts.get(status, 0) + 1
        if len(results) < 100:
            results.append(
                {
                    "document_id": record.get("document_id"),
                    "sha256": record.get("sha256"),
                    "status": status,
                    "backend": outcome.get("backend"),
                    "sidecar_dir": outcome.get("sidecar_dir"),
                }
            )
    return {"status": "ok", "force": force, "counts": counts, "results": results}


def extract_text_for_search(record: dict[str, Any], *, limits: SearchLimits) -> tuple[str, str, bool, dict[str, Any] | None, float]:
    started_at = perf_counter()
    cached = load_parse_cache(record.get("sha256"))
    if cached:
        meta = dict(cached.get("meta") or {})
        return (
            str(cached.get("text") or ""),
            str(meta.get("backend") or "parsed_sidecar"),
            True,
            cached.get("structured") if isinstance(cached.get("structured"), dict) else None,
            round((perf_counter() - started_at) * 1000, 2),
        )

    if str(record.get("status")) == "legacy":
        path = Path(record["cas_path"])
        if path.exists() and str(record.get("file_type") or detect_file_type(path)) in TEXT_FILE_TYPES:
            text = _read_text_file(path)
            structured = {"pages": [{"page": 1, "text": _collapse_space(text)}]} if text else None
            return (
                text,
                "legacy_text",
                False,
                structured,
                round((perf_counter() - started_at) * 1000, 2),
            )

    return "", "normalization_missing", False, None, round((perf_counter() - started_at) * 1000, 2)
