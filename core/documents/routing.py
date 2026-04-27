"""Unified routing catalog for corp_table, corp_script, and doc_domain routes."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
CERTIFICATE_TERMS = (
    "сертификат",
    "сертификаты",
    "сертификац",
    "декларац",
)
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
SERIES_AWARE_ROUTE_IDS = {
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
    "corp_db.lamp_filters",
    "corp_db.category_mountings",
    "corp_db.lamp_mounting_compatibility",
}
ROUTE_ARGUMENT_PROPERTY_ALLOWLISTS = {
    "corp_db.catalog_lookup": {
        "kind",
        "query",
        "name",
        "category",
        "mounting_type",
        "limit",
        "offset",
        "fuzzy",
    },
    "corp_db.sku_lookup": {
        "kind",
        "query",
        "etm",
        "oracl",
        "limit",
        "offset",
    },
    "corp_db.category_lamps": {
        "kind",
        "category",
        "query",
        "limit",
        "offset",
        "fuzzy",
    },
    "corp_db.portfolio_lookup": {
        "kind",
        "query",
        "profile",
        "entity_types",
        "limit",
        "offset",
    },
    "corp_db.portfolio_by_sphere": {
        "kind",
        "sphere",
        "query",
        "fuzzy",
        "limit",
        "offset",
    },
    "corp_db.application_recommendation": {
        "kind",
        "query",
        "limit_categories",
        "limit_lamps",
        "limit_portfolio",
    },
    "corp_db.sphere_curated_categories": {
        "kind",
        "sphere",
        "query",
        "fuzzy",
    },
    "corp_db.sphere_categories": {
        "kind",
        "sphere",
        "query",
        "fuzzy",
    },
    "corp_db.lamp_filters": {
        "kind",
        "query",
        "category",
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
        "fuzzy",
    },
    "corp_db.category_mountings": {
        "kind",
        "category",
        "series",
        "mounting_type",
        "query",
        "fuzzy",
    },
    "corp_db.lamp_mounting_compatibility": {
        "kind",
        "category",
        "series",
        "mounting_type",
        "query",
        "fuzzy",
    },
}
ROUTE_REQUIRED_ARGUMENTS = {
    "corp_db.application_recommendation": {"query"},
    "corp_db.portfolio_lookup": {"query"},
    "corp_db.portfolio_by_sphere": {"sphere"},
    "corp_db.sphere_curated_categories": {"sphere"},
    "corp_db.sphere_categories": {"sphere"},
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


def _required_route_argument_keys(route_id: str, schema: dict[str, Any]) -> list[str]:
    required = set(schema.get("required") or [])
    required.update(ROUTE_REQUIRED_ARGUMENTS.get(route_id, set()))
    return [key for key in schema.get("properties", {}) if key in required]


def _apply_runtime_argument_overrides(route: dict[str, Any], *, sphere_context: dict[str, Any] | None = None) -> None:
    route_id = str(route.get("route_id") or "").strip()
    executor = str(route.get("executor") or route.get("tool_name") or "").strip()
    executor_args_template = dict(route.get("executor_args_template") or {})
    route["argument_schema"] = default_argument_schema(
        executor=executor,
        executor_args_template=executor_args_template,
        locked_args=executor_args_template,
    )
    route["argument_schema"]["properties"] = _retain_argument_properties(
        route_id,
        dict(route["argument_schema"].get("properties") or {}),
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
    route["argument_schema"]["required"] = _required_route_argument_keys(route_id, route["argument_schema"])
    hints = dict(route.get("argument_hints") or {})
    if route_id in SPHERE_AWARE_ROUTE_IDS and "sphere" in route["argument_schema"]["properties"]:
        hints["sphere"] = "Choose one canonical application sphere when the user clearly asks by segment or environment."
    if route_id in MOUNTING_TYPE_AWARE_ROUTE_IDS and "mounting_type" in route["argument_schema"]["properties"]:
        hints["mounting_type"] = "Choose one canonical mounting type when the user explicitly names a mounting option."
    if route_id in SERIES_AWARE_ROUTE_IDS:
        hints["series"] = "Choose one canonical business series when the user asks at model-family level."
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

    normalized = {
        "route_id": route_id,
        "route_family": route_family,
        "route_kind": route_kind,
        "authority": authority,
        "title": str(route.get("title") or route_id).strip(),
        "summary": str(route.get("summary") or "").strip(),
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
    normalized["observability_labels"].setdefault("route_kind", route_kind)
    normalized["observability_labels"].setdefault("authority", authority)
    normalized["observability_labels"].setdefault("source", normalized["source"])
    for field_name in ROUTE_CONTRACT_FIELDS:
        if field_name in route:
            normalized[field_name] = route[field_name]
    for field_name in ("hidden", "selector_visible"):
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
    routes = [
        {
            "route_id": "corp_kb.company_common",
            "route_family": "corp_kb.company_common",
            "route_kind": "corp_table",
            "authority": "primary",
            "title": "Company common knowledge base",
            "summary": "Source-scoped company KB for contacts, website, legal details, address, service, warranty, canonical series overviews, and general company facts.",
            "topics": ["company", "contacts", "legal", "certification", "quality", "series"],
            "keywords": [
                "сайт",
                "адрес",
                "контакты",
                "телефон",
                "email",
                "e-mail",
                "сертификат",
                "сертификаты",
                "качество",
                "комплектующие",
                "реквизиты",
                "инн",
                "кпп",
                "огрн",
                "гарантия",
                "сервис",
                "о компании",
                "год основания",
                "соцсети",
                "сертификация",
                "декларации",
                "экспертиза",
                "надежность",
                "серии светильников",
                "линейки светильников",
                "описание серий",
                "все серии",
            ],
            "patterns": [
                "какие есть сертификаты",
                "какие используются комплектующие",
                "как контролируется качество",
                "официальный сайт",
                "год основания",
                "общая информация о компании",
                "расскажи о компании",
                "контакты компании",
                "подскажи контакты компании",
                "реквизиты компании",
                "о самой компании",
                "какие сертификаты",
                "какая сертификация",
                "какие комплектующие",
                "какие у вас есть серии светильников",
                "в общей базе есть описание всех серий",
                "какие серии доступны",
            ],
            "executor": "corp_db_search",
            "executor_args_template": {
                "kind": "hybrid_search",
                "profile": "kb_route_lookup",
                "knowledge_route_id": "corp_kb.company_common",
                "source_files": ["common_information_about_company.md"],
            },
            "observability_labels": {"scope": "source_file"},
        },
        {
            "route_id": "corp_kb.luxnet",
            "route_family": "corp_kb.luxnet",
            "route_kind": "corp_table",
            "authority": "primary",
            "title": "Luxnet knowledge base",
            "summary": "Source-scoped Luxnet KB route.",
            "topics": ["luxnet", "product"],
            "keywords": ["luxnet", "люкснет"],
            "patterns": ["что такое luxnet", "что такое люкснет", "расскажи про luxnet"],
            "executor": "corp_db_search",
            "executor_args_template": {
                "kind": "hybrid_search",
                "profile": "kb_route_lookup",
                "knowledge_route_id": "corp_kb.luxnet",
                "source_files": ["about_Luxnet.md"],
            },
            "observability_labels": {"scope": "source_file"},
        },
        {
            "route_id": "corp_kb.lighting_norms",
            "route_family": "corp_kb.lighting_norms",
            "route_kind": "corp_table",
            "authority": "primary",
            "title": "Lighting norms knowledge base",
            "summary": "Source-scoped lighting norms KB route.",
            "topics": ["lighting_norms", "rules", "tables"],
            "keywords": ["нормы освещенности", "нормы освещённости", "освещенность", "освещённость", "нормативы освещения"],
            "patterns": ["какие нормы освещенности", "нормы освещения", "нормативы освещения"],
            "executor": "corp_db_search",
            "executor_args_template": {
                "kind": "hybrid_search",
                "profile": "kb_route_lookup",
                "knowledge_route_id": "corp_kb.lighting_norms",
                "source_files": ["normy_osveschennosty.md"],
            },
            "observability_labels": {"scope": "source_file"},
        },
        {
            "route_id": "corp_db.catalog_lookup",
            "route_family": "corp_db.catalog_lookup",
            "route_kind": "corp_table",
            "authority": "primary",
            "title": "Lamp catalog lookup",
            "summary": "Exact models, codes, series, categories, and structured catalog lookup.",
            "topics": ["catalog", "lamp", "model"],
            "keywords": ["модель", "серия", "артикул", "код", "светильник", "каталог", "характеристики", "крепление", "совместимость"],
            "patterns": ["точная модель", "карточка светильника", "найди модель"],
            "executor": "corp_db_search",
            "executor_args_template": {"kind": "lamp_exact"},
        },
        {
            "route_id": "corp_db.sku_lookup",
            "route_family": "corp_db.sku_lookup",
            "route_kind": "corp_table",
            "authority": "primary",
            "title": "ETM, ORACL, and SKU lookup",
            "summary": "Structured lookup by ETM code, ORACL code, SKU, article, or exact catalog identifier.",
            "topics": ["catalog", "sku", "codes"],
            "keywords": [
                "etm",
                "етм",
                "oracl",
                "оракл",
                "sku",
                "артикул",
                "код",
                "код номенклатуры",
                "найди по коду",
            ],
            "patterns": [
                "найди по etm",
                "найди по етм",
                "найди по oracl",
                "найди по оракл",
                "найди sku",
                "по артикулу",
            ],
            "executor": "corp_db_search",
            "executor_args_template": {"kind": "sku_by_code"},
            "argument_hints": {
                "etm": "Extract the ETM code as a short free string when present.",
                "oracl": "Extract the ORACL code as a short free string when present.",
                "query": "Use the original identifier text when the code system is unclear.",
            },
            "observability_labels": {"scope": "sku_lookup"},
        },
        {
            "route_id": "corp_db.category_lamps",
            "route_family": "corp_db.category_lamps",
            "route_kind": "corp_table",
            "authority": "primary",
            "title": "Lamps by category",
            "summary": (
                "Structured route for category pages and lamp lists. Exact display-category names may resolve "
                "through the category tree to executable leaf category ids before lamp retrieval."
            ),
            "topics": ["catalog", "category", "lamp"],
            "keywords": [
                "категория",
                "категории",
                "линейка",
                "светильники категории",
                "модели в категории",
            ],
            "patterns": [
                "какие светильники в категории",
                "покажи категорию",
                "модели категории",
            ],
            "executor": "corp_db_search",
            "executor_args_template": {"kind": "category_lamps", "fuzzy": True},
            "argument_hints": {
                "category": "Extract the product category name as a free string. Exact display-category names may be expanded to executable leaf categories.",
                "query": "Keep the original category phrase for fuzzy resolution when the input is already a leaf-like catalog category.",
            },
            "observability_labels": {"scope": "category_lamps"},
        },
        {
            "route_id": "corp_db.sphere_curated_categories",
            "route_family": "corp_db.sphere_curated_categories",
            "route_kind": "corp_table",
            "authority": "primary",
            "title": "Curated Categories By Application Sphere",
            "summary": (
                "Structured route for user-facing application questions that returns curated display categories "
                "for a resolved sphere. Use this for sphere-to-category answers; runtime expands family categories "
                "to executable leaf category ids only in downstream search flows."
            ),
            "topics": ["catalog", "sphere", "category", "application"],
            "keywords": [
                "сфера применения",
                "область применения",
                "категории для",
                "для стадиона",
                "для склада",
                "для аэропорта",
            ],
            "patterns": [
                "какие категории подходят для",
                "категории для сферы",
                "светильники для сферы",
            ],
            "executor": "corp_db_search",
            "executor_args_template": {"kind": "sphere_curated_categories", "fuzzy": True},
            "argument_hints": {
                "sphere": "Extract the application sphere as a free string and resolve it to curated display categories.",
                "query": "Use the user wording when the sphere requires fuzzy or alias-based resolution.",
            },
            "observability_labels": {"scope": "sphere_curated_categories"},
        },
        {
            "route_id": "corp_db.sphere_categories",
            "route_family": "corp_db.sphere_categories",
            "route_kind": "corp_table",
            "authority": "secondary",
            "title": "Imported Categories By Application Sphere",
            "summary": (
                "Compatibility route for full imported sphere-category linkage. Prefer the curated sphere route for "
                "user-facing application questions; keep this only for diagnostics or full linkage inspection."
            ),
            "topics": ["catalog", "sphere", "category", "application"],
            "keywords": [
                "сфера применения",
                "область применения",
                "категории для",
                "для стадиона",
                "для склада",
                "для аэропорта",
            ],
            "patterns": [
                "какие категории подходят для",
                "категории для сферы",
                "светильники для сферы",
            ],
            "executor": "corp_db_search",
            "executor_args_template": {"kind": "sphere_categories", "fuzzy": True},
            "argument_hints": {
                "sphere": "Extract the application sphere as a free string when full imported linkage is explicitly needed.",
                "query": "Use the user wording when the sphere requires fuzzy resolution for diagnostic lookup.",
            },
            "observability_labels": {"scope": "sphere_categories"},
            "selector_visible": False,
        },
        {
            "route_id": "corp_db.lamp_filters",
            "route_family": "corp_db.lamp_filters",
            "route_kind": "corp_table",
            "authority": "primary",
            "title": "Lamp structured filters",
            "summary": "Structured catalog filtering by power, flux, CCT, IP, voltage, dimensions, protection class, category, and mounting type.",
            "topics": ["catalog", "filters", "lamp", "mounting_type"],
            "keywords": [
                "мощность",
                "световой поток",
                "цветовая температура",
                "ip",
                "напряжение",
                "габариты",
                "класс защиты",
                "тип крепления",
                "монтаж",
            ],
            "patterns": [
                "подбери по параметрам",
                "светильники с ip",
                "светильники мощностью",
                "светильники с креплением",
            ],
            "executor": "corp_db_search",
            "executor_args_template": {"kind": "lamp_filters", "fuzzy": True},
            "argument_hints": {
                "category": "Extract category name when the user narrows the filter by category.",
                "mounting_type": "Extract mounting type as a free string.",
                "ip": "Extract IP rating like IP65 or 65.",
            },
            "observability_labels": {"scope": "lamp_filters"},
        },
        {
            "route_id": "corp_db.category_mountings",
            "route_family": "corp_db.category_mountings",
            "route_kind": "corp_table",
            "authority": "primary",
            "title": "Category mounting options",
            "summary": "Structured route for mounting types available for a product category.",
            "topics": ["catalog", "category_mounting", "mounting_type", "lamp_mountings"],
            "keywords": [
                "крепления категории",
                "варианты крепления",
                "типы креплений",
                "монтаж",
                "lamp_mountings",
                "mounting_types",
            ],
            "patterns": [
                "какие крепления доступны",
                "какие типы креплений",
                "крепления для категории",
            ],
            "executor": "corp_db_search",
            "executor_args_template": {"kind": "category_mountings", "fuzzy": True},
            "argument_hints": {
                "category": "Extract the product category name.",
                "mounting_type": "Extract the requested mounting type when present.",
            },
            "observability_labels": {"scope": "category_mountings"},
        },
        {
            "route_id": "corp_db.lamp_mounting_compatibility",
            "route_family": "corp_db.lamp_mounting_compatibility",
            "route_kind": "corp_table",
            "authority": "primary",
            "title": "Lamp and mounting compatibility",
            "summary": "Structured route for checking compatibility between lamp categories/models and mounting types.",
            "topics": ["catalog", "compatibility", "lamp_mountings", "mounting_type"],
            "keywords": [
                "совместимость креплений",
                "совместимо с креплением",
                "подходит крепление",
                "крепление подходит",
                "lamp_mountings",
            ],
            "patterns": [
                "какое крепление подходит",
                "совместимость с креплением",
                "подходит ли крепление",
            ],
            "executor": "corp_db_search",
            "executor_args_template": {"kind": "category_mountings", "fuzzy": True},
            "argument_hints": {
                "category": "Extract category/model family when available.",
                "mounting_type": "Extract mounting type as a free string.",
                "query": "Keep the compatibility wording for fuzzy resolution.",
            },
            "observability_labels": {"scope": "mounting_compatibility"},
        },
        {
            "route_id": "corp_db.portfolio_lookup",
            "route_family": "corp_db.portfolio_lookup",
            "route_kind": "corp_table",
            "authority": "secondary",
            "title": "Portfolio object lookup",
            "summary": (
                "Named portfolio object lookup for concrete customer, object, terminal, warehouse, bridge, "
                "plant, or project names. Use this when the user asks about a specific realized object such "
                "as Белый Раст rather than a broad project segment."
            ),
            "topics": ["portfolio", "projects", "objects", "references", "realized_projects"],
            "keywords": [
                "портфолио",
                "референсы",
                "кейс",
                "кейсы",
                "логистический центр",
                "терминально-логистический центр",
                "терминал",
                "белый раст",
            ],
            "patterns": [
                "расскажи подробнее про объект",
                "расскажи подробнее про проект",
                "расскажи про объект",
                "покажи проект",
                "терминально-логистический центр",
            ],
            "executor": "corp_db_search",
            "executor_args_template": {
                "kind": "hybrid_search",
                "profile": "entity_resolver",
                "entity_types": ["portfolio", "sphere"],
                "limit": 8,
            },
            "argument_hints": {
                "query": "Use the original user wording with named object/customer/project terms.",
                "entity_types": "Keep locked to portfolio and sphere for portfolio entity resolution.",
            },
            "fallback_route_ids": ["corp_db.portfolio_by_sphere", "corp_db.portfolio_examples_by_lamp"],
            "observability_labels": {"scope": "portfolio_lookup"},
        },
        {
            "route_id": "corp_db.portfolio_by_sphere",
            "route_family": "corp_db.portfolio_by_sphere",
            "route_kind": "corp_script",
            "authority": "primary",
            "title": "Portfolio by sphere",
            "summary": (
                "Preferred broad portfolio route for completed projects, object examples, and implementation "
                "references by sphere, customer segment, or environment."
            ),
            "topics": ["portfolio", "projects"],
            "keywords": [
                "портфолио",
                "проект",
                "объект",
                "реализованные проекты",
                "реализованные объекты",
                "пример проекта",
                "пример объекта",
                "примеры реализации",
                "стадион",
                "аэропорт",
                "перрон",
                "склад",
                "офис",
                "карьер",
                "наружное освещение",
                "ржд",
                "логистический центр",
                "белый раст",
            ],
            "patterns": [
                "какие объекты были реализованы",
                "список объектов",
                "список проектов",
                "реализованные проекты для",
                "пример проекта",
                "пример объекта",
                "из портфолио",
                "портфолио по",
            ],
            "executor": "corp_db_search",
            "executor_args_template": {"kind": "portfolio_by_sphere", "fuzzy": True},
            "argument_hints": {
                "sphere": "Choose the canonical broad sphere or customer segment such as РЖД, складские помещения, логистический центр, стадион.",
                "query": "Keep the original wording when the sphere is ambiguous.",
            },
            "fallback_route_ids": ["corp_db.portfolio_lookup", "corp_db.portfolio_examples_by_lamp"],
        },
        {
            "route_id": "corp_db.portfolio_examples_by_lamp",
            "route_family": "corp_db.portfolio_examples_by_lamp",
            "route_kind": "corp_script",
            "authority": "secondary",
            "title": "Portfolio examples by lamp",
            "summary": "Portfolio examples and completed projects connected to a specific lamp, category, or model family.",
            "topics": ["portfolio", "projects", "lamp", "category"],
            "keywords": [
                "примеры с моделью",
                "проекты с моделью",
                "объекты с моделью",
                "портфолио по светильнику",
                "референсы",
            ],
            "patterns": [
                "где применялась модель",
                "объекты с этим светильником",
                "примеры проектов с",
            ],
            "executor": "corp_db_search",
            "executor_args_template": {"kind": "portfolio_examples_by_lamp", "fuzzy": True},
            "argument_hints": {
                "name": "Extract lamp/model name as a free string.",
                "category": "Extract category when the request is category-level.",
            },
            "observability_labels": {"scope": "portfolio_examples_by_lamp"},
        },
        {
            "route_id": "corp_db.application_recommendation",
            "route_family": "corp_db.application_recommendation",
            "route_kind": "corp_script",
            "authority": "secondary",
            "title": "Application recommendation",
            "summary": "Broad recommendation by application area such as stadiums, warehouses, airports, offices, or aggressive environments.",
            "topics": ["recommendation", "application"],
            "keywords": [
                "стадион",
                "арена",
                "спорткомплекс",
                "карьер",
                "рудник",
                "аэропорт",
                "склад",
                "офис",
                "кабинет",
                "агрессивная среда",
                "агрессивной среды",
                "агрессивной среде",
                "апрон",
                "высокие пролеты",
            ],
            "patterns": [
                "подбери освещение",
                "какие светильники подойдут",
                "какие светильники подходят",
                "подходят для агрессивной среды",
                "рекомендация по освещению",
            ],
            "executor": "corp_db_search",
            "executor_args_template": {"kind": "application_recommendation"},
        },
    ]
    for route in routes:
        _apply_runtime_argument_overrides(route)
    return routes


def default_corp_db_route_cards() -> list[dict[str, Any]]:
    return [
        {
            "route_id": route["route_id"],
            "route_family": route["route_family"],
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
        return _merge_catalogs(payloads, manifest_origin="published")
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
    return (
        any(keyword in query_text for keyword in DOCUMENT_REQUEST_KEYWORDS)
        or certificate_document_context
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


def _route_intent_family(route: dict[str, Any]) -> str:
    route_id = str(route.get("route_id") or "")
    route_family = str(route.get("route_family") or "")
    if route_id.startswith("corp_kb."):
        return "company_fact"
    if route_id in {
        "corp_db.catalog_lookup",
        "corp_db.sku_lookup",
        "corp_db.category_lamps",
        "corp_db.sphere_curated_categories",
        "corp_db.sphere_categories",
        "corp_db.lamp_filters",
        "corp_db.category_mountings",
        "corp_db.lamp_mounting_compatibility",
    }:
        return "catalog_lookup"
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
    if _intent_contains(query_text, PORTFOLIO_LOOKUP_KEYWORDS):
        return "portfolio_lookup"
    if _is_sphere_category_query(query):
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
        if _intent_contains(query_text, ("список", "какие объект", "какие проект", "для ржд", "ржд")):
            return ["corp_db.portfolio_by_sphere", "corp_db.portfolio_lookup", "corp_db.portfolio_examples_by_lamp"]
        return ["corp_db.portfolio_lookup", "corp_db.portfolio_by_sphere", "corp_db.portfolio_examples_by_lamp"]
    if intent_family == "application_recommendation":
        return ["corp_db.application_recommendation", "corp_db.portfolio_lookup", "corp_db.portfolio_by_sphere"]
    if intent_family == "document_lookup":
        return []
    if intent_family == "catalog_lookup":
        if _is_broad_series_query(query):
            return ["corp_kb.company_common", "corp_db.catalog_lookup", "corp_db.category_lamps", "corp_db.sphere_curated_categories"]
        if _is_sphere_category_query(query):
            return ["corp_db.sphere_curated_categories", "corp_db.category_lamps", "corp_db.catalog_lookup", "corp_db.category_mountings"]
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
        return _matching_document_routes(routes, query)
    return _ordered_routes_for_intent(routes, query, intent_family)


def _candidate_payload(route: dict[str, Any], *, intent_family: str, selection_reason: str) -> dict[str, Any]:
    payload = dict(route)
    payload["selection_reason"] = selection_reason
    payload["route_kind"] = str(route.get("route_kind") or "")
    payload["route_family"] = str(route.get("route_family") or "")
    payload["selected_route_kind"] = str(route.get("route_kind") or "")
    payload["selected_route_family"] = str(route.get("route_family") or "")
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
                "selection_reason": str(item.get("selection_reason") or ""),
                "intent_family": str(item.get("intent_family") or ""),
                "route_intent_family": str(item.get("route_intent_family") or ""),
            }
            for item in secondary_candidates
        ],
        "selection_reason": selection_reason,
        "selected_route_kind": str(selected.get("route_kind") or "") if selected is not None else "",
        "selected_route_family": str(selected.get("route_family") or "") if selected is not None else "",
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
                "etm",
                "oracl",
                "category",
                "series",
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
    return {
        "route_id": str(route.get("route_id") or ""),
        "route_family": str(route.get("route_family") or ""),
        "route_kind": str(route.get("route_kind") or ""),
        "authority": str(route.get("authority") or ""),
        "title": str(route.get("title") or ""),
        "summary": str(route.get("summary") or "")[:500],
        "topics": list(route.get("topics") or [])[:12],
        "keywords": list(route.get("keywords") or [])[:16],
        "patterns": list(route.get("patterns") or [])[:8],
        "executor": str(route.get("executor") or route.get("tool_name") or ""),
        "source": str(route.get("source") or ""),
        "tool_name": str(route.get("tool_name") or route.get("executor") or ""),
        "executor_args_template": dict(route_payload.get("executor_args_template") or {}),
        "locked_args": dict(route_payload.get("locked_args") or {}),
        "argument_schema": compact_schema,
        "argument_hints": dict(route_payload.get("argument_hints") or {}),
        "evidence_policy": dict(route.get("evidence_policy") or {}),
        "fallback_route_ids": list(route.get("fallback_route_ids") or [])[:6],
        "document_selectors": list(route.get("document_selectors") or [])[:8],
        "table_scopes": list(route.get("table_scopes") or [])[:12],
    }


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
        candidates = list(routes)
        candidate_mode = "all_visible"
    else:
        candidates = _ordered_routes_for_intent(routes, query, intent_family)[:max_routes]
        candidate_mode = "intent_then_catalog_order"
    return {
        "query": query,
        "resolved_sphere_context": dict(sphere_context or {}),
        "catalog_version": str(catalog.get("catalog_version") or ""),
        "catalog_origin": str(catalog.get("manifest_origin") or ""),
        "schema_version": int(catalog.get("schema_version") or 0),
        "route_count": int(catalog.get("route_count") or len(routes)),
        "candidate_mode": candidate_mode,
        "candidate_route_ids": [str(route.get("route_id") or "") for route in candidates],
        "routes": [_compact_selector_route_card(route, sphere_context=sphere_context) for route in candidates],
    }
