"""Document corpus primitives for RFC-007."""

from .storage import (
    DEFAULT_CORP_DOCS_ROOT,
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
from .route_schema import (
    SelectorValidationResult,
    merge_route_tool_args,
    normalize_route_card_contract,
    validate_selector_output,
    validate_tool_args,
)
from .routing import (
    build_route_selector_payload,
    build_routing_index,
    load_routing_index,
    routing_catalog_health,
    select_route,
    select_route_card,
)

__all__ = [
    "DEFAULT_CORP_DOCS_ROOT",
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
    "merge_route_tool_args",
    "normalize_route_card_contract",
    "build_route_selector_payload",
    "build_routing_index",
    "load_routing_index",
    "routing_catalog_health",
    "select_route",
    "select_route_card",
    "SelectorValidationResult",
    "sync_repo_inbox",
    "validate_selector_output",
    "validate_tool_args",
    "write_parse_cache",
]
