"""Document corpus primitives for RFC-007."""

from .storage import (
    DEFAULT_CORP_DOCS_ROOT,
    DEFAULT_LEGACY_DOCS_ROOT,
    DocumentPaths,
    RepoPaths,
    detect_file_type,
    ensure_document_layout,
    get_document_paths,
    get_repo_paths,
    ingest_document,
    ingest_document_with_report,
    iter_live_documents,
    load_live_document,
    sync_repo_inbox,
)
from .cache import (
    current_sidecar_dir,
    load_parse_cache,
    write_parse_cache,
    cache_version_key,
)
from .routing import build_routing_index, load_routing_index, select_route_card

__all__ = [
    "DEFAULT_CORP_DOCS_ROOT",
    "DEFAULT_LEGACY_DOCS_ROOT",
    "DocumentPaths",
    "RepoPaths",
    "cache_version_key",
    "current_sidecar_dir",
    "detect_file_type",
    "ensure_document_layout",
    "get_document_paths",
    "get_repo_paths",
    "ingest_document",
    "ingest_document_with_report",
    "iter_live_documents",
    "load_live_document",
    "load_parse_cache",
    "build_routing_index",
    "load_routing_index",
    "select_route_card",
    "sync_repo_inbox",
    "write_parse_cache",
]
