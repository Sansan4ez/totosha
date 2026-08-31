"""Unified routing catalog for corp_table, corp_script, and doc_domain routes."""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .argument_catalogs import (
    canonical_mounting_type_names,
    canonical_sphere_names,
    curated_category_names_for_sphere,
)
from .cache import load_parse_cache
from .route_schema import (
    ROUTE_CONTRACT_FIELDS,
    RouteCardContractError,
    default_argument_schema,
    normalize_route_card_contract,
)
from .routing_policy import (
    CATALOG_APPLICATION_RECOMMENDATION_KEYWORDS as APPLICATION_RECOMMENDATION_KEYWORDS,
    CATALOG_COMPANY_FACT_KEYWORDS as COMPANY_FACT_KEYWORDS,
    CATALOG_PORTFOLIO_LOOKUP_KEYWORDS as PORTFOLIO_LOOKUP_KEYWORDS,
)
from .series_catalog import canonical_series_names
from .storage import ensure_document_layout, get_document_paths, iter_live_documents

_logger = logging.getLogger(__name__)

WORD_RE = re.compile(r"[\wА-Яа-яЁё]+", re.UNICODE)
DOCUMENT_REQUEST_KEYWORDS = (
    "паспорт",
    "pdf",
    "документ",
    "wiki",
    "вики",
    "фрагмент",
    "цитат",
)
DOCUMENT_TYPE_ENUM = ("passport", "certificate", "manual", "ies")
PASSPORT_TERMS = (
    "паспорт",
    "паспорта",
)
CERTIFICATE_TERMS = (
    "сертификат",
    "сертификаты",
    "сертификац",
    "декларац",
)
MANUAL_TERMS = (
    "инструк",
    "руководств",
    "manual",
    "мануал",
)
IES_TERMS = (
    "ies",
    "ies-файл",
    "ies файл",
)
DOCUMENT_SUBTYPE_ROUTE_IDS = {
    "passport": "corp_db.passport_by_lamp_name",
    "certificate": "corp_db.certificate_by_lamp_name",
    "manual": "corp_db.manual_by_lamp_name",
    "ies": "corp_db.ies_by_lamp_name",
}
DOCUMENT_TYPE_TERMS = {
    "passport": PASSPORT_TERMS,
    "certificate": CERTIFICATE_TERMS,
    "manual": MANUAL_TERMS,
    "ies": IES_TERMS,
}
DOCUMENTS_FAMILY_ROUTE_IDS = {
    "corp_db.documents_by_lamp_name",
    *DOCUMENT_SUBTYPE_ROUTE_IDS.values(),
}
CERTIFICATE_DOCUMENT_CONTEXT_KEYWORDS = (
    "ссылка",
    "прямая ссылка",
    "прямую ссылку",
    "pdf",
    "файл",
    "скачать",
    "скачай",
    "фрагмент",
    "цитат",
    "найди в",
    "в документ",
    "из документ",
)
DOCUMENT_LINK_CONTEXT_PATTERNS = (
    "ссылка на сертификат",
    "ссылка на паспорт",
    "ссылка на pdf",
    "ссылка на документ",
    "прямая ссылка на сертификат",
    "прямая ссылка на паспорт",
    "прямая ссылка на pdf",
    "прямая ссылка на документ",
)
DOCUMENT_IN_TEXT_PATTERNS = (
    "в документе",
    "из документа",
    "по документу",
    "в pdf",
    "из pdf",
    "цитату из",
    "фрагмент из",
)
CODE_SYSTEM_TERMS = {
    "etm": ("etm", "етм"),
    "oracl": ("oracl", "оракл"),
    "sku": ("sku",),
    "article": ("артикул", "артикулы"),
    "catalog_identifier": ("код номенклатуры", "каталожный код", "каталожный номер"),
}
CODE_LOOKUP_DIRECTION_ENUM = ("by_name", "by_code")
CODE_SYSTEM_ENUM = ("etm", "oracl", "sku", "article", "catalog_identifier", "mixed")
ORCHESTRATION_KEYWORDS = (
    "подбери",
    "рекоменд",
    "портфолио",
    "пример проекта",
    "пример объекта",
    "покажи проекты",
    "какие проекты",
    "какие светильники подходят",
    "подходят для",
    "подходит для",
)
CATALOG_LOOKUP_KEYWORDS = (
    "модель",
    "серия",
    "серии",
    "серий",
    "линейка",
    "линейки",
    "артикул",
    "код",
    "sku",
    "etm",
    "етм",
    "oracl",
    "оракл",
    "категория",
    "категории",
    "карточка",
    "характеристики",
    "совместимость",
    "крепление",
    "крепления",
    "монтаж",
    "тип крепления",
)
BROAD_SERIES_QUERY_CUES = (
    "какие серии",
    "какие у вас есть серии",
    "какие есть серии",
    "какие серии светильников",
    "какие линейки",
    "какие есть линейки",
    "все серии",
    "всех серий",
    "описание всех серий",
    "описание серий",
    "серии светильников",
    "линейки светильников",
    "перечисли серии",
    "список серий",
)
BROAD_SERIES_QUERY_EXCLUSIONS = (
    "чем отличается",
    "отличия между",
    "сравни",
    "сравнение",
    "на каких сериях",
    "в каких сериях",
    "какие крепления",
    "совместим",
    "подходит крепление",
    "закал",
    "стекл",
)
SERIES_COMPARISON_QUERY_CUES = (
    "чем отличается",
    "чем отличаются",
    "отличия между",
    "разница между",
    "сравни серии",
    "сравнение серий",
)
SERIES_KNOWLEDGE_SCOPE_CUES = (
    "на каких сериях",
    "в каких сериях",
    "какие серии",
)
SERIES_KNOWLEDGE_FACT_CUES = (
    "закал",
    "стекл",
    "материал",
    "рассеивател",
    "особенност",
)
SPHERE_CATEGORY_QUERY_CUES = (
    "какие категории подходят",
    "какие категории есть",
    "категории для",
    "категории по",
    "категории в сфере",
    "категории по сфере",
    "категории для сферы",
    "какие категории у",
)
MOUNTING_QUERY_CUES = (
    "креплен",
    "крепления",
    "монтаж",
    "тип крепления",
    "типы креплений",
    "совместим",
    "совместимость",
)
ROUTE_MATCH_STOPWORDS = {
    "и",
    "в",
    "на",
    "по",
    "для",
    "про",
    "дай",
    "найди",
    "покажи",
    "какие",
    "какой",
    "какая",
    "какое",
    "нужен",
    "нужна",
    "нужно",
    "документ",
    "фрагмент",
    "ссылка",
}
ROUTING_SCHEMA_VERSION = 1
ROUTING_CATALOG_ID = "totosha.unified-routing-catalog"
ROUTING_CATALOG_FILENAME = "catalog.v1.json"
LEGACY_ROUTING_INDEX_FILENAME = "index.json"
# Retain the legacy guard for persisted runtime catalogs without publishing the old generic route.
LEGACY_GENERIC_DOC_LOOKUP_ROUTE_ID = "doc_search." "document_lookup"
SELECTOR_ROUTE_LIMIT = 60
PRODUCTION_ENV_VALUES = {"prod", "production"}
TRUTH_SOURCE_OWNERS = {"repo_static", "corp_db", "document_ingestion", "runtime_merged"}
KNOWN_CORP_DB_DOMAINS = (
    "kb_chunk",
    "lamp",
    "sku",
    "category",
    "mounting_type",
    "category_mounting",
    "sphere",
    "portfolio",
)
ROUTE_OWNER_PRIORITY = {
    "bootstrap": 0,
    "repo_static": 10,
    "corp_db": 20,
    "document_ingestion": 30,
    "runtime_merged": 40,
}
def static_route_catalog_dir() -> Path:
    """RFC-028 declarative route catalog directory (core/routes/), shipped with the code.

    Distinct from _repo_route_dir(), which is an optional runtime overlay of
    generated/published manifests outside the core image.
    """
    return Path(__file__).resolve().parents[1] / "routes"


