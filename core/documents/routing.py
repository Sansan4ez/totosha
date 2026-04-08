"""Route-card index for corp_db and doc_search selection."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cache import load_parse_cache
from .storage import ensure_document_layout, get_document_paths, iter_live_documents


WORD_RE = re.compile(r"[\wА-Яа-яЁё]+", re.UNICODE)


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


def _route_dir() -> Path:
    paths = ensure_document_layout(get_document_paths())
    route_dir = paths.manifests / "routes"
    route_dir.mkdir(parents=True, exist_ok=True)
    return route_dir


def default_corp_db_route_cards() -> list[dict[str, Any]]:
    return [
        {
            "route_id": "doc_search.document_lookup",
            "source": "doc_search",
            "title": "Document lookup and certificates",
            "summary": "Certificates, passports, PDFs, and free-text document facts such as material options or series differences.",
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
            "tool_name": "doc_search",
            "tool_args": {"top": 5},
        },
        {
            "route_id": "corp_db.company_profile",
            "source": "corp_db",
            "title": "Company profile and contacts",
            "summary": "Contacts, website, legal details, address, service, warranty, and general company facts.",
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
            ],
            "tool_name": "corp_db_search",
            "tool_args": {"kind": "hybrid_search", "profile": "kb_search", "entity_types": ["company"]},
        },
        {
            "route_id": "corp_db.portfolio_by_sphere",
            "source": "corp_db",
            "title": "Portfolio by sphere",
            "summary": "Examples of completed projects, portfolio objects, and implementation references by application area.",
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
            "patterns": [
                "пример проекта",
                "пример объекта",
                "из портфолио",
                "портфолио по",
            ],
            "tool_name": "corp_db_search",
            "tool_args": {"kind": "portfolio_by_sphere", "fuzzy": True},
        },
        {
            "route_id": "corp_db.application_recommendation",
            "source": "corp_db",
            "title": "Application recommendation",
            "summary": "Broad recommendation by application area such as stadiums, warehouses, airports, offices, or aggressive environments.",
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
                "апрон",
                "высокие пролеты",
            ],
            "patterns": ["подбери освещение", "какие светильники подойдут", "рекомендация по освещению"],
            "tool_name": "corp_db_search",
            "tool_args": {"kind": "application_recommendation"},
        },
        {
            "route_id": "corp_db.catalog_lookup",
            "source": "corp_db",
            "title": "Lamp catalog lookup",
            "summary": "Exact models, codes, series, categories, and structured catalog lookup.",
            "keywords": [
                "модель",
                "серия",
                "артикул",
                "код",
                "светильник",
                "каталог",
                "характеристики",
                "крепление",
                "совместимость",
            ],
            "patterns": ["точная модель", "карточка светильника", "найди модель"],
            "tool_name": "corp_db_search",
            "tool_args": {"kind": "lamp_exact"},
        },
    ]


def build_document_route_cards() -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for record in iter_live_documents():
        aliases = list(record.get("aliases") or [])
        primary_alias = aliases[0] if aliases else {}
        metadata = primary_alias.get("metadata") if isinstance(primary_alias.get("metadata"), dict) else {}
        cached = load_parse_cache(record.get("sha256"))
        text = str(cached.get("text") or "") if cached else ""
        summary = str(metadata.get("summary") or text[:220]).strip()
        title = str(metadata.get("title") or record.get("original_filename") or record.get("relative_path") or record.get("document_id"))
        tags = [str(tag) for tag in metadata.get("tags", [])] if isinstance(metadata.get("tags"), list) else []
        keywords = _dedupe(
            tags
            + [title, str(record.get("relative_path") or ""), str(record.get("original_filename") or "")]
            + _terms(summary)[:24]
        )
        cards.append(
            {
                "route_id": f"doc_search.{record['document_id']}",
                "source": "doc_search",
                "document_id": record["document_id"],
                "title": title,
                "summary": summary,
                "keywords": keywords,
                "patterns": _dedupe([title, str(record.get("relative_path") or ""), *tags]),
                "tool_name": "doc_search",
                "tool_args": {"preferred_document_ids": [record["document_id"]]},
            }
        )
    return cards


def build_routing_index() -> dict[str, Any]:
    route_dir = _route_dir()
    cards = default_corp_db_route_cards() + build_document_route_cards()
    payload = {
        "generated_at": _utcnow(),
        "route_count": len(cards),
        "routes": cards,
    }
    (route_dir / "index.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def load_routing_index() -> dict[str, Any]:
    index_path = _route_dir() / "index.json"
    default_routes = default_corp_db_route_cards()
    if not index_path.exists():
        payload = {
            "generated_at": _utcnow(),
            "route_count": len(default_routes),
            "routes": default_routes,
        }
        return payload
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    existing_routes = payload.get("routes") if isinstance(payload.get("routes"), list) else []
    merged_by_id: dict[str, dict[str, Any]] = {}
    for card in default_routes:
        if isinstance(card, dict) and card.get("route_id"):
            merged_by_id[str(card["route_id"])] = dict(card)
    for card in existing_routes:
        if isinstance(card, dict) and card.get("route_id"):
            merged_by_id[str(card["route_id"])] = dict(card)
    merged_routes = list(merged_by_id.values())
    payload["routes"] = merged_routes
    payload["route_count"] = len(merged_routes)
    return payload


def select_route_card(query: str) -> dict[str, Any] | None:
    query_text = _normalize(query)
    query_terms = set(_terms(query))
    best: dict[str, Any] | None = None
    best_score = 0
    for card in load_routing_index().get("routes", []):
        if not isinstance(card, dict):
            continue
        score = 0
        for pattern in card.get("patterns", []) or []:
            normalized = _normalize(pattern)
            if normalized and normalized in query_text:
                score += 12
        for keyword in card.get("keywords", []) or []:
            for term in _terms(keyword):
                if term in query_terms:
                    score += 3
        source = str(card.get("source") or "")
        if source == "doc_search" and _normalize(card.get("title")) in query_text:
            score += 8
        if score > best_score:
            best = dict(card)
            best_score = score
    if best is None or best_score < 4:
        return None
    best["score"] = best_score
    return best
