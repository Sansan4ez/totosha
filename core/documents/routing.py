"""Unified routing catalog for corp_table, corp_script, and doc_domain routes."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cache import load_parse_cache
from .storage import ensure_document_layout, get_document_paths, iter_live_documents


WORD_RE = re.compile(r"[\wА-Яа-яЁё]+", re.UNICODE)
DOCUMENT_REQUEST_KEYWORDS = (
    "сертификат",
    "паспорт",
    "pdf",
    "документ",
    "wiki",
    "вики",
    "фрагмент",
    "цитат",
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
COMPANY_FACT_KEYWORDS = (
    "контакты",
    "контакт",
    "телефон",
    "email",
    "e-mail",
    "почта",
    "адрес",
    "сайт",
    "официальный сайт",
    "реквизиты",
    "инн",
    "кпп",
    "огрн",
    "о компании",
    "расскажи о компании",
    "год основания",
    "соцсети",
    "сервис",
    "гарантия",
)
CATALOG_LOOKUP_KEYWORDS = (
    "модель",
    "серия",
    "артикул",
    "код",
    "карточка",
    "характеристики",
    "совместимость",
    "крепление",
)
PORTFOLIO_LOOKUP_KEYWORDS = (
    "портфолио",
    "пример проекта",
    "пример объекта",
    "примеры проектов",
    "примеры объектов",
    "из портфолио",
    "какие проекты",
    "покажи проекты",
    "реализация",
)
APPLICATION_RECOMMENDATION_KEYWORDS = (
    "подбери",
    "рекоменд",
    "подходит",
    "подходят",
    "для стадиона",
    "для склада",
    "для аэропорта",
    "для офиса",
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
)
ROUTING_SCHEMA_VERSION = 1
ROUTING_CATALOG_ID = "totosha.unified-routing-catalog"
ROUTING_CATALOG_FILENAME = "catalog.v1.json"
LEGACY_ROUTING_INDEX_FILENAME = "index.json"
MIN_SELECTION_SCORE = 4
SHORTLIST_SIZE = 4


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def _normalize_route_card(route: dict[str, Any], *, origin: str) -> dict[str, Any] | None:
    route_id = str(route.get("route_id") or "").strip()
    if not route_id:
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
    }
    normalized["observability_labels"].setdefault("route_family", route_family)
    normalized["observability_labels"].setdefault("route_kind", route_kind)
    normalized["observability_labels"].setdefault("authority", authority)
    normalized["observability_labels"].setdefault("source", normalized["source"])
    return normalized


def bootstrap_route_cards() -> list[dict[str, Any]]:
    return [
        {
            "route_id": "corp_kb.company_common",
            "route_family": "corp_kb.company_common",
            "route_kind": "corp_table",
            "authority": "primary",
            "title": "Company common knowledge base",
            "summary": "Source-scoped company KB for contacts, website, legal details, address, service, warranty, and general company facts.",
            "topics": ["company", "contacts", "legal", "certification"],
            "keywords": [
                "сайт",
                "адрес",
                "контакты",
                "телефон",
                "email",
                "e-mail",
                "реквизиты",
                "инн",
                "кпп",
                "огрн",
                "гарантия",
                "сервис",
                "о компании",
                "год основания",
                "соцсети",
            ],
            "patterns": [
                "официальный сайт",
                "год основания",
                "общая информация о компании",
                "расскажи о компании",
                "контакты компании",
                "подскажи контакты компании",
                "реквизиты компании",
                "о самой компании",
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
            "route_id": "corp_db.portfolio_by_sphere",
            "route_family": "corp_db.portfolio_by_sphere",
            "route_kind": "corp_script",
            "authority": "secondary",
            "title": "Portfolio by sphere",
            "summary": "Examples of completed projects, portfolio objects, and implementation references by application area.",
            "topics": ["portfolio", "projects"],
            "keywords": [
                "портфолио",
                "проект",
                "объект",
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
            ],
            "patterns": ["пример проекта", "пример объекта", "из портфолио", "портфолио по"],
            "executor": "corp_db_search",
            "executor_args_template": {"kind": "portfolio_by_sphere", "fuzzy": True},
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
        {
            "route_id": "doc_search.document_lookup",
            "route_family": "doc_domain.document_lookup",
            "route_kind": "doc_domain",
            "authority": "secondary",
            "title": "Document lookup and certificates",
            "summary": "Certificates, passports, PDFs, and free-text document facts such as material options or series differences.",
            "topics": ["documents", "certificates"],
            "keywords": [
                "сертификат",
                "пожарный сертификат",
                "ce",
                "pdf",
                "паспорт",
                "документ",
                "закаленное стекло",
                "закалённое стекло",
                "чем отличается",
            ],
            "patterns": [
                "пожарный сертификат",
                "сертификат ce",
                "закаленное стекло",
                "закалённое стекло",
                "чем отличается серия",
            ],
            "executor": "doc_search",
            "executor_args_template": {"top": 5},
        },
    ]


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


def build_document_route_cards() -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for record in iter_live_documents():
        aliases = list(record.get("aliases") or [])
        primary_alias = aliases[0] if aliases else {}
        metadata = primary_alias.get("metadata") if isinstance(primary_alias.get("metadata"), dict) else {}
        routing_metadata = dict(record.get("routing") or {}) if isinstance(record.get("routing"), dict) else {}
        cached = load_parse_cache(record.get("sha256"))
        text = str(cached.get("text") or "") if cached else ""
        summary = str(routing_metadata.get("summary") or metadata.get("summary") or text[:220]).strip()
        title = str(
            routing_metadata.get("title")
            or metadata.get("title")
            or record.get("original_filename")
            or record.get("relative_path")
            or record.get("document_id")
        )
        tags = _string_list(routing_metadata.get("tags") or metadata.get("tags"))
        topics = _string_list(routing_metadata.get("topics")) or tags
        keywords = _string_list(routing_metadata.get("keywords"))
        patterns = _string_list(routing_metadata.get("patterns"))
        document_id = str(record.get("document_id") or "").strip()
        relative_path = str(record.get("relative_path") or record.get("original_filename") or "").strip()
        route_family = str(routing_metadata.get("route_family") or "").strip() or (
            f"doc_domain.{document_id}" if document_id else "doc_domain.live"
        )
        route_id = str(routing_metadata.get("route_id") or "").strip() or (
            route_family if route_family.startswith("doc_search.") else f"doc_search.{document_id}"
        )
        preferred_document_ids = _dedupe(
            [
                document_id,
                relative_path,
                str(record.get("original_filename") or "").strip(),
            ]
        )
        route = _normalize_route_card(
            {
                "route_id": route_id,
                "route_family": route_family,
                "route_kind": "doc_domain",
                "authority": "primary",
                "document_id": document_id,
                "title": title,
                "summary": summary,
                "topics": topics,
                "keywords": _dedupe(
                    keywords + [title, relative_path, str(record.get("original_filename") or "")]
                ),
                "patterns": _dedupe(patterns + [title, relative_path]),
                "generated_keywords": _dedupe(tags + topics + _terms(summary)[:24]),
                "executor": "doc_search",
                "executor_args_template": {"preferred_document_ids": preferred_document_ids},
                "observability_labels": {"document_id": document_id},
            },
            origin="runtime_live_documents",
        )
        if route is not None:
            cards.append(route)
    return cards


def _load_catalog_file(path: Path, *, origin: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    routes_payload = payload if isinstance(payload, list) else payload.get("routes")
    if not isinstance(routes_payload, list):
        return None

    routes: list[dict[str, Any]] = []
    for route in routes_payload:
        if isinstance(route, dict):
            normalized = _normalize_route_card(route, origin=origin)
            if normalized is not None:
                routes.append(normalized)

    return {
        "catalog_id": str(payload.get("catalog_id") or ROUTING_CATALOG_ID) if isinstance(payload, dict) else ROUTING_CATALOG_ID,
        "schema_version": int(payload.get("schema_version") or ROUTING_SCHEMA_VERSION) if isinstance(payload, dict) else ROUTING_SCHEMA_VERSION,
        "catalog_version": str(payload.get("catalog_version") or path.stem) if isinstance(payload, dict) else path.stem,
        "generated_at": str(payload.get("generated_at") or _utcnow()) if isinstance(payload, dict) else _utcnow(),
        "routes": routes,
        "manifest_origin": origin,
        "manifest_path": str(path),
    }


def _merge_catalogs(payloads: list[dict[str, Any]], *, manifest_origin: str) -> dict[str, Any]:
    merged_by_id: dict[str, dict[str, Any]] = {}
    catalog_id = ROUTING_CATALOG_ID
    schema_version = ROUTING_SCHEMA_VERSION
    catalog_version = "bootstrap"
    generated_at = _utcnow()
    manifest_paths: list[str] = []

    for payload in payloads:
        catalog_id = str(payload.get("catalog_id") or catalog_id)
        schema_version = int(payload.get("schema_version") or schema_version)
        catalog_version = str(payload.get("catalog_version") or catalog_version)
        generated_at = str(payload.get("generated_at") or generated_at)
        manifest_path = str(payload.get("manifest_path") or "").strip()
        if manifest_path:
            manifest_paths.append(manifest_path)
        for route in payload.get("routes", []):
            if isinstance(route, dict) and route.get("route_id"):
                merged_by_id[str(route["route_id"])] = dict(route)

    routes = list(merged_by_id.values())
    return {
        "catalog_id": catalog_id,
        "schema_version": schema_version,
        "catalog_version": catalog_version,
        "generated_at": generated_at,
        "route_count": len(routes),
        "routes": routes,
        "manifest_origin": manifest_origin,
        "manifest_paths": manifest_paths,
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
    return {
        "catalog_id": ROUTING_CATALOG_ID,
        "schema_version": ROUTING_SCHEMA_VERSION,
        "catalog_version": "bootstrap-v1",
        "generated_at": _utcnow(),
        "route_count": len(routes),
        "routes": routes,
        "manifest_origin": "bootstrap",
        "manifest_paths": [],
    }


def build_routing_index() -> dict[str, Any]:
    payloads = _repo_catalog_payloads()
    runtime_payload = _merge_catalogs(payloads, manifest_origin="repo_manifest") if payloads else _bootstrap_catalog_payload()
    merged_by_id = {str(route["route_id"]): dict(route) for route in runtime_payload.get("routes", []) if isinstance(route, dict) and route.get("route_id")}
    for route in build_document_route_cards():
        merged_by_id[str(route["route_id"])] = dict(route)

    payload = {
        "catalog_id": ROUTING_CATALOG_ID,
        "schema_version": ROUTING_SCHEMA_VERSION,
        "catalog_version": _utcnow(),
        "generated_at": _utcnow(),
        "route_count": len(merged_by_id),
        "routes": list(merged_by_id.values()),
        "manifest_origin": "runtime_merged",
        "manifest_paths": list(runtime_payload.get("manifest_paths", [])),
    }

    for target in (_runtime_catalog_path(), _legacy_runtime_index_path()):
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def load_routing_index() -> dict[str, Any]:
    runtime_catalog = _load_catalog_file(_runtime_catalog_path(), origin="runtime_merged")
    if runtime_catalog is not None:
        return _merge_catalogs([runtime_catalog], manifest_origin="runtime_merged")

    payloads = _repo_catalog_payloads()
    legacy_runtime = _load_catalog_file(_legacy_runtime_index_path(), origin="runtime_legacy")
    if legacy_runtime is not None:
        payloads.append(legacy_runtime)
    if payloads:
        return _merge_catalogs(payloads, manifest_origin="published")
    return _bootstrap_catalog_payload()


def _is_explicit_document_request(query: str) -> bool:
    query_text = _normalize(query)
    return (
        any(keyword in query_text for keyword in DOCUMENT_REQUEST_KEYWORDS)
        or any(pattern in query_text for pattern in DOCUMENT_LINK_CONTEXT_PATTERNS)
        or any(pattern in query_text for pattern in DOCUMENT_IN_TEXT_PATTERNS)
    )


def _authority_rank(authority: str) -> int:
    return 2 if authority == "primary" else 1


def _route_intent_family(route: dict[str, Any]) -> str:
    route_id = str(route.get("route_id") or "")
    route_family = str(route.get("route_family") or "")
    if route_id.startswith("corp_kb.company_"):
        return "company_fact"
    if route_id == "corp_db.catalog_lookup":
        return "catalog_lookup"
    if route_id == "corp_db.application_recommendation":
        return "application_recommendation"
    if route_id == "corp_db.portfolio_by_sphere":
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
    if _intent_contains(query_text, APPLICATION_RECOMMENDATION_KEYWORDS) or _intent_contains(query_text, ORCHESTRATION_KEYWORDS):
        return "application_recommendation"
    if _intent_contains(query_text, CATALOG_LOOKUP_KEYWORDS):
        return "catalog_lookup"
    if _intent_contains(query_text, COMPANY_FACT_KEYWORDS):
        return "company_fact"
    return "other"


def _kind_rank(route_kind: str, *, explicit_document_request: bool) -> int:
    if explicit_document_request:
        ranks = {"doc_domain": 3, "corp_table": 2, "corp_script": 1}
    else:
        ranks = {"corp_table": 3, "corp_script": 2, "doc_domain": 1}
    return ranks.get(route_kind, 0)


def _intent_bonus(route: dict[str, Any], *, intent_family: str, explicit_document_request: bool) -> tuple[int, str | None]:
    route_intent = _route_intent_family(route)
    route_kind = str(route.get("route_kind") or "")
    if not intent_family or intent_family == "other":
        return (0, None)
    if route_intent == intent_family:
        bonus_by_intent = {
            "company_fact": 14,
            "catalog_lookup": 12,
            "application_recommendation": 16,
            "portfolio_lookup": 14,
            "document_lookup": 18,
        }
        return (bonus_by_intent.get(intent_family, 10), f"intent_match={intent_family}")
    if intent_family == "application_recommendation":
        if route_intent == "portfolio_lookup":
            return (8, "neighbor_intent=portfolio_lookup")
        if route_kind == "doc_domain" and not explicit_document_request:
            return (-12, "application_vs_doc_penalty")
    if intent_family == "portfolio_lookup" and route_intent == "application_recommendation":
        return (6, "neighbor_intent=application_recommendation")
    if intent_family == "company_fact" and route_kind == "doc_domain" and not explicit_document_request:
        return (-8, "company_fact_vs_doc_penalty")
    if intent_family == "catalog_lookup" and route_kind == "doc_domain" and not explicit_document_request:
        return (-6, "catalog_vs_doc_penalty")
    if intent_family == "document_lookup" and route_kind != "doc_domain":
        return (-6, "document_lookup_prefers_doc_domain")
    return (0, None)


def _score_route_card(
    route: dict[str, Any],
    query: str,
    *,
    explicit_document_request: bool,
    intent_family: str,
) -> dict[str, Any]:
    query_text = _normalize(query)
    query_terms = set(_terms(query))
    score = 0
    reasons: list[str] = []
    matched_keywords: list[str] = []
    matched_patterns: list[str] = []

    for pattern in route.get("patterns", []) or []:
        normalized = _normalize(pattern)
        if normalized and normalized in query_text:
            score += 12
            matched_patterns.append(str(pattern))
    if matched_patterns:
        reasons.append(f"pattern:{matched_patterns[0]}")

    for keyword in route.get("keywords", []) or []:
        keyword_terms = [term for term in _terms(keyword) if term in query_terms]
        if keyword_terms:
            score += 3 * len(keyword_terms)
            matched_keywords.extend(keyword_terms)
    if str(route.get("route_kind") or "") == "doc_domain" and (
        explicit_document_request or intent_family == "document_lookup"
    ):
        for keyword in route.get("generated_keywords", []) or []:
            keyword_terms = [term for term in _terms(keyword) if term in query_terms]
            if keyword_terms:
                score += 2 * len(keyword_terms)
                matched_keywords.extend(keyword_terms)
    matched_keywords = _dedupe(matched_keywords)
    if matched_keywords:
        reasons.append(f"keywords:{','.join(matched_keywords[:3])}")

    title = _normalize(route.get("title"))
    if route.get("route_kind") == "doc_domain" and title and title in query_text:
        score += 8
        reasons.append("document_title_match")

    if explicit_document_request and route.get("route_kind") == "doc_domain":
        score += 18
        reasons.append("explicit_document_request")
    elif explicit_document_request and route.get("route_kind") != "doc_domain":
        score -= 6

    if route.get("route_kind") == "corp_script" and any(keyword in query_text for keyword in ORCHESTRATION_KEYWORDS):
        score += 6
        reasons.append("orchestration_signal")

    intent_bonus, intent_reason = _intent_bonus(
        route,
        intent_family=intent_family,
        explicit_document_request=explicit_document_request,
    )
    score += intent_bonus
    if intent_reason:
        reasons.append(intent_reason)

    if route.get("authority") == "primary":
        score += 2
        reasons.append("authority=primary")

    if route.get("route_kind") == "corp_table" and route.get("authority") == "primary" and score > 0:
        score += 1
        reasons.append("authoritative_table_scope")

    selection_reason = "; ".join(reasons[:4]) or "no_match"
    return {
        "route_id": str(route.get("route_id") or ""),
        "route_family": str(route.get("route_family") or ""),
        "route_kind": str(route.get("route_kind") or ""),
        "authority": str(route.get("authority") or ""),
        "score": score,
        "selection_reason": selection_reason,
        "matched_keywords": matched_keywords[:6],
        "matched_patterns": matched_patterns[:4],
        "intent_family": intent_family,
        "route_intent_family": _route_intent_family(route),
        "route": dict(route),
    }


def select_route(query: str, *, explicit_document_request: bool | None = None) -> dict[str, Any]:
    explicit_document_request = _is_explicit_document_request(query) if explicit_document_request is None else bool(explicit_document_request)
    intent_family = _infer_intent_family(query, explicit_document_request=explicit_document_request)
    catalog = load_routing_index()
    scored: list[dict[str, Any]] = []
    for route in catalog.get("routes", []):
        if not isinstance(route, dict):
            continue
        candidate = _score_route_card(
            route,
            query,
            explicit_document_request=explicit_document_request,
            intent_family=intent_family,
        )
        if candidate["score"] > 0:
            scored.append(candidate)

    scored.sort(
        key=lambda item: (
            item["score"],
            _authority_rank(item["authority"]),
            _kind_rank(item["route_kind"], explicit_document_request=explicit_document_request),
            item["route_id"],
        ),
        reverse=True,
    )

    shortlist = scored[:SHORTLIST_SIZE]
    selected = shortlist[0] if shortlist and shortlist[0]["score"] >= MIN_SELECTION_SCORE else None

    def _candidate_payload(item: dict[str, Any]) -> dict[str, Any]:
        route = dict(item["route"])
        route["score"] = int(item["score"])
        route["selection_reason"] = str(item["selection_reason"])
        route["route_kind"] = str(item["route_kind"])
        route["route_family"] = str(item["route_family"])
        route["selected_route_kind"] = str(item["route_kind"])
        route["selected_route_family"] = str(item["route_family"])
        route["intent_family"] = str(item.get("intent_family") or "")
        route["route_intent_family"] = str(item.get("route_intent_family") or "")
        return route

    primary_candidate = _candidate_payload(selected) if selected is not None else None
    secondary_candidates = [
        _candidate_payload(item)
        for item in shortlist[1:]
    ] if selected is not None else []
    selected_route = None
    if primary_candidate is not None:
        selected_route = dict(primary_candidate)
        selected_route["candidate_route_ids"] = [item["route_id"] for item in scored[:8]]
        selected_route["secondary_candidates"] = [
            {
                "route_id": str(item.get("route_id") or ""),
                "score": int(item.get("score") or 0),
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
        "candidate_route_ids": [item["route_id"] for item in scored[:8]],
        "secondary_candidates": [
            {
                "route_id": str(item.get("route_id") or ""),
                "score": int(item.get("score") or 0),
                "route_kind": str(item.get("route_kind") or ""),
                "route_family": str(item.get("route_family") or ""),
                "selection_reason": str(item.get("selection_reason") or ""),
                "intent_family": str(item.get("intent_family") or ""),
                "route_intent_family": str(item.get("route_intent_family") or ""),
            }
            for item in secondary_candidates
        ],
        "selection_reason": str(selected["selection_reason"]) if selected is not None else "",
        "selection_score": int(selected["score"]) if selected is not None else 0,
        "selected_route_kind": str(selected["route_kind"]) if selected is not None else "",
        "selected_route_family": str(selected["route_family"]) if selected is not None else "",
        "catalog_version": str(catalog.get("catalog_version") or ""),
        "catalog_origin": str(catalog.get("manifest_origin") or ""),
        "route_count": int(catalog.get("route_count") or 0),
    }


def select_route_card(query: str, *, explicit_document_request: bool | None = None) -> dict[str, Any] | None:
    return select_route(query, explicit_document_request=explicit_document_request).get("selected")