def load_route_family_cards() -> dict[str, dict[str, str]]:
    """Load routes/families.yaml (family id -> {title, summary})."""
    families_path = static_route_catalog_dir() / "families.yaml"
    if not families_path.exists():
        return {}
    payload = yaml.safe_load(families_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


# RFC-028: families.yaml is the single source of truth for family title/summary metadata,
# same as core/routes/<family>/<leaf>.yaml is for routes (see load_static_route_cards). It ships
# in the image (core/Dockerfile: COPY routes/ ./routes/), so a missing/empty file is a packaging
# bug, not a runtime condition to silently degrade -- fail fast at import time instead of falling
# back to a second, driftable copy of this data in Python.
ROUTE_FAMILY_CARDS = load_route_family_cards()
if not ROUTE_FAMILY_CARDS:
    raise RuntimeError(f"route family catalog is empty or missing at {static_route_catalog_dir() / 'families.yaml'}")
ROUTE_FAMILY_ORDER = {
    family_id: index
    for index, family_id in enumerate(ROUTE_FAMILY_CARDS.keys(), start=1)
}
ROUTE_BUSINESS_METADATA = {
    "corp_kb.company_common": {"family_id": "company_info", "leaf_route_id": "company_general", "route_stage": "stage1_general"},
    "corp_kb.series_description": {"family_id": "company_info", "leaf_route_id": "series_description", "route_stage": "stage2_specialized"},
    "corp_kb.luxnet": {"family_id": "company_info", "leaf_route_id": "luxnet_overview", "route_stage": "stage1_general"},
    "corp_kb.lighting_norms": {"family_id": "company_info", "leaf_route_id": "lighting_norms_reference", "route_stage": "stage1_general"},
    "corp_db.catalog_lookup": {"family_id": "catalog", "leaf_route_id": "catalog_entity_lookup", "route_stage": "stage1_general"},
    "corp_db.category_lamps": {"family_id": "catalog", "leaf_route_id": "category_lamps", "route_stage": "stage1_general"},
    "corp_db.showcase_lamps_by_category": {"family_id": "catalog", "leaf_route_id": "showcase_lamps_by_category", "route_stage": "stage3_optimized"},
    "corp_db.documents_by_lamp_name": {"family_id": "documents", "leaf_route_id": "documents_by_lamp_name", "route_stage": "stage3_optimized"},
    "corp_db.passport_by_lamp_name": {"family_id": "documents", "leaf_route_id": "passport_by_lamp_name", "route_stage": "stage3_optimized"},
    "corp_db.certificate_by_lamp_name": {"family_id": "documents", "leaf_route_id": "certificate_by_lamp_name", "route_stage": "stage3_optimized"},
    "corp_db.manual_by_lamp_name": {"family_id": "documents", "leaf_route_id": "manual_by_lamp_name", "route_stage": "stage3_optimized"},
    "corp_db.ies_by_lamp_name": {"family_id": "documents", "leaf_route_id": "ies_by_lamp_name", "route_stage": "stage3_optimized"},
    "corp_db.sku_lookup": {"family_id": "codes_and_sku", "leaf_route_id": "sku_by_code", "route_stage": "stage3_optimized"},
    "corp_db.sku_codes_lookup": {"family_id": "codes_and_sku", "leaf_route_id": "sku_codes_lookup", "route_stage": "stage3_optimized"},
    "corp_db.sphere_curated_categories": {"family_id": "sphere_category_mapping", "leaf_route_id": "curated_categories_by_sphere", "route_stage": "stage1_general"},
    "corp_db.sphere_categories": {"family_id": "sphere_category_mapping", "leaf_route_id": "imported_categories_by_sphere", "route_stage": "stage1_general"},
    "corp_db.lamp_filters": {"family_id": "catalog", "leaf_route_id": "catalog_filters_by_category", "route_stage": "stage1_general"},
    "corp_db.category_mountings": {"family_id": "mountings", "leaf_route_id": "mountings_by_category", "route_stage": "stage1_general"},
    "corp_db.lamp_mounting_compatibility": {"family_id": "mountings", "leaf_route_id": "mounting_compatibility_by_series", "route_stage": "stage2_specialized"},
    "corp_db.portfolio_lookup": {"family_id": "portfolio", "leaf_route_id": "portfolio_named_object_lookup", "route_stage": "stage1_general"},
    "corp_db.portfolio_by_sphere": {"family_id": "portfolio", "leaf_route_id": "portfolio_projects_by_sphere", "route_stage": "stage1_general"},
    "corp_db.portfolio_examples_by_lamp": {"family_id": "portfolio", "leaf_route_id": "portfolio_examples_by_lamp", "route_stage": "stage2_specialized"},
    "corp_db.application_recommendation": {"family_id": "catalog", "leaf_route_id": "application_recommendation", "route_stage": "stage1_general"},
}
SERIES_AWARE_ROUTE_IDS = {
    "corp_kb.series_description",
    "corp_db.lamp_filters",
    "corp_db.category_mountings",
    "corp_db.lamp_mounting_compatibility",
}
SPHERE_AWARE_ROUTE_IDS = {
    "corp_db.portfolio_by_sphere",
    "corp_db.sphere_curated_categories",
    "corp_db.sphere_categories",
}
MOUNTING_TYPE_AWARE_ROUTE_IDS = {
    "corp_db.lamp_filters",
    "corp_db.category_mountings",
    "corp_db.lamp_mounting_compatibility",
}
CATEGORY_AWARE_ROUTE_IDS = {
    "corp_db.category_lamps",
    "corp_db.showcase_lamps_by_category",
    "corp_db.lamp_filters",
    "corp_db.category_mountings",
    "corp_db.lamp_mounting_compatibility",
}
ROUTE_ARGUMENT_PROPERTY_ALLOWLISTS = {
    "corp_kb.company_common": {
        "query",
        "topic_facets",
        "limit",
    },
    "corp_kb.series_description": {
        "query",
        "series",
        "topic_facets",
        "limit",
    },
    "corp_kb.luxnet": {
        "query",
        "limit",
    },
    "corp_kb.lighting_norms": {
        "query",
        "limit",
    },
    "corp_db.catalog_lookup": {
        "query",
        "name",
        "category",
        "mounting_type",
        "limit",
        "offset",
    },
    "corp_db.sku_lookup": {
        "lookup_direction",
        "code_system",
        "name",
        "query",
        "etm",
        "oracl",
        "limit",
        "offset",
    },
    "corp_db.sku_codes_lookup": {
        "lookup_direction",
        "code_system",
        "name",
        "limit",
        "offset",
    },
    "corp_db.category_lamps": {
        "category",
        "query",
        "limit",
        "offset",
    },
    "corp_db.showcase_lamps_by_category": {
        "category",
        "query",
        "limit",
        "offset",
    },
    "corp_db.documents_by_lamp_name": {
        "document_type",
        "names",
        "query",
        "limit",
        "offset",
    },
    "corp_db.passport_by_lamp_name": {
        "names",
        "query",
        "limit",
        "offset",
    },
    "corp_db.certificate_by_lamp_name": {
        "names",
        "query",
        "limit",
        "offset",
    },
    "corp_db.manual_by_lamp_name": {
        "names",
        "query",
        "limit",
        "offset",
    },
    "corp_db.ies_by_lamp_name": {
        "names",
        "query",
        "limit",
        "offset",
    },
    "corp_db.portfolio_lookup": {
        "query",
        "limit",
        "offset",
    },
    "corp_db.portfolio_by_sphere": {
        "sphere",
        "query",
        "limit",
        "offset",
    },
    "corp_db.application_recommendation": {
        "query",
        "application_key",
        "context_profile",
        "limit_categories",
        "limit_lamps",
        "limit_portfolio",
    },
    "corp_db.sphere_curated_categories": {
        "sphere",
        "query",
    },
    "corp_db.sphere_categories": {
        "sphere",
        "query",
    },
    "corp_db.lamp_filters": {
        "category",
        "series",
        "mounting_type",
        "beam_pattern",
        "climate_execution",
        "electrical_protection_class",
        "explosion_protection_marking",
        "supply_voltage_raw",
        "dimensions_raw",
        "power_factor_operator",
        "ip",
        "voltage_kind",
        "explosion_protected",
        "power_w_min",
        "power_w_max",
        "flux_lm_min",
        "flux_lm_max",
        "cct_k_min",
        "cct_k_max",
        "weight_kg_min",
        "weight_kg_max",
        "cri_ra_min",
        "cri_ra_max",
        "power_factor_min_min",
        "power_factor_min_max",
        "temp_c_min",
        "temp_c_max",
        "voltage_nominal_v_min",
        "voltage_nominal_v_max",
        "voltage_min_v_min",
        "voltage_min_v_max",
        "voltage_max_v_min",
        "voltage_max_v_max",
        "voltage_tol_minus_pct_min",
        "voltage_tol_minus_pct_max",
        "voltage_tol_plus_pct_min",
        "voltage_tol_plus_pct_max",
        "length_mm_min",
        "length_mm_max",
        "width_mm_min",
        "width_mm_max",
        "height_mm_min",
        "height_mm_max",
        "warranty_years_min",
        "warranty_years_max",
        "limit",
        "offset",
    },
    "corp_db.category_mountings": {
        "category",
        "series",
        "mounting_type",
        "query",
    },
    "corp_db.lamp_mounting_compatibility": {
        "category",
        "series",
        "mounting_type",
        "query",
    },
}


class RouteCatalogUnavailable(RuntimeError):
    """No valid merged route catalog is available for production routing."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _truth_source_owner(origin: str, payload: dict[str, Any] | None = None) -> str:
    payload = payload or {}
    declared = str(
        payload.get("source_owner")
        or payload.get("route_owner")
        or payload.get("owner")
        or ""
    ).strip()
    if declared:
        return declared
    if origin in {"runtime_live_documents", "document_ingestion"}:
        return "document_ingestion"
    if origin in {"corp_db_generated", "corp_db"}:
        return "corp_db"
    if origin in {"bootstrap"}:
        return "bootstrap"
    if origin in {"runtime_merged"}:
        return "runtime_merged"
    return "repo_static"


def _default_family_metadata(route_id: str, route_kind: str) -> dict[str, str]:
    if route_kind == "doc_domain" or route_id.startswith("doc_search."):
        return {
            "family_id": "documents",
            "leaf_route_id": "document_domain_lookup",
            "route_stage": "stage1_general",
        }
    if route_id.startswith("corp_kb."):
        return {
            "family_id": "company_info",
            "leaf_route_id": "company_general",
            "route_stage": "stage1_general",
        }
    return {
        "family_id": "other",
        "leaf_route_id": route_id or "other",
        "route_stage": "stage1_general",
    }


def _family_metadata_for_route(route_id: str, route_kind: str) -> dict[str, str]:
    metadata = dict(_default_family_metadata(route_id, route_kind))
    metadata.update(ROUTE_BUSINESS_METADATA.get(route_id, {}))
    family = ROUTE_FAMILY_CARDS.get(metadata["family_id"], ROUTE_FAMILY_CARDS["other"])
    metadata["family_title"] = str(family.get("title") or metadata["family_id"])
    metadata["family_summary"] = str(family.get("summary") or "")
    return metadata


def _catalog_required_for_runtime() -> bool:
    explicit = os.getenv("ROUTING_CATALOG_REQUIRED", "").strip().lower()
    if explicit in {"1", "true", "yes", "on"}:
        return True
    if explicit in {"0", "false", "no", "off"}:
        return False
    for key in ("APP_ENV", "ENVIRONMENT", "DEPLOYMENT_ENVIRONMENT", "OTEL_DEPLOYMENT_ENVIRONMENT"):
        if os.getenv(key, "").strip().lower() in PRODUCTION_ENV_VALUES:
            return True
    return False


def _normalize(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def _terms(text: Any) -> list[str]:
    return [token.lower() for token in WORD_RE.findall(str(text or "")) if token.strip()]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = _normalize(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(str(item).strip())
    return result


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return _dedupe([str(item).strip() for item in value if str(item).strip()])


def _runtime_route_dir() -> Path:
    paths = ensure_document_layout(get_document_paths())
    route_dir = paths.manifests / "routes"
    route_dir.mkdir(parents=True, exist_ok=True)
    return route_dir


def _repo_root() -> Path:
    default_root = Path(__file__).resolve().parents[2]
    return Path(os.getenv("DOC_REPO_ROOT", str(default_root)))


def _repo_route_dir() -> Path:
    return _repo_root() / "doc-corpus" / "manifests" / "routes"


def _route_schema_file_path(card_path: Path, payload: dict[str, Any]) -> Path:
    schema_ref = str(payload.get("schema_ref") or "").strip()
    if schema_ref:
        return card_path.parent / schema_ref
    return card_path.with_suffix(".schema.json")


@functools.lru_cache(maxsize=1)
def _load_static_route_cards_from_disk() -> tuple[dict[str, Any], ...]:
    routes_dir = static_route_catalog_dir()
    routes: list[dict[str, Any]] = []
    for path in sorted(routes_dir.glob("*/*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and payload.get("route_id"):
            # RFC-029 workstream 4: the argument schema is a machine-executed contract and
            # lives in a sibling .schema.json file, never inline YAML.
            if "argument_schema" in payload:
                _logger.error(f"route card must not embed argument_schema (use .schema.json), skipped: {path}")
                continue
            schema_path = _route_schema_file_path(path, payload)
            if schema_path.is_file():
                payload["argument_schema"] = json.loads(schema_path.read_text(encoding="utf-8"))
                payload["argument_schema_origin"] = "schema_file"
            routes.append(payload)
        elif isinstance(payload, dict):
            _logger.error(f"route catalog card missing route_id, skipped: {path}")
    return tuple(routes)


def load_static_route_cards() -> list[dict[str, Any]]:
    """Load the RFC-028 declarative route catalog (core/routes/<family>/<leaf>.yaml).

    Returns route dicts in the same raw shape bootstrap_route_cards() used to return as
    Python literals: family/stage metadata is not included here (it is layered on by
    _normalize_route_card via ROUTE_BUSINESS_METADATA), only the route's own declared fields.
    File order is alphabetical by (family directory, filename) for determinism.

    The disk read + YAML parse of all 23 route cards is cached process-wide (the catalog is
    immutable within a running image); callers get a shallow per-route-dict copy so in-place
    top-level key assignment (see _apply_runtime_argument_overrides) never mutates the cache.
    """
    return [dict(route) for route in _load_static_route_cards_from_disk()]


def _runtime_catalog_path() -> Path:
    return _runtime_route_dir() / ROUTING_CATALOG_FILENAME


def _legacy_runtime_index_path() -> Path:
    return _runtime_route_dir() / LEGACY_ROUTING_INDEX_FILENAME


def _default_retry_policy(route_kind: str, authority: str) -> dict[str, Any]:
    if route_kind == "corp_table" and authority == "primary":
        return {"max_primary_attempts": 1, "max_local_retries": 1}
    return {"max_primary_attempts": 1, "max_local_retries": 0}


def _source_from_executor(executor: str) -> str:
    return "doc_search" if executor == "doc_search" else "corp_db"


def _canonical_series_property_schema() -> dict[str, Any]:
    return {"type": "string", "enum": canonical_series_names()}


def _canonical_sphere_property_schema() -> dict[str, Any]:
    return {"type": "string", "enum": canonical_sphere_names()}


def _canonical_mounting_type_property_schema() -> dict[str, Any]:
    return {"type": "string", "enum": canonical_mounting_type_names()}


def _scoped_category_property_schema(sphere_name: str) -> dict[str, Any]:
    values = curated_category_names_for_sphere(sphere_name)
    if values:
        return {"type": "string", "enum": values}
    return {"type": "string"}


def _retain_argument_properties(route_id: str, properties: dict[str, Any]) -> dict[str, Any]:
    allowed = ROUTE_ARGUMENT_PROPERTY_ALLOWLISTS.get(route_id)
    if not allowed:
        return properties
    return {
        key: value
        for key, value in properties.items()
        if key in allowed
    }


def _apply_runtime_argument_overrides(route: dict[str, Any], *, sphere_context: dict[str, Any] | None = None) -> None:
    route_id = str(route.get("route_id") or "").strip()
    executor = str(route.get("executor") or route.get("tool_name") or "").strip()
    executor_args_template = dict(route.get("executor_args_template") or {})
    locked_args = dict(route.get("locked_args") or executor_args_template)
    declared_schema = route.get("argument_schema") if isinstance(route.get("argument_schema"), dict) else None
    if declared_schema and str(route.get("argument_schema_origin") or "") == "schema_file":
        # RFC-029 workstream 4: the .schema.json file is the source of truth for the
        # selector-visible argument contract; only live enum values are refreshed below.
        route["argument_schema"] = json.loads(json.dumps(declared_schema))
    else:
        route["argument_schema"] = default_argument_schema(
            executor=executor,
            executor_args_template=executor_args_template,
            locked_args=locked_args,
            selector_visible_only=True,
        )
        route["argument_schema"]["properties"] = _retain_argument_properties(
            route_id,
            dict(route["argument_schema"].get("properties") or {}),
        )
    if executor == "corp_db_search":
        from documents.corp_db_contract import allowed_fields_for_kind

        kind = str(executor_args_template.get("kind") or locked_args.get("kind") or "").strip()
        consumed_fields = allowed_fields_for_kind(
            kind,
            fixed_args={**executor_args_template, **locked_args},
        )
        route["argument_schema"]["properties"] = {
            key: value
            for key, value in route["argument_schema"]["properties"].items()
            if key in consumed_fields
        }
    route["execution_argument_schema"] = default_argument_schema(
        executor=executor,
        executor_args_template=executor_args_template,
        locked_args=locked_args,
        selector_visible_only=False,
    )
    if route_id in SPHERE_AWARE_ROUTE_IDS and "sphere" in route["argument_schema"]["properties"]:
        route["argument_schema"]["properties"]["sphere"] = _canonical_sphere_property_schema()
    if route_id in MOUNTING_TYPE_AWARE_ROUTE_IDS and "mounting_type" in route["argument_schema"]["properties"]:
        route["argument_schema"]["properties"]["mounting_type"] = _canonical_mounting_type_property_schema()
    if route_id in SERIES_AWARE_ROUTE_IDS:
        route["argument_schema"]["properties"]["series"] = _canonical_series_property_schema()
    scoped_sphere_name = str((sphere_context or {}).get("sphere_name") or "").strip()
    if scoped_sphere_name and route_id in CATEGORY_AWARE_ROUTE_IDS and "category" in route["argument_schema"]["properties"]:
        route["argument_schema"]["properties"]["category"] = _scoped_category_property_schema(scoped_sphere_name)
    if executor == "corp_db_search":
        from documents.corp_db_contract import apply_requirements

        apply_requirements(
            route["argument_schema"],
            kind=kind,
            fixed_args={**executor_args_template, **locked_args},
        )
    if route_id == "corp_db.category_mountings":
        route["argument_schema"]["properties"].pop("mounting_type", None)
        route["argument_schema"]["required"] = []
        route["argument_schema"]["anyOf"] = [
            {"required": ["category"]},
            {"required": ["series"]},
        ]
    elif route_id == "corp_db.lamp_mounting_compatibility":
        route["argument_schema"]["required"] = ["mounting_type"]
        route["argument_schema"]["anyOf"] = [
            {"required": ["category"]},
            {"required": ["series"]},
        ]
    hints = dict(route.get("argument_hints") or {})
    if route_id in SPHERE_AWARE_ROUTE_IDS and "sphere" in route["argument_schema"]["properties"]:
        hints["sphere"] = "Choose one canonical application sphere when the user clearly asks by segment or environment."
    if route_id in MOUNTING_TYPE_AWARE_ROUTE_IDS and "mounting_type" in route["argument_schema"]["properties"]:
        hints["mounting_type"] = "Choose one canonical mounting type when the user explicitly names a mounting option."
    if route_id in SERIES_AWARE_ROUTE_IDS:
        hints.setdefault("series", "Choose one canonical business series when the user asks at model-family level.")
    if scoped_sphere_name and route_id in CATEGORY_AWARE_ROUTE_IDS and "category" in route["argument_schema"]["properties"]:
        hints["category"] = f"Choose one curated category from the active sphere context: {scoped_sphere_name}."
    route["argument_hints"] = hints


def _infer_route_kind(route: dict[str, Any]) -> str:
    route_kind = str(route.get("route_kind") or "").strip()
    if route_kind in {"corp_table", "corp_script", "doc_domain"}:
        return route_kind
    executor = str(route.get("executor") or route.get("tool_name") or "").strip()
    args = route.get("executor_args_template")
    if not isinstance(args, dict):
        args = route.get("tool_args") if isinstance(route.get("tool_args"), dict) else {}
    if executor == "doc_search":
        return "doc_domain"
    kind = str(args.get("kind") or "")
    if kind in {"application_recommendation", "portfolio_by_sphere"}:
        return "corp_script"
    return "corp_table"


def _normalize_route_card(
    route: dict[str, Any],
    *,
    origin: str,
    source_owner: str | None = None,
    errors: list[str] | None = None,
) -> dict[str, Any] | None:
    route_id = str(route.get("route_id") or "").strip()
    if not route_id:
        return None
    if route_id == LEGACY_GENERIC_DOC_LOOKUP_ROUTE_ID:
        return None

    executor = str(route.get("executor") or route.get("tool_name") or "").strip()
    if not executor:
        return None

    executor_args = route.get("executor_args_template")
    if not isinstance(executor_args, dict):
        executor_args = route.get("tool_args") if isinstance(route.get("tool_args"), dict) else {}
    executor_args = dict(executor_args)

    route_kind = _infer_route_kind(route)
    route_family = str(route.get("route_family") or executor_args.get("knowledge_route_id") or route_id).strip()
    authority = str(route.get("authority") or "").strip() or (
        "primary" if route_kind != "doc_domain" or route_id.startswith("doc_search.doc_") else "secondary"
    )
    family_metadata = _family_metadata_for_route(route_id, route_kind)
    for field_name in ("family_id", "family_title", "family_summary", "leaf_route_id", "route_stage"):
        if str(route.get(field_name) or "").strip():
            family_metadata[field_name] = str(route.get(field_name) or "").strip()

    normalized = {
        "route_id": route_id,
        "route_family": route_family,
        "family_id": family_metadata["family_id"],
        "family_title": family_metadata["family_title"],
        "family_summary": family_metadata["family_summary"],
        "leaf_route_id": family_metadata["leaf_route_id"],
        "route_stage": family_metadata["route_stage"],
        "route_kind": route_kind,
        "authority": authority,
        "title": str(route.get("title") or route_id).strip(),
        "summary": str(route.get("summary") or "").strip(),
        "when_to_use": str(route.get("when_to_use") or "").strip(),
        "topics": [str(item).strip() for item in route.get("topics", []) if str(item).strip()],
        "keywords": _dedupe([str(item) for item in route.get("keywords", []) if str(item).strip()]),
        "patterns": _dedupe([str(item) for item in route.get("patterns", []) if str(item).strip()]),
        "generated_keywords": _dedupe([str(item) for item in route.get("generated_keywords", []) if str(item).strip()]),
        "preconditions": [str(item).strip() for item in route.get("preconditions", []) if str(item).strip()],
        "retry_policy": dict(route.get("retry_policy") or _default_retry_policy(route_kind, authority)),
        "executor": executor,
        "executor_args_template": executor_args,
        "observability_labels": dict(route.get("observability_labels") or {}),
        "document_id": str(route.get("document_id") or "").strip(),
        "source": str(route.get("source") or _source_from_executor(executor)).strip(),
        "tool_name": executor,
        "tool_args": executor_args,
        "catalog_origin": origin,
        "route_owner": source_owner or _truth_source_owner(origin),
    }
    normalized["observability_labels"].setdefault("route_family", route_family)
    normalized["observability_labels"].setdefault("family_id", family_metadata["family_id"])
    normalized["observability_labels"].setdefault("leaf_route_id", family_metadata["leaf_route_id"])
    normalized["observability_labels"].setdefault("route_stage", family_metadata["route_stage"])
    normalized["observability_labels"].setdefault("route_kind", route_kind)
    normalized["observability_labels"].setdefault("authority", authority)
    normalized["observability_labels"].setdefault("source", normalized["source"])
    for field_name in ROUTE_CONTRACT_FIELDS:
        if field_name in route:
            normalized[field_name] = route[field_name]
    for field_name in ("hidden", "selector_visible", "argument_schema_origin"):
        if field_name in route:
            normalized[field_name] = route[field_name]
    for override_key in (
        "overrides_route_ids",
        "override_route_ids",
        "allow_override_route_ids",
        "overrides_route_id",
        "override_route_id",
        "allow_override_route_id",
        "allow_route_id_override",
        "catalog_override",
    ):
        if override_key in route:
            normalized[override_key] = route[override_key]
    try:
        return normalize_route_card_contract(normalized)
    except RouteCardContractError as exc:
        if errors is not None:
            errors.append(f"{route_id}: {exc}")
        return None


def bootstrap_route_cards() -> list[dict[str, Any]]:
    routes = load_static_route_cards()
    for route in routes:
        _apply_runtime_argument_overrides(route)
    return routes


def default_corp_db_route_cards() -> list[dict[str, Any]]:
    return [
        {
            "route_id": route["route_id"],
            "route_family": route["route_family"],
            "family_id": str(route.get("family_id") or ""),
            "family_title": str(route.get("family_title") or ""),
            "family_summary": str(route.get("family_summary") or ""),
            "leaf_route_id": str(route.get("leaf_route_id") or route["route_id"]),
            "route_stage": str(route.get("route_stage") or ""),
            "route_kind": route["route_kind"],
            "authority": route["authority"],
            "source": route["source"],
            "title": route["title"],
            "summary": route["summary"],
            "topics": list(route["topics"]),
            "keywords": list(route["keywords"]),
            "patterns": list(route["patterns"]),
            "tool_name": route["tool_name"],
            "tool_args": dict(route["tool_args"]),
            "executor": route["executor"],
            "executor_args_template": dict(route["executor_args_template"]),
            "argument_schema": dict(route["argument_schema"]),
            "locked_args": dict(route["locked_args"]),
            "argument_hints": dict(route["argument_hints"]),
            "evidence_policy": dict(route["evidence_policy"]),
            "fallback_route_ids": list(route["fallback_route_ids"]),
            "cross_family_fallback_route_ids": list(route.get("cross_family_fallback_route_ids") or []),
            "fallback_policy": dict(route.get("fallback_policy") or {}),
            "document_selectors": list(route["document_selectors"]),
            "route_owner": str(route.get("route_owner") or ""),
            "table_scopes": list(route["table_scopes"]),
            "negative_keywords": list(route["negative_keywords"]),
            "observability_labels": dict(route["observability_labels"]),
        }
        for route in (
            normalized
            for normalized in (
                _normalize_route_card(route, origin="bootstrap") for route in bootstrap_route_cards()
            )
            if normalized is not None
        )
    ]


def _document_routing_specs(routing_metadata: dict[str, Any]) -> list[dict[str, Any]]:
    base = {
        key: value
        for key, value in routing_metadata.items()
        if key not in {"routes", "route_cards", "thematic_routes"}
    }
    raw_routes = (
        routing_metadata.get("routes")
        or routing_metadata.get("route_cards")
        or routing_metadata.get("thematic_routes")
    )
    if isinstance(raw_routes, list) and raw_routes:
        specs: list[dict[str, Any]] = []
        for item in raw_routes:
            if isinstance(item, dict):
                merged = dict(base)
                merged.update(item)
                specs.append(merged)
        return specs or [base]
    return [base]


def build_document_route_cards() -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for record in iter_live_documents():
        aliases = list(record.get("aliases") or [])
        primary_alias = aliases[0] if aliases else {}
        metadata = primary_alias.get("metadata") if isinstance(primary_alias.get("metadata"), dict) else {}
        routing_metadata = dict(record.get("routing") or {}) if isinstance(record.get("routing"), dict) else {}
        cached = load_parse_cache(record.get("sha256"))
        text = str(cached.get("text") or "") if cached else ""
        document_id = str(record.get("document_id") or "").strip()
        relative_path = str(record.get("relative_path") or record.get("original_filename") or "").strip()
        original_filename = str(record.get("original_filename") or "").strip()
        base_preferred_document_ids = _dedupe([document_id, relative_path, original_filename])
        route_specs = _document_routing_specs(routing_metadata)
        for index, route_spec in enumerate(route_specs, start=1):
            summary = str(route_spec.get("summary") or metadata.get("summary") or text[:220]).strip()
            title = str(
                route_spec.get("title")
                or metadata.get("title")
                or original_filename
                or relative_path
                or document_id
            )
            tags = _string_list(route_spec.get("tags") or metadata.get("tags"))
            topics = _string_list(route_spec.get("topics")) or tags
            keywords = _string_list(route_spec.get("keywords"))
            patterns = _string_list(route_spec.get("patterns"))
            route_family = str(route_spec.get("route_family") or "").strip() or (
                f"doc_domain.{document_id}" if document_id else "doc_domain.live"
            )
            default_route_id = route_family if route_family.startswith("doc_search.") else f"doc_search.{document_id}"
            if len(route_specs) > 1 and default_route_id == f"doc_search.{document_id}":
                default_route_id = f"doc_search.{document_id}.{index}"
            route_id = str(route_spec.get("route_id") or "").strip() or default_route_id
            extra_selectors = _string_list(route_spec.get("document_selectors") or route_spec.get("preferred_document_ids"))
            preferred_document_ids = _dedupe(base_preferred_document_ids + extra_selectors)
            route = _normalize_route_card(
                {
                    "route_id": route_id,
                    "route_family": route_family,
                    "route_kind": "doc_domain",
                    "authority": "primary",
                    "document_id": document_id,
                    "document_selectors": preferred_document_ids,
                    "title": title,
                    "summary": summary,
                    "topics": topics,
                    "keywords": _dedupe(
                        keywords + [title, relative_path, original_filename]
                    ),
                    "patterns": _dedupe(patterns + [title, relative_path]),
                    "generated_keywords": _dedupe(tags + topics + _terms(summary)[:24]),
                    "executor": "doc_search",
                    "executor_args_template": {"preferred_document_ids": preferred_document_ids},
                    "observability_labels": {"document_id": document_id},
                    "argument_hints": dict(route_spec.get("argument_hints") or {}),
                },
                origin="runtime_live_documents",
            )
            if route is not None:
                cards.append(route)
    return cards


def _load_catalog_file(path: Path, *, origin: str) -> dict[str, Any] | None:
    try:
        raw_text = path.read_text(encoding="utf-8")
        payload = json.loads(raw_text)
    except Exception:
        return None

    routes_payload = payload if isinstance(payload, list) else payload.get("routes")
    if not isinstance(routes_payload, list):
        return None

    source_owner = _truth_source_owner(origin, payload if isinstance(payload, dict) else None)
    normalization_errors: list[str] = []
    routes: list[dict[str, Any]] = []
    for route in routes_payload:
        if isinstance(route, dict):
            route_owner = str(
                route.get("route_owner")
                or route.get("source_owner")
                or route.get("owner")
                or source_owner
            ).strip()
            normalized = _normalize_route_card(
                route,
                origin=origin,
                source_owner=route_owner,
                errors=normalization_errors,
            )
            if normalized is not None:
                routes.append(normalized)

    manifest_digest = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    return {
        "catalog_id": str(payload.get("catalog_id") or ROUTING_CATALOG_ID) if isinstance(payload, dict) else ROUTING_CATALOG_ID,
        "schema_version": int(payload.get("schema_version") or ROUTING_SCHEMA_VERSION) if isinstance(payload, dict) else ROUTING_SCHEMA_VERSION,
        "catalog_version": str(payload.get("catalog_version") or path.stem) if isinstance(payload, dict) else path.stem,
        "generated_at": str(payload.get("generated_at") or _utcnow()) if isinstance(payload, dict) else _utcnow(),
        "routes": routes,
        "manifest_origin": origin,
        "manifest_path": str(path),
        "manifest_digest": manifest_digest,
        "source_owner": source_owner,
        "source_name": str(payload.get("source_name") or path.name) if isinstance(payload, dict) else path.name,
        "normalization_errors": normalization_errors,
        "source_manifests": list(payload.get("source_manifests") or []) if isinstance(payload, dict) else [],
        "source_digests": dict(payload.get("source_digests") or {}) if isinstance(payload, dict) else {},
        "validation_report": dict(payload.get("validation_report") or {}) if isinstance(payload, dict) else {},
    }


def _explicit_override_ids(route: dict[str, Any]) -> set[str]:
    values: list[Any] = []
    for key in ("overrides_route_ids", "override_route_ids", "allow_override_route_ids"):
        raw = route.get(key)
        if isinstance(raw, list):
            values.extend(raw)
    for key in ("overrides_route_id", "override_route_id", "allow_override_route_id"):
        raw = route.get(key)
        if raw:
            values.append(raw)
    if route.get("allow_route_id_override") is True or route.get("catalog_override") is True:
        values.append(route.get("route_id"))
    return {str(value or "").strip() for value in values if str(value or "").strip()}


def _source_manifest_entry(payload: dict[str, Any]) -> dict[str, Any]:
    manifest_path = str(payload.get("manifest_path") or "").strip()
    source_name = str(payload.get("source_name") or payload.get("manifest_origin") or "source").strip()
    digest = str(payload.get("manifest_digest") or "").strip()
    if not digest:
        digest = _json_digest(payload.get("routes") or [])
    entry = {
        "source_name": source_name,
        "source_owner": str(payload.get("source_owner") or _truth_source_owner(str(payload.get("manifest_origin") or ""))).strip(),
        "manifest_origin": str(payload.get("manifest_origin") or "").strip(),
        "manifest_path": manifest_path,
        "manifest_digest": digest,
        "catalog_version": str(payload.get("catalog_version") or "").strip(),
        "route_count": len([route for route in payload.get("routes", []) if isinstance(route, dict)]),
    }
    return entry


def _route_count_by_kind(routes: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"corp_table": 0, "corp_script": 0, "doc_domain": 0}
    for route in routes:
        route_kind = str(route.get("route_kind") or "unknown")
        counts[route_kind] = counts.get(route_kind, 0) + 1
    return counts


def _covered_corp_db_domains(routes: list[dict[str, Any]]) -> set[str]:
    covered: set[str] = set()
    kind_domains = {
        "hybrid_search": {"kb_chunk"},
        "lamp_exact": {"lamp", "sku"},
        "lamp_suggest": {"lamp"},
        "sku_by_code": {"sku", "lamp"},
        "lamp_filters": {"lamp", "category", "mounting_type"},
        "category_lamps": {"category", "lamp"},
        "category_mountings": {"category_mounting", "category", "mounting_type"},
        "sphere_curated_categories": {"sphere", "category"},
        "sphere_categories": {"sphere", "category"},
        "portfolio_by_sphere": {"portfolio", "sphere"},
        "portfolio_examples_by_lamp": {"portfolio", "sphere", "lamp", "category"},
        "application_recommendation": {"portfolio", "sphere", "category", "lamp"},
    }
    for route in routes:
        if str(route.get("executor") or route.get("tool_name") or "") != "corp_db_search":
            continue
        args = route.get("locked_args") if isinstance(route.get("locked_args"), dict) else {}
        template = route.get("executor_args_template") if isinstance(route.get("executor_args_template"), dict) else {}
        scopes = set(str(item or "").strip() for item in route.get("table_scopes") or [])
        route_text = " ".join(
            [
                str(route.get("route_id") or ""),
                str(route.get("route_family") or ""),
                " ".join(scopes),
            ]
        ).lower()
        kind = str(args.get("kind") or template.get("kind") or "").strip()
        covered.update(kind_domains.get(kind, set()))
        for source in (args, template):
            entity_types = source.get("entity_types")
            if isinstance(entity_types, list):
                covered.update(str(item or "").strip() for item in entity_types if str(item or "").strip())
            if source.get("source_files") or str(source.get("knowledge_route_id") or "").startswith("corp_kb."):
                covered.add("kb_chunk")
        for domain in KNOWN_CORP_DB_DOMAINS:
            if domain in route_text:
                covered.add(domain)
    return covered


def _validate_route_fallback_policies(
    routes: list[dict[str, Any]],
    *,
    errors: list[str],
    warnings: list[str],
) -> None:
    routes_by_id = {
        str(route.get("route_id") or ""): route
        for route in routes
        if isinstance(route, dict) and str(route.get("route_id") or "").strip()
    }
    for route in routes:
        route_id = str(route.get("route_id") or "")
        family_id = str(route.get("family_id") or "")
        fallback_ids = _string_list(route.get("fallback_route_ids") or [])
        raw_policy = route.get("fallback_policy") if isinstance(route.get("fallback_policy"), dict) else {}
        cross_family_ids = set(
            _string_list(
                raw_policy.get("cross_family_route_ids")
                or route.get("cross_family_fallback_route_ids")
                or []
            )
        )
        undeclared_cross_family_ids = [fallback_id for fallback_id in cross_family_ids if fallback_id not in fallback_ids]
        for fallback_id in undeclared_cross_family_ids:
            errors.append(f"{route_id}: cross-family fallback {fallback_id} must also be declared in fallback_route_ids")
        for fallback_id in fallback_ids:
            target_route = routes_by_id.get(fallback_id)
            if target_route is None:
                errors.append(f"{route_id}: fallback route {fallback_id} is missing from the active catalog")
                continue
            target_family_id = str(target_route.get("family_id") or "")
            if fallback_id in cross_family_ids:
                if target_family_id == family_id:
                    warnings.append(
                        f"{route_id}: fallback route {fallback_id} is declared cross-family but stays inside family {family_id}"
                    )
                continue
            if target_family_id != family_id:
                errors.append(
                    f"{route_id}: fallback route {fallback_id} leaves family {family_id} and requires explicit cross_family_fallback_route_ids"
                )


def _validate_merged_catalog(
    routes: list[dict[str, Any]],
    *,
    duplicate_errors: list[dict[str, Any]],
    overrides: list[dict[str, Any]],
    source_manifests: list[dict[str, Any]],
    normalization_errors: list[str],
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    for item in normalization_errors:
        errors.append(f"route normalization failed: {item}")
    for duplicate in duplicate_errors:
        errors.append(
            "duplicate route_id "
            f"{duplicate['route_id']} from owners {duplicate['existing_owner']} and {duplicate['incoming_owner']}"
        )

    production_routes = [route for route in routes if str(route.get("route_owner") or "") != "bootstrap"]
    truth_source_count = len(
        {
            str(source.get("source_owner") or "")
            for source in source_manifests
            if str(source.get("source_owner") or "") in TRUTH_SOURCE_OWNERS
            and int(source.get("route_count") or 0) > 0
        }
    )
    if not production_routes:
        warnings.append("catalog contains only bootstrap routes; production requires a published source-owned catalog")

    for route in production_routes:
        route_id = str(route.get("route_id") or "")
        for field_name in ("executor", "locked_args", "argument_schema", "evidence_policy"):
            if field_name not in route or route.get(field_name) in (None, "", {}):
                errors.append(f"{route_id}: missing required production field {field_name}")
        if str(route.get("route_kind") or "") == "doc_domain" and not route.get("document_selectors"):
            errors.append(f"{route_id}: doc_domain route must declare concrete document_selectors")
        if str(route.get("route_kind") or "") == "corp_table":
            has_scope = bool(route.get("table_scopes")) or bool(route.get("scope_reason") or route.get("broad_scope_reason"))
            if not has_scope:
                errors.append(f"{route_id}: corp_table route must declare table/source scope or broad_scope_reason")

    _validate_route_fallback_policies(routes, errors=errors, warnings=warnings)

    covered_domains = _covered_corp_db_domains(routes)
    missing_domains = [domain for domain in KNOWN_CORP_DB_DOMAINS if domain not in covered_domains]
    if missing_domains:
        warnings.append("missing corp DB domain coverage: " + ", ".join(missing_domains))

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "duplicate_route_ids": duplicate_errors,
        "overrides": overrides,
        "route_count_by_kind": _route_count_by_kind(routes),
        "production_route_count": len(production_routes),
        "truth_source_count": truth_source_count,
        "known_corp_db_domains": list(KNOWN_CORP_DB_DOMAINS),
        "covered_corp_db_domains": sorted(covered_domains),
        "missing_corp_db_domains": missing_domains,
    }


def _merge_catalogs(payloads: list[dict[str, Any]], *, manifest_origin: str) -> dict[str, Any]:
    merged_by_id: dict[str, dict[str, Any]] = {}
    catalog_id = ROUTING_CATALOG_ID
    schema_version = ROUTING_SCHEMA_VERSION
    catalog_version = "bootstrap"
    generated_at = _utcnow()
    manifest_paths: list[str] = []
    source_manifests: list[dict[str, Any]] = []
    source_digests: dict[str, str] = {}
    duplicate_errors: list[dict[str, Any]] = []
    overrides: list[dict[str, Any]] = []
    normalization_errors: list[str] = []

    for payload in payloads:
        catalog_id = str(payload.get("catalog_id") or catalog_id)
        schema_version = int(payload.get("schema_version") or schema_version)
        catalog_version = str(payload.get("catalog_version") or catalog_version)
        generated_at = str(payload.get("generated_at") or generated_at)
        source_entry = _source_manifest_entry(payload)
        source_manifests.append(source_entry)
        source_digests[source_entry["source_name"]] = source_entry["manifest_digest"]
        manifest_path = str(payload.get("manifest_path") or "").strip()
        if manifest_path:
            manifest_paths.append(manifest_path)
        normalization_errors.extend(str(item) for item in payload.get("normalization_errors", []) if str(item).strip())
        for route in payload.get("routes", []):
            if not isinstance(route, dict) or not route.get("route_id"):
                continue
            route_id = str(route["route_id"])
            incoming = dict(route)
            incoming_owner = str(incoming.get("route_owner") or payload.get("source_owner") or "repo_static")
            incoming["route_owner"] = incoming_owner
            existing = merged_by_id.get(route_id)
            if existing is None:
                merged_by_id[route_id] = incoming
                continue

            existing_owner = str(existing.get("route_owner") or "")
            if existing_owner == incoming_owner:
                if existing_owner == "bootstrap":
                    # Bootstrap-owned routes are defined by the code/YAML shipped with the
                    # current deploy. When _revalidate_loaded_runtime_catalog re-merges a
                    # persisted runtime-catalog snapshot against a freshly computed bootstrap
                    # payload, both copies of a bootstrap route tie on owner here -- keep the
                    # first-seen (fresh) one rather than last-wins, so a frozen snapshot can
                    # never shadow a core/routes/*.yaml edit until a manual catalog rebuild.
                    continue
                merged_by_id[route_id] = incoming
                continue

            existing_priority = ROUTE_OWNER_PRIORITY.get(existing_owner, 10)
            incoming_priority = ROUTE_OWNER_PRIORITY.get(incoming_owner, 10)
            bootstrap_override = "bootstrap" in {existing_owner, incoming_owner}
            explicit_override = (
                route_id in _explicit_override_ids(incoming)
                or route_id in _explicit_override_ids(existing)
            )
            if bootstrap_override or explicit_override:
                winner = incoming if incoming_priority >= existing_priority else existing
                loser = existing if winner is incoming else incoming
                merged_by_id[route_id] = dict(winner)
                overrides.append(
                    {
                        "route_id": route_id,
                        "winner_owner": str(winner.get("route_owner") or ""),
                        "loser_owner": str(loser.get("route_owner") or ""),
                        "reason": "bootstrap_precedence" if bootstrap_override else "explicit_override",
                    }
                )
                continue

            duplicate_errors.append(
                {
                    "route_id": route_id,
                    "existing_owner": existing_owner,
                    "incoming_owner": incoming_owner,
                }
            )

    routes = list(merged_by_id.values())
    validation_report = _validate_merged_catalog(
        routes,
        duplicate_errors=duplicate_errors,
        overrides=overrides,
        source_manifests=source_manifests,
        normalization_errors=normalization_errors,
    )
    return {
        "catalog_id": catalog_id,
        "schema_version": schema_version,
        "catalog_version": catalog_version,
        "generated_at": generated_at,
        "route_count": len(routes),
        "route_count_by_kind": validation_report["route_count_by_kind"],
        "routes": routes,
        "manifest_origin": manifest_origin,
        "manifest_paths": manifest_paths,
        "source_manifests": source_manifests,
        "source_digests": source_digests,
        "validation_report": validation_report,
    }


def _repo_catalog_payloads() -> list[dict[str, Any]]:
    route_dir = _repo_route_dir()
    if not route_dir.exists():
        return []
    payloads: list[dict[str, Any]] = []
    for path in sorted(route_dir.glob("*.json")):
        payload = _load_catalog_file(path, origin="repo_manifest")
        if payload is not None:
            payloads.append(payload)
    return payloads


def _bootstrap_catalog_payload() -> dict[str, Any]:
    routes = [
        normalized
        for normalized in (_normalize_route_card(route, origin="bootstrap") for route in bootstrap_route_cards())
        if normalized is not None
    ]
    payload = {
        "catalog_id": ROUTING_CATALOG_ID,
        "schema_version": ROUTING_SCHEMA_VERSION,
        "catalog_version": "bootstrap-v1",
        "generated_at": _utcnow(),
        "route_count": len(routes),
        "routes": routes,
        "manifest_origin": "bootstrap",
        "manifest_paths": [],
        "manifest_digest": _json_digest(routes),
        "source_owner": "bootstrap",
        "source_name": "bootstrap",
    }
    source_entry = _source_manifest_entry(payload)
    validation_report = _validate_merged_catalog(
        routes,
        duplicate_errors=[],
        overrides=[],
        source_manifests=[source_entry],
        normalization_errors=[],
    )
    payload["route_count_by_kind"] = validation_report["route_count_by_kind"]
    payload["source_manifests"] = [source_entry]
    payload["source_digests"] = {source_entry["source_name"]: source_entry["manifest_digest"]}
    payload["validation_report"] = validation_report
    return payload


def _document_catalog_payload() -> dict[str, Any]:
    routes = build_document_route_cards()
    return {
        "catalog_id": ROUTING_CATALOG_ID,
        "schema_version": ROUTING_SCHEMA_VERSION,
        "catalog_version": _utcnow(),
        "generated_at": _utcnow(),
        "route_count": len(routes),
        "routes": routes,
        "manifest_origin": "runtime_live_documents",
        "manifest_paths": [],
        "manifest_digest": _json_digest(routes),
        "source_owner": "document_ingestion",
        "source_name": "document_ingestion.live_manifests",
    }


def _catalog_is_valid(payload: dict[str, Any] | None) -> bool:
    if not payload:
        return False
    report = payload.get("validation_report")
    if isinstance(report, dict) and report:
        return bool(report.get("valid"))
    return bool(payload.get("routes")) and int(payload.get("route_count") or 0) > 0


def build_routing_index() -> dict[str, Any]:
    payloads = [_bootstrap_catalog_payload(), *_repo_catalog_payloads(), _document_catalog_payload()]
    payload = _merge_catalogs(payloads, manifest_origin="runtime_merged")
    generated_at = _utcnow()
    payload["catalog_version"] = generated_at
    payload["generated_at"] = generated_at
    payload["manifest_origin"] = "runtime_merged"
    _runtime_catalog_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def _revalidate_loaded_runtime_catalog(payload: dict[str, Any]) -> dict[str, Any]:
    """Recompute runtime catalog metadata with the current route-card contract.

    Runtime catalogs may outlive code deploys. Merge the current bootstrap cards
    first so newly shipped core routes become visible without requiring a
    writable catalog rebuild during request handling; loaded runtime routes keep
    precedence for already-published route ids.
    """
    revalidated = _merge_catalogs([_bootstrap_catalog_payload(), payload], manifest_origin="runtime_merged")
    revalidated["manifest_origin"] = "runtime_merged"
    return revalidated


def load_routing_index() -> dict[str, Any]:
    required = _catalog_required_for_runtime()
    runtime_catalog = _load_catalog_file(_runtime_catalog_path(), origin="runtime_merged")
    if runtime_catalog is not None:
        revalidated_runtime_catalog = _revalidate_loaded_runtime_catalog(runtime_catalog)
        if _catalog_is_valid(revalidated_runtime_catalog):
            return revalidated_runtime_catalog
        if required:
            raise RouteCatalogUnavailable("active merged route catalog failed validation")
    elif required:
        raise RouteCatalogUnavailable("no active merged route catalog is published")

    payloads = _repo_catalog_payloads()
    legacy_runtime = _load_catalog_file(_legacy_runtime_index_path(), origin="runtime_legacy")
    if legacy_runtime is not None and not required:
        return _merge_catalogs([*payloads, legacy_runtime], manifest_origin="runtime_legacy")

    if payloads:
        return _merge_catalogs([_bootstrap_catalog_payload(), *payloads], manifest_origin="published")
    return _bootstrap_catalog_payload()


def routing_catalog_health() -> dict[str, Any]:
    required = _catalog_required_for_runtime()
    try:
        catalog = load_routing_index()
    except RouteCatalogUnavailable as exc:
        return {
            "status": "unavailable",
            "required": required,
            "error": str(exc),
            "catalog_path": str(_runtime_catalog_path()),
        }
    report = catalog.get("validation_report") if isinstance(catalog.get("validation_report"), dict) else {}
    valid = _catalog_is_valid(catalog)
    if required and str(catalog.get("manifest_origin") or "") != "runtime_merged":
        return {
            "status": "unavailable",
            "required": required,
            "error": "production requires an active merged route catalog",
            "manifest_origin": str(catalog.get("manifest_origin") or ""),
            "catalog_path": str(_runtime_catalog_path()),
            "validation_report": report,
        }
    if required and int(report.get("truth_source_count") or 0) <= 0:
        return {
            "status": "unavailable",
            "required": required,
            "error": "production catalog has no source-owned route manifests",
            "manifest_origin": str(catalog.get("manifest_origin") or ""),
            "catalog_path": str(_runtime_catalog_path()),
            "validation_report": report,
        }
    return {
        "status": "ok" if valid else "degraded",
        "required": required,
        "manifest_origin": str(catalog.get("manifest_origin") or ""),
        "catalog_version": str(catalog.get("catalog_version") or ""),
        "schema_version": int(catalog.get("schema_version") or 0),
        "route_count": int(catalog.get("route_count") or 0),
        "route_count_by_kind": dict(catalog.get("route_count_by_kind") or {}),
        "catalog_path": str(_runtime_catalog_path()),
        "validation_report": report,
    }


def _is_explicit_document_request(query: str) -> bool:
    query_text = _normalize(query)
    certificate_document_context = _intent_contains(query_text, CERTIFICATE_TERMS) and _intent_contains(
        query_text,
        CERTIFICATE_DOCUMENT_CONTEXT_KEYWORDS,
    )
    subtype_by_lamp_context = bool(_detect_document_type(query)) and any(
        marker in query_text
        for marker in (
            " на ",
            " для ",
            "светильник",
            "модель",
            "серия",
            "линейк",
        )
    )
    return (
        any(keyword in query_text for keyword in DOCUMENT_REQUEST_KEYWORDS)
        or certificate_document_context
        or subtype_by_lamp_context
        or any(pattern in query_text for pattern in DOCUMENT_LINK_CONTEXT_PATTERNS)
        or any(pattern in query_text for pattern in DOCUMENT_IN_TEXT_PATTERNS)
    )


def _is_broad_series_query(query: str) -> bool:
    query_text = _normalize(query)
    if not query_text:
        return False
    if any(marker in query_text for marker in BROAD_SERIES_QUERY_EXCLUSIONS):
        return False
    return any(marker in query_text for marker in BROAD_SERIES_QUERY_CUES)


def _is_sphere_category_query(query: str) -> bool:
    query_text = _normalize(query)
    if "категор" not in query_text:
        return False
    if any(marker in query_text for marker in SPHERE_CATEGORY_QUERY_CUES):
        return True
    return _intent_contains(query_text, APPLICATION_RECOMMENDATION_KEYWORDS)


def _is_series_or_category_mounting_query(query: str) -> bool:
    query_text = _normalize(query)
    if not _intent_contains(query_text, MOUNTING_QUERY_CUES):
        return False
    return any(marker in query_text for marker in ("сер", "категор", "линейк", "модел"))


def _mentions_specific_mounting_type(query: str) -> bool:
    query_text = _normalize(query)
    return any(
        _normalize(mounting_type) in query_text
        for mounting_type in canonical_mounting_type_names()
        if mounting_type
    )


def _is_mounting_compatibility_query(query: str) -> bool:
    query_text = _normalize(query)
    compatibility_wording = any(
        marker in query_text
        for marker in ("совместим", "совместимость", "подходит", "подойдут", "подойдёт", "подойдет")
    )
    return compatibility_wording and _mentions_specific_mounting_type(query)


def _is_mountings_family_query(query: str) -> bool:
    return _intent_contains(_normalize(query), MOUNTING_QUERY_CUES) or _mentions_specific_mounting_type(query)


def _is_series_description_query(query: str) -> bool:
    query_text = _normalize(query)
    if _is_explicit_document_request(query) or _is_mountings_family_query(query) or _is_codes_family_query(query):
        return False
    if _is_broad_series_query(query):
        return True
    if any(marker in query_text for marker in ("опиши сери", "описание серии", "расскажи про сери", "что за серия")):
        return not any(marker in query_text for marker in BROAD_SERIES_QUERY_EXCLUSIONS)
    if any(marker in query_text for marker in SERIES_COMPARISON_QUERY_CUES):
        return "сери" in query_text or _distinct_series_mentions(query) > 1
    return (
        any(marker in query_text for marker in SERIES_KNOWLEDGE_SCOPE_CUES)
        and any(marker in query_text for marker in SERIES_KNOWLEDGE_FACT_CUES)
    )


def _detect_document_type(query: str) -> str | None:
    query_text = _normalize(query)
    matches = [
        document_type
        for document_type in DOCUMENT_TYPE_ENUM
        if _intent_contains(query_text, DOCUMENT_TYPE_TERMS[document_type])
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _detect_code_system(query: str) -> str | None:
    query_text = _normalize(query)
    matches = [
        code_system
        for code_system, terms in CODE_SYSTEM_TERMS.items()
        if _intent_contains(query_text, terms)
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return "mixed"
    return None


def _distinct_series_mentions(query: str) -> int:
    query_text = _normalize(query)
    return len({name.lower() for name in canonical_series_names() if name.lower() in query_text})


def _is_documents_by_lamp_query(query: str) -> bool:
    query_text = _normalize(query)
    if not _is_explicit_document_request(query):
        return False
    if _distinct_series_mentions(query) > 1:
        return False
    if any(
        marker in query_text
        for marker in (
            "какие документы есть",
            "документы на",
            "документы для",
            "паспорт на",
            "паспорт для",
            "сертификаты на",
            "сертификаты для",
        )
    ):
        return True
    document_type = _detect_document_type(query)
    if not document_type:
        return False
    return any(
        marker in query_text
        for marker in (
            " на ",
            " для ",
            "серии ",
            "модели ",
            "светильник",
        )
    )


def _is_reverse_code_lookup_query(query: str) -> bool:
    query_text = _normalize(query)
    reverse_patterns = (
        "что это за модель по коду",
        "что за модель по коду",
        "какая модель по коду",
        "какой светильник по коду",
        "найди модель по коду",
        "найди светильник по коду",
        "модель по etm",
        "модель по етм",
        "модель по oracl",
        "модель по оракл",
        "светильник по etm",
        "светильник по етм",
        "светильник по oracl",
        "светильник по оракл",
        "по артикулу",
    )
    if any(pattern in query_text for pattern in reverse_patterns):
        return True
    query_terms = set(_terms(query))
    has_lookup_target = bool(query_terms.intersection({"модель", "светильник"}))
    has_by_code_marker = any(marker in query_text for marker in ("по коду", "по etm", "по етм", "по oracl", "по оракл"))
    return has_lookup_target and has_by_code_marker


def _is_codes_for_lamp_query(query: str) -> bool:
    query_text = _normalize(query)
    if _is_reverse_code_lookup_query(query):
        return False
    if any(
        marker in query_text
        for marker in (
            "какие коды у",
            "какие артикулы у",
            "какой артикул у",
            "sku для модели",
            "артикулы для модели",
            "какой etm-код у",
            "какой etm код у",
            "какой етм код у",
            "какой oracl-код у",
            "какой oracl код у",
            "какой оракл код у",
        )
    ):
        return True
    query_terms = set(_terms(query))
    asks_for_specific_code = bool(query_terms.intersection({"какой", "какие", "покажи", "дай"})) and bool(_detect_code_system(query))
    has_lamp_context = any(marker in query_text for marker in (" у ", " для ", "модел", "светильник", "серия", "линейк"))
    return asks_for_specific_code and has_lamp_context


def _is_codes_family_query(query: str) -> bool:
    query_text = _normalize(query)
    return any(
        marker in query_text
        for marker in (
            "код",
            "коды",
            "артикул",
            "артикулы",
            "sku",
            "etm",
            "етм",
            "oracl",
            "оракл",
        )
    )


def _is_showcase_category_query(query: str) -> bool:
    query_text = _normalize(query)
    if "категор" not in query_text:
        return False
    return any(marker in query_text for marker in ("покажи примеры", "примеры моделей", "как пример", "представительные модели", "витрина"))


def _is_broad_portfolio_query(query: str) -> bool:
    query_text = _normalize(query)
    if not _intent_contains(query_text, PORTFOLIO_LOOKUP_KEYWORDS):
        return False
    if any(
        marker in query_text
        for marker in (
            "расскажи подробнее про",
            "расскажи про объект",
            "расскажи про проект",
            "покажи проект",
            "конкретный объект",
            "конкретный проект",
        )
    ):
        return False
    return any(
        marker in query_text
        for marker in (
            "какие реализован",
            "реализованные проект",
            "реализованные объект",
            "список объектов",
            "список проектов",
            "портфолио по",
            "проекты для",
            "проекты по",
            "объекты для",
            "объекты по",
            "по склад",
            "для склад",
            "по стади",
            "для стади",
            "по аэроп",
            "для аэроп",
            "по ржд",
            "для ржд",
            "по офис",
            "для офис",
            "по логист",
            "для логист",
        )
    )


def _route_intent_family(route: dict[str, Any]) -> str:
    route_id = str(route.get("route_id") or "")
    route_family = str(route.get("route_family") or "")
    if str(route.get("family_id") or "") == "documents" or route_id in DOCUMENTS_FAMILY_ROUTE_IDS:
        return "document_lookup"
    if route_id in {
        "corp_kb.series_description",
        "corp_db.catalog_lookup",
        "corp_db.sku_lookup",
        "corp_db.sku_codes_lookup",
        "corp_db.category_lamps",
        "corp_db.showcase_lamps_by_category",
        "corp_db.sphere_curated_categories",
        "corp_db.sphere_categories",
        "corp_db.lamp_filters",
        "corp_db.category_mountings",
        "corp_db.lamp_mounting_compatibility",
    }:
        return "catalog_lookup"
    if route_id.startswith("corp_kb."):
        return "company_fact"
    if route_id == "corp_db.application_recommendation":
        return "application_recommendation"
    if route_id in {"corp_db.portfolio_lookup", "corp_db.portfolio_by_sphere", "corp_db.portfolio_examples_by_lamp"}:
        return "portfolio_lookup"
    if route_family.startswith("doc_domain.") or str(route.get("route_kind") or "") == "doc_domain":
        return "document_lookup"
    return "other"


def _intent_contains(query_text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in query_text for needle in needles)


def _infer_intent_family(query: str, *, explicit_document_request: bool) -> str:
    query_text = _normalize(query)
    if explicit_document_request:
        return "document_lookup"
    if _is_sphere_category_query(query):
        return "catalog_lookup"
    if _intent_contains(query_text, PORTFOLIO_LOOKUP_KEYWORDS):
        return "portfolio_lookup"
    if _is_mountings_family_query(query):
        return "catalog_lookup"
    if _intent_contains(query_text, APPLICATION_RECOMMENDATION_KEYWORDS) or _intent_contains(query_text, ORCHESTRATION_KEYWORDS):
        return "application_recommendation"
    if _intent_contains(query_text, CATALOG_LOOKUP_KEYWORDS):
        return "catalog_lookup"
    if _intent_contains(query_text, COMPANY_FACT_KEYWORDS):
        return "company_fact"
    return "other"


def _visible_catalog_routes(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        route
        for route in catalog.get("routes", [])
        if isinstance(route, dict)
        and str(route.get("route_id") or "").strip()
        and route.get("hidden") is not True
        and route.get("selector_visible") is not False
    ]


def _route_matches_query(route: dict[str, Any], query: str) -> bool:
    query_text = _normalize(query)
    query_terms = {term for term in _terms(query) if term not in ROUTE_MATCH_STOPWORDS and len(term) > 1}
    route_id = str(route.get("route_id") or "").lower()
    route_family = str(route.get("route_family") or "").lower()
    if route_id == "corp_db.documents_by_lamp_name":
        return _is_documents_by_lamp_query(query)
    if route_id in DOCUMENT_SUBTYPE_ROUTE_IDS.values():
        document_type = str(
            (route.get("locked_args") or {}).get("document_type")
            or (route.get("executor_args_template") or {}).get("document_type")
            or ""
        ).strip()
        return _is_documents_by_lamp_query(query) and _detect_document_type(query) == document_type
    if route_id == "corp_db.sku_codes_lookup":
        return _is_codes_for_lamp_query(query)
    if route_id == "corp_db.sku_lookup":
        return _is_reverse_code_lookup_query(query) or _is_codes_family_query(query)
    if route_id and route_id in query_text:
        return True
    if route_family and route_family in query_text:
        return True

    for pattern in route.get("patterns", []) or []:
        normalized = _normalize(pattern)
        if normalized and normalized in query_text:
            return True

    for keyword in route.get("keywords", []) or []:
        keyword_terms = [term for term in _terms(keyword) if term not in ROUTE_MATCH_STOPWORDS and len(term) > 1]
        if not keyword_terms:
            continue
        required_matches = 1 if len(keyword_terms) == 1 else min(2, len(keyword_terms))
        if len(query_terms.intersection(keyword_terms)) >= required_matches:
            return True

    title = _normalize(route.get("title"))
    title_terms = [term for term in _terms(title) if term not in ROUTE_MATCH_STOPWORDS and len(term) > 1]
    return bool(title_terms and len(query_terms.intersection(title_terms)) >= min(2, len(title_terms)))


def _preferred_route_ids_for_intent(query: str, intent_family: str) -> list[str]:
    query_text = _normalize(query)
    if intent_family == "portfolio_lookup":
        if _is_broad_portfolio_query(query) or _intent_contains(query_text, ("список", "какие объект", "какие проект", "для ржд", "ржд")):
            return ["corp_db.portfolio_by_sphere", "corp_db.portfolio_lookup", "corp_db.portfolio_examples_by_lamp"]
        return ["corp_db.portfolio_lookup", "corp_db.portfolio_by_sphere", "corp_db.portfolio_examples_by_lamp"]
    if intent_family == "application_recommendation":
        return ["corp_db.application_recommendation", "corp_db.portfolio_lookup", "corp_db.portfolio_by_sphere"]
    if intent_family == "document_lookup":
        document_type = _detect_document_type(query)
        if document_type and _is_documents_by_lamp_query(query):
            return [DOCUMENT_SUBTYPE_ROUTE_IDS[document_type], "corp_db.documents_by_lamp_name"]
        return ["corp_db.documents_by_lamp_name"]
    if intent_family == "catalog_lookup":
        if _is_series_description_query(query):
            return ["corp_kb.series_description", "corp_kb.company_common"]
        if _is_reverse_code_lookup_query(query):
            return ["corp_db.sku_lookup", "corp_db.sku_codes_lookup", "corp_db.catalog_lookup"]
        if _is_codes_for_lamp_query(query):
            return ["corp_db.sku_codes_lookup", "corp_db.sku_lookup", "corp_db.catalog_lookup"]
        if _is_codes_family_query(query):
            return ["corp_db.sku_lookup", "corp_db.sku_codes_lookup", "corp_db.catalog_lookup"]
        if _is_showcase_category_query(query):
            return ["corp_db.showcase_lamps_by_category", "corp_db.category_lamps", "corp_db.catalog_lookup"]
        if _is_sphere_category_query(query):
            return ["corp_db.sphere_curated_categories", "corp_db.category_lamps", "corp_db.catalog_lookup", "corp_db.category_mountings"]
        if _is_mounting_compatibility_query(query):
            return ["corp_db.lamp_mounting_compatibility", "corp_db.category_mountings", "corp_db.catalog_lookup", "corp_db.category_lamps"]
        if _is_mountings_family_query(query):
            return ["corp_db.category_mountings", "corp_db.lamp_mounting_compatibility", "corp_db.catalog_lookup", "corp_db.category_lamps"]
        if _is_series_or_category_mounting_query(query):
            return ["corp_db.category_mountings", "corp_db.lamp_mounting_compatibility", "corp_db.catalog_lookup", "corp_db.category_lamps"]
        return ["corp_db.catalog_lookup", "corp_db.sku_lookup", "corp_db.category_lamps", "corp_db.sphere_curated_categories"]
    if intent_family == "company_fact":
        if _intent_contains(query_text, ("luxnet", "люкснет")):
            return ["corp_kb.luxnet", "corp_kb.company_common"]
        if _intent_contains(query_text, ("норм", "освещенн", "освещённ")):
            return ["corp_kb.lighting_norms", "corp_kb.company_common"]
        return ["corp_kb.company_common", "corp_kb.luxnet", "corp_kb.lighting_norms"]
    return []


def _dedupe_routes(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for route in routes:
        route_id = str(route.get("route_id") or "")
        if route_id and route_id not in seen:
            seen.add(route_id)
            result.append(route)
    return result


def _matching_document_routes(routes: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    return [
        route
        for route in routes
        if _route_intent_family(route) == "document_lookup" and _route_matches_query(route, query)
    ]


def _ordered_routes_for_intent(routes: list[dict[str, Any]], query: str, intent_family: str) -> list[dict[str, Any]]:
    by_id = {str(route.get("route_id") or ""): route for route in routes}
    preferred = [by_id[route_id] for route_id in _preferred_route_ids_for_intent(query, intent_family) if route_id in by_id]
    intent_matches = [route for route in routes if _route_intent_family(route) == intent_family and route not in preferred]
    text_matches = [route for route in routes if _route_matches_query(route, query) and route not in preferred and route not in intent_matches]
    if intent_family == "document_lookup":
        document_text_matches = _matching_document_routes(routes, query)
        if _is_documents_by_lamp_query(query):
            return _dedupe_routes([*preferred, *document_text_matches, *intent_matches, *text_matches, *routes])
        return _dedupe_routes([*document_text_matches, *preferred, *intent_matches, *text_matches, *routes])
    if intent_family == "company_fact":
        document_text_matches = _matching_document_routes(routes, query)
        if document_text_matches:
            return _dedupe_routes([*document_text_matches, *preferred, *intent_matches, *text_matches, *routes])
    if intent_family == "other":
        document_text_matches = _matching_document_routes(routes, query)
        if document_text_matches:
            return _dedupe_routes([*document_text_matches, *preferred, *intent_matches, *text_matches, *routes])
    return _dedupe_routes([*preferred, *intent_matches, *text_matches, *routes])


def _ordered_routes_for_degraded_selection(routes: list[dict[str, Any]], query: str, intent_family: str) -> list[dict[str, Any]]:
    if intent_family == "document_lookup":
        by_id = {str(route.get("route_id") or ""): route for route in routes}
        preferred = [by_id[route_id] for route_id in _preferred_route_ids_for_intent(query, intent_family) if route_id in by_id]
        matches = _matching_document_routes(routes, query)
        if _is_documents_by_lamp_query(query):
            return _dedupe_routes([*preferred, *matches])
        return matches
    return _ordered_routes_for_intent(routes, query, intent_family)


def _candidate_payload(route: dict[str, Any], *, intent_family: str, selection_reason: str) -> dict[str, Any]:
    payload = dict(route)
    payload["selection_reason"] = selection_reason
    payload["route_kind"] = str(route.get("route_kind") or "")
    payload["route_family"] = str(route.get("route_family") or "")
    payload["selected_route_kind"] = str(route.get("route_kind") or "")
    payload["selected_route_family"] = str(route.get("route_family") or "")
    payload["selected_family_id"] = str(route.get("family_id") or "")
    payload["selected_leaf_route_id"] = str(route.get("leaf_route_id") or route.get("route_id") or "")
    payload["selected_route_stage"] = str(route.get("route_stage") or "")
    payload["intent_family"] = intent_family
    payload["route_intent_family"] = _route_intent_family(route)
    return payload


def select_route(query: str, *, explicit_document_request: bool | None = None) -> dict[str, Any]:
    explicit_document_request = _is_explicit_document_request(query) if explicit_document_request is None else bool(explicit_document_request)
    intent_family = _infer_intent_family(query, explicit_document_request=explicit_document_request)
    try:
        catalog = load_routing_index()
    except RouteCatalogUnavailable as exc:
        return {
            "intent_family": intent_family,
            "primary_candidate": None,
            "selected": None,
            "candidate_route_ids": [],
            "secondary_candidates": [],
            "selection_reason": "",
            "selected_route_kind": "",
            "selected_route_family": "",
            "catalog_version": "",
            "catalog_origin": "",
            "route_count": 0,
            "catalog_unavailable": True,
            "temporary_unavailable": True,
            "error": str(exc),
        }
    routes = _visible_catalog_routes(catalog)
    ordered = _ordered_routes_for_degraded_selection(routes, query, intent_family)
    selected = ordered[0] if ordered else None
    selection_reason = f"degraded_intent_order:{intent_family}" if selected is not None else ""
    primary_candidate = _candidate_payload(
        selected,
        intent_family=intent_family,
        selection_reason=selection_reason,
    ) if selected is not None else None
    secondary_candidates = [
        _candidate_payload(route, intent_family=intent_family, selection_reason="degraded_catalog_candidate")
        for route in ordered[1:4]
    ] if selected is not None else []
    selected_route = None
    if primary_candidate is not None:
        selected_route = dict(primary_candidate)
        selected_route["candidate_route_ids"] = [str(route.get("route_id") or "") for route in ordered]
        selected_route["secondary_candidates"] = [
            {
                "route_id": str(item.get("route_id") or ""),
                "route_kind": str(item.get("route_kind") or ""),
                "route_family": str(item.get("route_family") or ""),
                "family_id": str(item.get("family_id") or ""),
                "leaf_route_id": str(item.get("leaf_route_id") or item.get("route_id") or ""),
                "route_stage": str(item.get("route_stage") or ""),
                "selection_reason": str(item.get("selection_reason") or ""),
                "intent_family": str(item.get("intent_family") or ""),
                "route_intent_family": str(item.get("route_intent_family") or ""),
            }
            for item in secondary_candidates
        ]
        selected_route["catalog_version"] = str(catalog.get("catalog_version") or "")
        selected_route["catalog_origin"] = str(catalog.get("manifest_origin") or "")

    return {
        "intent_family": intent_family,
        "primary_candidate": primary_candidate,
        "selected": selected_route,
        "candidate_route_ids": [str(route.get("route_id") or "") for route in ordered],
        "secondary_candidates": [
            {
                "route_id": str(item.get("route_id") or ""),
                "route_kind": str(item.get("route_kind") or ""),
                "route_family": str(item.get("route_family") or ""),
                "family_id": str(item.get("family_id") or ""),
                "leaf_route_id": str(item.get("leaf_route_id") or item.get("route_id") or ""),
                "route_stage": str(item.get("route_stage") or ""),
                "selection_reason": str(item.get("selection_reason") or ""),
                "intent_family": str(item.get("intent_family") or ""),
                "route_intent_family": str(item.get("route_intent_family") or ""),
            }
            for item in secondary_candidates
        ],
        "selection_reason": selection_reason,
        "selected_route_kind": str(selected.get("route_kind") or "") if selected is not None else "",
        "selected_route_family": str(selected.get("route_family") or "") if selected is not None else "",
        "selected_family_id": str(selected.get("family_id") or "") if selected is not None else "",
        "selected_leaf_route_id": str(selected.get("leaf_route_id") or selected.get("route_id") or "") if selected is not None else "",
        "selected_route_stage": str(selected.get("route_stage") or "") if selected is not None else "",
        "catalog_version": str(catalog.get("catalog_version") or ""),
        "catalog_origin": str(catalog.get("manifest_origin") or ""),
        "route_count": int(catalog.get("route_count") or 0),
    }


def select_route_card(query: str, *, explicit_document_request: bool | None = None) -> dict[str, Any] | None:
    return select_route(query, explicit_document_request=explicit_document_request).get("selected")


def _compact_selector_route_card(route: dict[str, Any], *, sphere_context: dict[str, Any] | None = None) -> dict[str, Any]:
    route_payload = dict(route)
    _apply_runtime_argument_overrides(route_payload, sphere_context=sphere_context)
    schema = route_payload.get("argument_schema") if isinstance(route_payload.get("argument_schema"), dict) else {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    locked_keys = set((route_payload.get("locked_args") or {}).keys()) if isinstance(route_payload.get("locked_args"), dict) else set()
    template_keys = set((route_payload.get("executor_args_template") or {}).keys()) if isinstance(route_payload.get("executor_args_template"), dict) else set()
    required_keys = set(schema.get("required") or [])
    compact_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": list(schema.get("required") or []),
        "properties": {
            key: value
            for key, value in properties.items()
            if key in required_keys
            or key in locked_keys
            or key in template_keys
            or key in {
                "query",
                "name",
                "names",
                "application_key",
                "context_profile",
                "document_type",
                "lookup_direction",
                "code_system",
                "etm",
                "oracl",
                "category",
                "series",
                "explosion_protected",
                "sphere",
                "mounting_type",
                "limit_categories",
                "limit_lamps",
                "limit_portfolio",
                "preferred_document_ids",
                "topic_facets",
                "source_files",
            }
            or key.endswith("_min")
            or key.endswith("_max")
        },
    }
    fallback_policy = route_payload.get("fallback_policy") if isinstance(route_payload.get("fallback_policy"), dict) else {}
    return {
        "route_id": str(route.get("route_id") or ""),
        "route_family": str(route.get("route_family") or ""),
        "family_id": str(route.get("family_id") or "other"),
        "family_title": str(route.get("family_title") or ""),
        "family_summary": str(route.get("family_summary") or "")[:240],
        "leaf_route_id": str(route.get("leaf_route_id") or route.get("route_id") or ""),
        "route_stage": str(route.get("route_stage") or ""),
        "route_kind": str(route.get("route_kind") or ""),
        "authority": str(route.get("authority") or ""),
        "title": str(route.get("title") or ""),
        "summary": str(route.get("summary") or "")[:500],
        # RFC-029 workstream 1 (finishing RFC-028 workstream 4): keywords/patterns stay in the
        # route YAML for humans, tests, and the degraded (LLM-unavailable) ordering only; they
        # never serialize into any selector-visible payload.
        "when_to_use": str(route.get("when_to_use") or "")[:400],
        "topics": list(route.get("topics") or [])[:12],
        "executor": str(route.get("executor") or route.get("tool_name") or ""),
        "source": str(route.get("source") or ""),
        "tool_name": str(route.get("tool_name") or route.get("executor") or ""),
        "executor_args_template": dict(route_payload.get("executor_args_template") or {}),
        "locked_args": dict(route_payload.get("locked_args") or {}),
        "argument_schema": compact_schema,
        "execution_argument_schema": dict(route_payload.get("execution_argument_schema") or {}),
        "argument_hints": dict(route_payload.get("argument_hints") or {}),
        "evidence_policy": dict(route.get("evidence_policy") or {}),
        "fallback_route_ids": list(route.get("fallback_route_ids") or [])[:6],
        "cross_family_fallback_route_ids": list(route.get("cross_family_fallback_route_ids") or [])[:6],
        "fallback_policy": {
            "default_scope": str(fallback_policy.get("default_scope") or "family_local"),
            "family_id": str(fallback_policy.get("family_id") or route.get("family_id") or "other"),
            "same_family_route_ids": list(fallback_policy.get("same_family_route_ids") or route.get("fallback_route_ids") or [])[:6],
            "cross_family_route_ids": list(
                fallback_policy.get("cross_family_route_ids") or route.get("cross_family_fallback_route_ids") or []
            )[:6],
            "allow_cross_family": bool(
                fallback_policy.get("allow_cross_family")
                or route.get("cross_family_fallback_route_ids")
            ),
        },
        "document_selectors": list(route.get("document_selectors") or [])[:8],
        "table_scopes": list(route.get("table_scopes") or [])[:12],
    }


def _selector_family_cards(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    ordered: list[tuple[int, str]] = []
    for route in routes:
        family_id = str(route.get("family_id") or "other")
        family = grouped.get(family_id)
        if family is None:
            family = {
                "family_id": family_id,
                "family_title": str(route.get("family_title") or ROUTE_FAMILY_CARDS.get(family_id, ROUTE_FAMILY_CARDS["other"]).get("title") or family_id),
                "family_summary": str(route.get("family_summary") or ROUTE_FAMILY_CARDS.get(family_id, ROUTE_FAMILY_CARDS["other"]).get("summary") or "")[:240],
                "route_ids": [],
                "leaf_routes": [],
            }
            grouped[family_id] = family
            ordered.append((len(ordered), family_id))
        route_id = str(route.get("route_id") or "")
        family["route_ids"].append(route_id)
        family["leaf_routes"].append(dict(route))
    return [grouped[family_id] for _, family_id in ordered]


def selector_payload_leaf_routes(selector_payload: dict[str, Any]) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    for family in selector_payload.get("families") or []:
        if not isinstance(family, dict):
            continue
        for route in family.get("leaf_routes") or []:
            if isinstance(route, dict):
                routes.append(route)
    return routes


def _group_routes_by_family(routes: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    family_order: list[str] = []
    for route in routes:
        family_id = str(route.get("family_id") or "other")
        if family_id not in grouped:
            grouped[family_id] = []
            family_order.append(family_id)
        grouped[family_id].append(route)
    return grouped, family_order


def _family_first_candidate_routes(
    routes: list[dict[str, Any]],
    *,
    query: str,
    intent_family: str,
    max_routes: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    grouped, catalog_family_order = _group_routes_by_family(routes)
    ranked_routes = _ordered_routes_for_intent(routes, query, intent_family)
    ranked_family_ids: list[str] = []
    for route in ranked_routes:
        family_id = str(route.get("family_id") or "other")
        if family_id not in ranked_family_ids:
            ranked_family_ids.append(family_id)
    for family_id in catalog_family_order:
        if family_id not in ranked_family_ids:
            ranked_family_ids.append(family_id)

    selected_family_ids: list[str] = []
    selected_route_count = 0
    for family_id in ranked_family_ids:
        family_routes = grouped.get(family_id) or []
        if not family_routes:
            continue
        if selected_family_ids and (selected_route_count + len(family_routes)) > max_routes:
            continue
        selected_family_ids.append(family_id)
        selected_route_count += len(family_routes)
        if selected_route_count >= max_routes:
            break

    if not selected_family_ids and ranked_family_ids:
        selected_family_ids = [ranked_family_ids[0]]

    candidates: list[dict[str, Any]] = []
    seen_route_ids: set[str] = set()
    for route in ranked_routes:
        route_id = str(route.get("route_id") or "")
        family_id = str(route.get("family_id") or "other")
        if family_id in selected_family_ids and route_id and route_id not in seen_route_ids:
            seen_route_ids.add(route_id)
            candidates.append(route)
    for family_id in selected_family_ids:
        for route in grouped.get(family_id) or []:
            route_id = str(route.get("route_id") or "")
            if route_id and route_id not in seen_route_ids:
                seen_route_ids.add(route_id)
                candidates.append(route)
    return candidates, selected_family_ids


def build_route_selector_payload(
    query: str,
    *,
    limit: int = SELECTOR_ROUTE_LIMIT,
    sphere_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    catalog = load_routing_index()
    routes = _visible_catalog_routes(catalog)
    explicit_document_request = _is_explicit_document_request(query)
    intent_family = _infer_intent_family(query, explicit_document_request=explicit_document_request)
    max_routes = max(1, min(int(limit or SELECTOR_ROUTE_LIMIT), SELECTOR_ROUTE_LIMIT))
    if len(routes) <= max_routes:
        # Catalog serialization order is not a relevance ranking: preserve the same
        # intent-first ordering that degraded route selection uses.
        candidates = _ordered_routes_for_intent(routes, query, intent_family)
        candidate_mode = "all_visible_ranked_by_intent"
    else:
        candidates, selected_family_ids = _family_first_candidate_routes(
            routes,
            query=query,
            intent_family=intent_family,
            max_routes=max_routes,
        )
        candidate_mode = "family_first_budgeted_by_family"
    compact_routes = [_compact_selector_route_card(route, sphere_context=sphere_context) for route in candidates]
    families = _selector_family_cards(compact_routes)
    return {
        "query": query,
        "intent_family": intent_family,
        "resolved_sphere_context": dict(sphere_context or {}),
        "catalog_version": str(catalog.get("catalog_version") or ""),
        "catalog_origin": str(catalog.get("manifest_origin") or ""),
        "schema_version": int(catalog.get("schema_version") or 0),
        "route_count": int(catalog.get("route_count") or len(routes)),
        "candidate_mode": candidate_mode,
        "candidate_route_ids": [str(route.get("route_id") or "") for route in compact_routes],
        "candidate_family_ids": [str(family.get("family_id") or "") for family in families],
        "families": families,
    }
