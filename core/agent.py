"""ReAct Agent implementation"""

import asyncio
import os
import json
import re
import aiohttp
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from typing import Optional, Any
from pathlib import Path

from config import CONFIG, get_model, get_temperature, get_max_iterations
from documents.argument_catalogs import canonical_sphere_names, curated_category_names_for_sphere
from documents.route_schema import validate_selector_output
from documents.routing import build_route_selector_payload, select_route
from documents.routing_policy import (
    APPLICATION_RECOMMENDATION_KEYWORDS,
    COMPANY_COMMON_FACET_KEYWORDS,
    COMPANY_FACT_KEYWORDS,
    KB_ROUTE_SPECS,
    company_common_topic_facets as _company_common_topic_facets,
    company_fact_intent_type as _company_fact_intent_type,
    contact_doc_search_query as _contact_doc_search_query,
    dedupe_strings as _dedupe_strings,
    expand_company_fact_query as _expand_company_fact_query,
    is_application_recommendation_intent as _is_application_recommendation_intent,
    is_company_fact_intent as _is_company_fact_intent,
    is_document_lookup_intent as _is_document_lookup_intent,
    is_portfolio_lookup_intent as _is_portfolio_lookup_intent,
    lighting_norms_topic_facets as _lighting_norms_topic_facets,
    normalize_routing_text as _normalize_routing_text,
    rewrite_authoritative_kb_search_args as _rewrite_authoritative_kb_search_args,
    rewrite_company_fact_search_args as _rewrite_company_fact_search_args,
    routing_message_text as _routing_message_text,
    routing_query_text as _routing_query_text,
    text_has_any as _text_has_any,
)
from logger import agent_logger, log_agent_step
from observability import (
    REQUEST_ID as OBS_REQUEST_ID,
    inject_trace_context,
    record_span_event,
    update_correlation_context,
)
try:
    from observability import observe_context_trim
except Exception:
    def observe_context_trim(**kwargs):
        return None
from run_meta import run_meta_append_artifact, run_meta_get, run_meta_update_llm
from tool_output_policy import (
    EXECUTION_MODE_RUNTIME,
    allows_deterministic_primary_finalization,
    get_bench_payload_format,
    get_runtime_payload_format,
    normalize_execution_mode,
)
from tools import execute_tool, filter_tools_for_session
from models import ToolContext, ToolResult
from opentelemetry import trace
from session_manager import Session, SessionManager

# Cache for tool definitions
_tools_cache = None
_tools_cache_time = 0
TOOLS_CACHE_TTL = 60  # seconds

# Cache for userbot availability
_userbot_available_cache = None
_userbot_check_time = 0
USERBOT_CHECK_TTL = 30  # seconds


@dataclass
class ContextBudgetResult:
    messages: list[dict[str, Any]]
    pre_chars: int
    post_chars: int
    removed_messages: int = 0
    truncated_messages: int = 0
    hard_stop: bool = False
    reason: str = ""

EXPLICIT_WIKI_KEYWORDS = (
    "wiki", "вики", "согласно wiki", "согласно вики", "найди в wiki", "найди в вики",
    "в wiki", "в вики", "процит", "цитат", "покажи фрагмент", "фрагмент", "документ",
    "из документа", "по документам", "в документе", "найди в документ", "doc search",
)

URL_RE = re.compile(r"https?://[^\s)>\]]+")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\+?\d[\d\-\(\)\s]{8,}\d")
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

CORP_DOCS_ROOT = "/data/corp_docs"

# Google tokens (admin-only, configured via Admin UI)
GOOGLE_TOKENS_FILE = "/data/google_tokens.json"
GOOGLE_MCP_CREDS_DIR = "/data/google_creds"


def get_google_email() -> Optional[str]:
    """Get authorized Google email (admin-only, single account per instance).
    
    Lookup order:
    1. google_tokens.json (saved by Admin UI)
    2. Scan google_creds/ for any .json file
    """
    try:
        if os.path.exists(GOOGLE_TOKENS_FILE):
            with open(GOOGLE_TOKENS_FILE) as f:
                tokens = json.load(f)
                email = tokens.get("email")
                if email:
                    return email
    except:
        pass
    
    # Fallback: scan google_creds/
    try:
        if os.path.exists(GOOGLE_MCP_CREDS_DIR):
            for fname in os.listdir(GOOGLE_MCP_CREDS_DIR):
                if fname.endswith(".json"):
                    return fname[:-5]  # "user@gmail.com.json" -> "user@gmail.com"
    except:
        pass
    
    return None


def _is_explicit_wiki_request(message: str) -> bool:
    return _text_has_any(_routing_message_text(message), EXPLICIT_WIKI_KEYWORDS)


def _format_route_candidate_for_prompt(candidate: dict[str, Any] | None) -> str:
    if not isinstance(candidate, dict) or not candidate:
        return ""
    return (
        f"route_id={candidate.get('route_id') or ''} "
        f"route_kind={candidate.get('selected_route_kind') or candidate.get('route_kind') or ''} "
        f"tool={candidate.get('tool_name') or ''} "
        f"reason={candidate.get('selection_reason') or ''} "
        f"tool_args={json.dumps(candidate.get('tool_args') or {}, ensure_ascii=False)}"
    )


def _parse_json_object(raw_text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_text or "")
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _document_identifier(args: dict[str, Any] | None, tool_output: str = "") -> str:
    preferred_document_ids = (args or {}).get("preferred_document_ids")
    if isinstance(preferred_document_ids, list):
        for item in preferred_document_ids:
            value = str(item or "").strip()
            if value:
                return value
    elif isinstance(preferred_document_ids, str) and preferred_document_ids.strip():
        return preferred_document_ids.strip()

    payload = _parse_json_object(tool_output)
    results = payload.get("results")
    if isinstance(results, list):
        for row in results:
            if not isinstance(row, dict):
                continue
            for key in ("document_id", "relative_path", "path", "document_title"):
                value = str(row.get(key) or "").strip()
                if value:
                    return value
    return ""


def _company_fact_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("results")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _collect_row_texts(rows: list[dict[str, Any]]) -> list[str]:
    texts: list[str] = []
    for row in rows:
        for key in ("heading", "title", "document_title", "content", "preview", "snippet", "value", "source_file"):
            value = str(row.get(key) or "").strip()
            if value:
                texts.append(value)
    return texts


def _collect_row_heading_texts(rows: list[dict[str, Any]]) -> list[str]:
    texts: list[str] = []
    for row in rows:
        for key in ("heading", "title"):
            value = str(row.get(key) or "").strip()
            if value:
                texts.append(value)
    return texts


def _collect_preview_texts(payload: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for row in _company_fact_rows(payload):
        preview = str(row.get("content") or row.get("preview") or row.get("snippet") or row.get("value") or "").strip()
        if preview:
            texts.append(preview)
    return texts


def _texts_contain_any(texts: list[str], keywords: tuple[str, ...]) -> bool:
    normalized_texts = [_normalize_routing_text(text) for text in texts if str(text or "").strip()]
    return any(_text_has_any(text, keywords) for text in normalized_texts)


def _extract_matching_text(texts: list[str], keywords: tuple[str, ...]) -> str:
    for text in texts:
        normalized = _normalize_routing_text(text)
        if _text_has_any(normalized, keywords):
            return str(text).strip()
    return ""


def _extract_address_text(texts: list[str]) -> str:
    for text in texts:
        match = re.search(r"адрес:\s*([^\\n]+?)(?:(?:телефон|e-mail|email|офис в|сайт):|$)", str(text), flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" ,.;")
    return _extract_matching_text(
        texts,
        ("челябинск", "ул.", "улиц", "чайковского", "д.", "дом", "обл", "офис", "адрес"),
    )


def _extract_social_text(texts: list[str]) -> str:
    return _extract_matching_text(texts, ("t.me/", "telegram", "youtube", "youtu", "vk.com", "вконтакте", "соцсет"))


def _extract_requisites_text(texts: list[str]) -> str:
    return _extract_matching_text(texts, ("инн", "кпп", "огрн", "реквизит"))


def _company_fact_payload_is_relevant(payload: dict[str, Any], message: str) -> bool:
    if payload.get("status") != "success":
        return False

    rows = _company_fact_rows(payload)
    if not rows:
        return False

    subtype = _company_fact_intent_type(message)
    texts = _collect_row_texts(rows)
    website = _extract_first_match(URL_RE, texts)
    email = _extract_first_match(EMAIL_RE, texts)
    phone = _extract_first_match(PHONE_RE, texts)
    year = _extract_first_match(YEAR_RE, texts)
    address = _extract_address_text(texts)
    socials = _extract_social_text(texts)
    requisites = _extract_requisites_text(texts)

    if subtype == "website":
        return bool(website)
    if subtype == "year_founded":
        return bool(year)
    if subtype == "address":
        return bool(address) or _texts_contain_any(texts, ("контактная информация", "адрес", "офис"))
    if subtype == "contacts":
        return bool(phone or email or website or address) or _texts_contain_any(texts, ("контактная информация", "контакты"))
    if subtype == "requisites":
        return bool(requisites) or _texts_contain_any(texts, ("реквизиты",))
    if subtype == "socials":
        return bool(socials)
    if subtype == "certification":
        return _texts_contain_any(texts, COMPANY_COMMON_FACET_KEYWORDS["certification"])
    if subtype == "quality":
        return _texts_contain_any(texts, COMPANY_COMMON_FACET_KEYWORDS["quality"])
    return _texts_contain_any(_collect_row_heading_texts(rows), ("о компании", "наш профиль", "о заводе", "об организации"))


def _is_successful_company_fact_kb_search(args: dict, tool_output: str, message: str) -> bool:
    if str(args.get("kind") or "") != "hybrid_search":
        return False
    if str(args.get("profile") or "") not in {"kb_search", "kb_route_lookup"}:
        return False

    payload = _parse_json_object(tool_output)
    entity_types = args.get("entity_types") or []
    if not (
        (isinstance(entity_types, list) and any(str(item).lower() == "company" for item in entity_types))
        or str(args.get("knowledge_route_id") or "") == "corp_kb.company_common"
        or _is_company_fact_intent(message)
        or _text_has_any(_normalize_routing_text(args.get("query")), COMPANY_FACT_KEYWORDS)
    ):
        return False
    return _company_fact_payload_is_relevant(payload, message)


def _payload_matches_kb_route_scope(payload: dict[str, Any], source_files: list[str]) -> bool:
    if payload.get("status") != "success":
        return False
    expected = {str(item) for item in source_files if str(item).strip()}
    if not expected:
        return False
    for row in _company_fact_rows(payload):
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        source_file = str(metadata.get("source_file") or row.get("source_file") or "").strip()
        if source_file in expected:
            return True
    return False


def _authoritative_kb_evidence_status(args: dict[str, Any], tool_result: ToolResult, message: str, routing_state: dict[str, Any]) -> str:
    if not tool_result.success:
        return "error"
    payload = _parse_json_object(tool_result.output or "")
    if payload.get("status") == "empty":
        return "empty"
    knowledge_route_id = str(args.get("knowledge_route_id") or routing_state.get("knowledge_route_id") or "")
    if knowledge_route_id == "corp_kb.company_common":
        return "sufficient" if _company_fact_payload_is_relevant(payload, message) else "weak"
    source_files = routing_state.get("source_file_scope")
    if isinstance(source_files, list) and _payload_matches_kb_route_scope(payload, source_files):
        return "sufficient"
    return "weak"


def _is_successful_application_recommendation(args: dict, tool_output: str, message: str) -> bool:
    if str(args.get("kind") or "") != "application_recommendation":
        return False
    payload = _parse_json_object(tool_output)
    status = str(payload.get("status") or "")
    if status not in {"success", "needs_clarification"}:
        return False
    return True


def _is_successful_portfolio_by_sphere(args: dict, tool_output: str, message: str) -> bool:
    kind = str(args.get("kind") or "")
    if kind != "portfolio_by_sphere":
        return False
    payload = _parse_json_object(tool_output)
    if payload.get("status") != "success":
        return False
    results = payload.get("results")
    return isinstance(results, list) and len(results) > 0


def _is_successful_document_lookup(name: str, args: dict, tool_output: str, message: str) -> bool:
    if name != "doc_search":
        return False
    if not _is_document_lookup_intent(message) and not _is_explicit_wiki_request(message):
        return False
    payload = _parse_json_object(tool_output)
    if payload.get("status") != "success":
        return False
    results = payload.get("results")
    return (
        isinstance(results, list)
        and len(results) > 0
        and _doc_search_payload_matches_expected_document(payload, args=args)
    )


def _is_wiki_tool_attempt(name: str, args: dict) -> bool:
    if name == "doc_search":
        return True
    if name in {"list_directory", "read_file", "search_text"}:
        path = _normalize_routing_text(args.get("path"))
        return CORP_DOCS_ROOT in path
    if name == "search_files":
        pattern = _normalize_routing_text(args.get("pattern"))
        path = _normalize_routing_text(args.get("path"))
        return CORP_DOCS_ROOT in pattern or CORP_DOCS_ROOT in path
    if name == "run_command":
        command = _normalize_routing_text(args.get("command"))
        return "/data/corp_docs" in command or "lit parse" in command
    return False


def _is_skill_or_doc_browse_attempt(name: str, args: dict) -> bool:
    if name not in {"list_directory", "read_file", "search_text", "search_files", "run_command"}:
        return False
    joined = " ".join(
        _normalize_routing_text(args.get(key))
        for key in ("path", "pattern", "command")
    )
    return "/data/skills" in joined or "/data/corp_docs" in joined


def _is_application_fallback_attempt(name: str, args: dict) -> bool:
    if _is_wiki_tool_attempt(name, args):
        return True
    if name != "corp_db_search":
        return False
    kind = str(args.get("kind") or "")
    return kind in {"hybrid_search", "category_lamps", "sphere_curated_categories", "sphere_categories", "portfolio_by_sphere", "lamp_filters"}


def _is_portfolio_fallback_attempt(name: str, args: dict) -> bool:
    if _is_wiki_tool_attempt(name, args):
        return True
    if name != "corp_db_search":
        return False
    kind = str(args.get("kind") or "")
    return kind in {
        "hybrid_search",
        "application_recommendation",
        "category_lamps",
        "sphere_curated_categories",
        "sphere_categories",
        "portfolio_by_sphere",
    }


def _is_document_fallback_attempt(name: str, args: dict) -> bool:
    if name == "corp_db_search":
        return True
    return False


def _is_retrieval_tool_attempt(name: str, args: dict) -> bool:
    if name == "corp_db_search":
        return True
    return _is_wiki_tool_attempt(name, args)


def _is_doc_domain_route(state: dict[str, Any]) -> bool:
    if str(state.get("selected_route_kind") or "") == "doc_domain":
        return True
    if str(state.get("route_source") or "") == "doc_search":
        return True
    return str(state.get("intent") or "") == "document_lookup"


def _has_authoritative_kb_route(state: dict[str, Any]) -> bool:
    return bool(state.get("knowledge_route_id"))


def _doc_search_result_identifiers(row: dict[str, Any]) -> list[str]:
    identifiers: list[str] = []
    for key in ("document_id", "relative_path", "path", "document_title", "title"):
        value = str(row.get(key) or "").strip()
        if value:
            identifiers.append(value)
    return identifiers


def _doc_search_expected_document_ids(args: dict[str, Any] | None = None, state: dict[str, Any] | None = None) -> list[str]:
    expected: list[str] = []
    document_id = str((state or {}).get("document_id") or "").strip()
    if document_id:
        expected.append(document_id)
    preferred = (args or {}).get("preferred_document_ids")
    if isinstance(preferred, list):
        expected.extend(str(item or "").strip() for item in preferred)
    elif isinstance(preferred, str):
        expected.append(preferred.strip())
    return _dedupe_strings([item for item in expected if item])


def _doc_search_payload_matches_expected_document(
    payload: dict[str, Any],
    *,
    args: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
) -> bool:
    expected = [_normalize_routing_text(item) for item in _doc_search_expected_document_ids(args, state)]
    if not expected:
        return True
    results = payload.get("results")
    if not isinstance(results, list):
        return False
    for row in results:
        if not isinstance(row, dict):
            continue
        identifiers = [_normalize_routing_text(item) for item in _doc_search_result_identifiers(row)]
        for expected_id in expected:
            if any(expected_id and (expected_id in identifier or identifier in expected_id) for identifier in identifiers):
                return True
    return False


def _doc_domain_evidence_status(
    tool_result: ToolResult,
    *,
    args: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
) -> str:
    if not tool_result.success:
        return "error"
    payload = _parse_json_object(tool_result.output or "")
    if payload.get("status") == "empty":
        return "empty"
    results = payload.get("results")
    if payload.get("status") == "success" and isinstance(results, list) and len(results) > 0:
        if not _doc_search_payload_matches_expected_document(payload, args=args, state=state):
            return "weak"
        return "sufficient"
    return "weak"


def _route_evidence_status(
    name: str,
    args: dict[str, Any],
    tool_result: ToolResult,
    message: str,
    state: dict[str, Any],
) -> str:
    if name == "doc_search":
        return _doc_domain_evidence_status(tool_result, args=args, state=state)
    if name != "corp_db_search":
        return "weak"
    if _has_authoritative_kb_route(state):
        return _authoritative_kb_evidence_status(args, tool_result, message, state)
    if not tool_result.success:
        return "error"
    payload = _parse_json_object(tool_result.output or "")
    if payload.get("status") == "empty":
        return "empty"
    if str(args.get("kind") or "") == "hybrid_search" and str(args.get("profile") or "") == "entity_resolver":
        entity_types = args.get("entity_types")
        if isinstance(entity_types, list) and any(str(item) in {"portfolio", "sphere"} for item in entity_types):
            results = payload.get("results")
            if payload.get("status") == "success" and isinstance(results, list) and results:
                return "intermediate"
            return "weak"
    if payload.get("status") == "needs_clarification":
        return "sufficient"
    results = payload.get("results")
    if payload.get("status") == "success" and isinstance(results, list) and results:
        return "sufficient"
    return "weak"


def _route_tool_name(route_hint: dict[str, Any] | None) -> str:
    if not route_hint:
        return ""
    return str(route_hint.get("tool_name") or route_hint.get("executor") or "").strip()


def _route_execution_args(route_hint: dict[str, Any], query: str) -> dict[str, Any]:
    args = dict(route_hint.get("tool_args") or {})
    schema = route_hint.get("argument_schema") if isinstance(route_hint.get("argument_schema"), dict) else {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    if "query" in properties and not args.get("query"):
        args["query"] = query
    return args


def _portfolio_lookup_fallback_call(message: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
    normalized = _routing_message_text(message)
    broad_query = any(
        marker in normalized
        for marker in (
            "какие объекты",
            "какие проекты",
            "реализованные объекты",
            "реализованные проекты",
            "список объектов",
            "список проектов",
            "из портфолио",
            "для ржд",
            "для склада",
            "для промышлен",
            "для спортив",
        )
    )
    if "ржд" in normalized:
        args = {
            "kind": "portfolio_by_sphere",
            "sphere": "РЖД",
            "query": message,
            "fuzzy": True,
            "limit": 10,
        }
        route_id = "corp_db.portfolio_by_sphere"
    elif broad_query:
        args = {
            "kind": "portfolio_by_sphere",
            "sphere": message,
            "query": message,
            "fuzzy": True,
            "limit": 10,
        }
        route_id = "corp_db.portfolio_by_sphere"
    else:
        args = {
            "kind": "hybrid_search",
            "profile": "entity_resolver",
            "entity_types": ["portfolio", "sphere"],
            "query": message,
            "limit": 8,
        }
        route_id = "corp_db.portfolio_lookup"
    route_hint = {
        "route_id": route_id,
        "route_family": route_id,
        "route_kind": "corp_table",
        "tool_name": "corp_db_search",
        "tool_args": dict(args),
    }
    return "corp_db_search", args, route_hint


async def _finalize_with_scoped_evidence(
    *,
    base_messages: list[dict[str, Any]],
    tool_name: str,
    tool_args: dict[str, Any],
    tool_result: ToolResult,
    route_hint: dict[str, Any],
) -> str:
    evidence_payload = {
        "selected_route_id": str(route_hint.get("route_id") or ""),
        "selected_route_kind": str(route_hint.get("route_kind") or ""),
        "tool_name": tool_name,
        "tool_args": tool_args,
        "tool_output": str(tool_result.output or "")[:12000],
    }
    finalizer_messages = list(base_messages)
    finalizer_messages.append(
        {
            "role": "user",
            "content": (
                "Сформулируй финальный ответ пользователю только по этим retrieved evidence. "
                "Если evidence не отвечает на вопрос, скажи что данных недостаточно.\n"
                + json.dumps(evidence_payload, ensure_ascii=False)
            ),
        }
    )
    result = await call_llm(finalizer_messages, [], purpose="finalizer")
    if "error" in result:
        raise RuntimeError(str(result.get("error") or "finalizer LLM error"))
    choices = result.get("choices") or []
    if not choices:
        raise RuntimeError("finalizer returned no choices")
    content = str((choices[0].get("message") or {}).get("content") or "")
    return clean_response(content)


def _selected_company_common_route(route_hint: dict[str, Any] | None, state: dict[str, Any]) -> bool:
    route_id = str((route_hint or {}).get("route_id") or state.get("route_id") or "")
    route_args = (route_hint or {}).get("tool_args") if isinstance((route_hint or {}).get("tool_args"), dict) else {}
    knowledge_route_id = str(
        state.get("knowledge_route_id")
        or route_args.get("knowledge_route_id")
        or ""
    )
    return route_id == "corp_kb.company_common" or knowledge_route_id == "corp_kb.company_common"


async def _try_controlled_portfolio_fallback(
    *,
    base_messages: list[dict[str, Any]],
    message: str,
    route_hint: dict[str, Any] | None,
    routing_state: dict[str, Any],
    tool_ctx: ToolContext,
    evidence_status: str,
) -> str:
    if evidence_status not in {"empty", "weak", "intermediate"}:
        return ""
    if not _is_portfolio_lookup_intent(message):
        return ""
    route_args = dict((route_hint or {}).get("tool_args") or {})
    selected_route_id = str((route_hint or {}).get("route_id") or routing_state.get("route_id") or "")
    if str(route_args.get("kind") or "") == "portfolio_by_sphere" or selected_route_id == "corp_db.portfolio_by_sphere":
        return _portfolio_bounded_failure_response(route_args, message)

    name, args, fallback_route_hint = _portfolio_lookup_fallback_call(message)
    if _is_duplicate_retrieval_attempt(name, args, routing_state):
        return _portfolio_bounded_failure_response(args, message)

    fallback_route_id = str(fallback_route_hint.get("route_id") or "")
    fallback_ids = routing_state.get("retrieval_fallback_route_ids")
    if not isinstance(fallback_ids, list):
        fallback_ids = []
        routing_state["retrieval_fallback_route_ids"] = fallback_ids
    if fallback_route_id and fallback_route_id not in fallback_ids:
        fallback_ids.append(fallback_route_id)

    agent_logger.warning(
        "Weak company KB evidence for portfolio query, executing controlled fallback %s with args=%s",
        fallback_route_id,
        json.dumps(args, ensure_ascii=False),
    )
    _record_retrieval_attempt(name, args, routing_state)
    tool_result = await execute_tool(
        name,
        args,
        tool_ctx,
        tool_call_id="route-selector-portfolio-fallback",
        tool_call_seq=1,
    )
    if tool_result.success:
        bench_artifact = tool_result.metadata.get("bench_artifact") if isinstance(tool_result.metadata, dict) else None
        if isinstance(bench_artifact, dict):
            run_meta_append_artifact(bench_artifact)
        _record_tool_output_contract(name, tool_result, routing_state)

    fallback_status_state = dict(routing_state)
    fallback_status_state["knowledge_route_id"] = ""
    fallback_status = _route_evidence_status(name, args, tool_result, message, fallback_status_state)
    routing_state["retrieval_evidence_status"] = fallback_status
    routing_state["selected_source"] = "corp_db" if tool_result.success else routing_state.get("selected_source", "")
    if fallback_status != "sufficient":
        routing_state["retrieval_phase"] = "open"
        routing_state["retrieval_close_reason"] = ""
        _update_routing_observability(routing_state)
        return _portfolio_bounded_failure_response(args, message)

    routing_state["intent"] = "portfolio_lookup"
    routing_state["route_id"] = fallback_route_id
    routing_state["route_source"] = "corp_db"
    routing_state["retrieval_route_family"] = fallback_route_id
    routing_state["selected_route_kind"] = "corp_table"
    routing_state["knowledge_route_id"] = ""
    routing_state["source_file_scope"] = []
    routing_state["topic_facets"] = []
    routing_state["corp_db_portfolio_success"] = True
    routing_state["retrieval_phase"] = "closed"
    routing_state["retrieval_close_reason"] = "controlled_portfolio_fallback_sufficient"
    routing_state["finalizer_mode"] = "llm"
    _update_routing_observability(routing_state)
    return await _finalize_with_scoped_evidence(
        base_messages=base_messages,
        tool_name=name,
        tool_args=args,
        tool_result=tool_result,
        route_hint=fallback_route_hint,
    )


def _is_authoritative_kb_tool_attempt(name: str, args: dict, state: dict[str, Any]) -> bool:
    if name != "corp_db_search" or not _has_authoritative_kb_route(state):
        return False
    kind = str(args.get("kind") or "hybrid_search")
    if kind and kind != "hybrid_search":
        return False
    requested_route_id = str(args.get("knowledge_route_id") or "")
    if requested_route_id and requested_route_id != str(state.get("knowledge_route_id") or ""):
        return False
    requested_source_files = args.get("source_files")
    expected_source_files = state.get("source_file_scope")
    if isinstance(requested_source_files, list) and isinstance(expected_source_files, list) and requested_source_files:
        return requested_source_files == expected_source_files
    return True


def _raw_browse_error(route_hint: dict[str, Any] | None, attempted_tool: str) -> str:
    route_id = str((route_hint or {}).get("route_id") or "")
    tool_name = str((route_hint or {}).get("tool_name") or "")
    if route_id and tool_name:
        return (
            f"Routing guardrail: raw browse tool `{attempted_tool}` is blocked here. "
            f"Use higher-level retrieval first via `{tool_name}` for route `{route_id}`."
        )
    return (
        f"Routing guardrail: raw browse tool `{attempted_tool}` is blocked here. "
        "Use `corp_db_search` or `doc_search` first instead of direct file or skill browsing."
    )


def _tool_attempt_signature(name: str, args: dict) -> str:
    try:
        normalized_args = json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        normalized_args = repr(args)
    return f"{name}:{normalized_args}"


def _is_duplicate_retrieval_attempt(name: str, args: dict, state: dict[str, Any]) -> bool:
    if not _is_retrieval_tool_attempt(name, args):
        return False
    signatures = state.get("retrieval_attempt_signatures")
    if not isinstance(signatures, list):
        return False
    return _tool_attempt_signature(name, args) in signatures


def _record_retrieval_attempt(name: str, args: dict, state: dict[str, Any]) -> None:
    if not _is_retrieval_tool_attempt(name, args):
        return
    signatures = state.get("retrieval_attempt_signatures")
    if not isinstance(signatures, list):
        signatures = []
        state["retrieval_attempt_signatures"] = signatures
    signature = _tool_attempt_signature(name, args)
    if signature not in signatures:
        signatures.append(signature)


def _duplicate_retrieval_error(attempted_tool: str) -> str:
    return (
        f"Routing guardrail: `{attempted_tool}` with these exact args was already called. "
        "Измени аргументы, выбери другой retrieval tool или дай финальный ответ."
    )


def _has_high_level_retrieval_hint(state: dict[str, Any]) -> bool:
    primary_tool = str(state.get("route_tool_name") or "")
    if primary_tool in {"corp_db_search", "doc_search"}:
        return True
    shortlist = state.get("route_shortlist") or []
    if isinstance(shortlist, list):
        for candidate in shortlist:
            if not isinstance(candidate, dict):
                continue
            if str(candidate.get("tool_name") or "") in {"corp_db_search", "doc_search"}:
                return True
    return str(state.get("intent") or "") in {
        "company_fact",
        "catalog_lookup",
        "application_recommendation",
        "portfolio_lookup",
        "document_lookup",
    }


def _update_routing_observability(state: dict[str, Any], *, blocked_tool: str = "") -> None:
    execution_mode = normalize_execution_mode(state.get("execution_mode"))
    effective_route_id = str(state.get("route_id") or "")
    knowledge_route_id = str(state.get("knowledge_route_id") or "")
    effective_candidate_route_ids = list(state.get("candidate_route_ids") or [])
    if knowledge_route_id:
        effective_route_id = knowledge_route_id
        if knowledge_route_id not in effective_candidate_route_ids:
            effective_candidate_route_ids = [knowledge_route_id, *effective_candidate_route_ids]
    effective_route_family = str(state.get("retrieval_route_family") or effective_route_id)
    meta = run_meta_get()
    if isinstance(meta, dict):
        meta["execution_mode"] = execution_mode
        meta["retrieval_intent"] = str(state.get("intent") or "")
        meta["retrieval_selected_source"] = str(state.get("selected_source") or "unknown")
        meta["retrieval_route_id"] = effective_route_id
        meta["retrieval_route_source"] = str(state.get("route_source") or "")
        meta["retrieval_selected_route_kind"] = str(state.get("selected_route_kind") or "")
        meta["retrieval_candidate_route_ids"] = effective_candidate_route_ids
        meta["retrieval_route_family"] = effective_route_family
        meta["retrieval_phase"] = str(state.get("retrieval_phase") or "")
        meta["retrieval_evidence_status"] = str(state.get("retrieval_evidence_status") or "")
        meta["retrieval_retry_count"] = int(state.get("retrieval_retry_count") or 0)
        meta["retrieval_close_reason"] = str(state.get("retrieval_close_reason") or "")
        meta["retrieval_validated_arg_keys"] = list(state.get("retrieval_validated_arg_keys") or [])
        meta["retrieval_validation_errors"] = list(state.get("retrieval_validation_errors") or [])
        meta["retrieval_fallback_route_ids"] = list(state.get("retrieval_fallback_route_ids") or [])
        meta["route_selector_status"] = str(state.get("route_selector_status") or "")
        meta["route_selector_model"] = str(state.get("route_selector_model") or "")
        meta["route_selector_latency_ms"] = float(state.get("route_selector_latency_ms") or 0.0)
        meta["route_selector_confidence"] = str(state.get("route_selector_confidence") or "")
        meta["route_selector_reason"] = str(state.get("route_selector_reason") or "")
        meta["route_selector_repair_attempted"] = bool(state.get("route_selector_repair_attempted"))
        meta["route_selector_repair_status"] = str(state.get("route_selector_repair_status") or "")
        meta["route_selector_validation_error_code"] = str(state.get("route_selector_validation_error_code") or "")
        meta["route_selector_validation_error"] = str(state.get("route_selector_validation_error") or "")
        meta["routing_catalog_version"] = str(state.get("routing_catalog_version") or "")
        meta["routing_catalog_origin"] = str(state.get("routing_catalog_origin") or "")
        meta["routing_schema_version"] = int(state.get("routing_schema_version") or 0)
        meta["knowledge_route_id"] = str(state.get("knowledge_route_id") or "")
        meta["document_id"] = str(state.get("document_id") or "")
        meta["source_file_scope"] = list(state.get("source_file_scope") or [])
        meta["topic_facets"] = list(state.get("topic_facets") or [])
        meta["finalizer_mode"] = str(state.get("finalizer_mode") or "")
        meta["retrieval_explicit_wiki_request"] = bool(state.get("explicit_wiki_request"))
        meta["routing_guardrail_hits"] = int(state.get("guardrail_activations", 0))
        meta["application_recovery_outcome"] = str(state.get("application_recovery_outcome") or "")
        meta["company_fact_intent_type"] = str(state.get("company_fact_intent_type") or "")
        meta["company_fact_payload_relevant"] = bool(state.get("company_fact_payload_relevant"))
        meta["company_fact_finalizer_mode"] = str(state.get("company_fact_finalizer_mode") or "")
        meta["company_fact_runtime_payload_format"] = str(state.get("company_fact_runtime_payload_format") or "")
        meta["company_fact_bench_payload_format"] = str(state.get("company_fact_bench_payload_format") or "")
        runtime_formats = state.get("tool_runtime_output_formats")
        if isinstance(runtime_formats, dict):
            meta["tool_runtime_output_formats"] = dict(runtime_formats)
        bench_formats = state.get("tool_bench_output_formats")
        if isinstance(bench_formats, dict):
            meta["tool_bench_output_formats"] = dict(bench_formats)
        if blocked_tool:
            meta["routing_guardrail_last_blocked_tool"] = blocked_tool

    update_correlation_context(
        selected_route_id=str(state.get("route_id") or ""),
        selected_route_family=str(state.get("retrieval_route_family") or ""),
        selected_route_kind=str(state.get("selected_route_kind") or ""),
        selected_source=str(state.get("selected_source") or "unknown"),
        knowledge_route_id=str(state.get("knowledge_route_id") or ""),
        document_id=str(state.get("document_id") or ""),
        retrieval_phase=str(state.get("retrieval_phase") or ""),
        retrieval_evidence_status=str(state.get("retrieval_evidence_status") or ""),
        retrieval_close_reason=str(state.get("retrieval_close_reason") or ""),
        application_recovery_outcome=str(state.get("application_recovery_outcome") or ""),
        route_selector_status=str(state.get("route_selector_status") or ""),
        routing_catalog_version=str(state.get("routing_catalog_version") or ""),
        routing_guardrail_hits=int(state.get("guardrail_activations", 0)),
        guardrail_blocked_tool=blocked_tool,
        finalizer_mode=str(state.get("finalizer_mode") or ""),
    )

    span = trace.get_current_span()
    try:
        span.set_attribute("execution_mode", execution_mode)
        span.set_attribute("retrieval.intent", str(state.get("intent") or ""))
        span.set_attribute("retrieval.selected_source", str(state.get("selected_source") or "unknown"))
        span.set_attribute("retrieval.route_id", str(state.get("route_id") or ""))
        span.set_attribute("retrieval.route_source", str(state.get("route_source") or ""))
        span.set_attribute("retrieval.selected_route_kind", str(state.get("selected_route_kind") or ""))
        candidate_route_ids = state.get("candidate_route_ids")
        if isinstance(candidate_route_ids, list):
            span.set_attribute("retrieval.candidate_route_ids", ",".join(str(item) for item in candidate_route_ids))
        span.set_attribute("retrieval.route_family", str(state.get("retrieval_route_family") or ""))
        span.set_attribute("retrieval.phase", str(state.get("retrieval_phase") or ""))
        span.set_attribute("retrieval.evidence_status", str(state.get("retrieval_evidence_status") or ""))
        span.set_attribute("retrieval.retry_count", int(state.get("retrieval_retry_count") or 0))
        span.set_attribute("retrieval.close_reason", str(state.get("retrieval_close_reason") or ""))
        span.set_attribute("application.recovery_outcome", str(state.get("application_recovery_outcome") or ""))
        validated_arg_keys = state.get("retrieval_validated_arg_keys")
        if isinstance(validated_arg_keys, list):
            span.set_attribute("retrieval.validated_arg_keys", ",".join(str(item) for item in validated_arg_keys))
        validation_errors = state.get("retrieval_validation_errors")
        if isinstance(validation_errors, list):
            span.set_attribute("retrieval.validation_errors", " | ".join(str(item) for item in validation_errors)[:500])
        fallback_route_ids = state.get("retrieval_fallback_route_ids")
        if isinstance(fallback_route_ids, list):
            span.set_attribute("retrieval.fallback_route_ids", ",".join(str(item) for item in fallback_route_ids))
        span.set_attribute("route_selector.status", str(state.get("route_selector_status") or ""))
        span.set_attribute("route_selector.model", str(state.get("route_selector_model") or ""))
        span.set_attribute("route_selector.latency_ms", float(state.get("route_selector_latency_ms") or 0.0))
        span.set_attribute("route_selector.confidence", str(state.get("route_selector_confidence") or ""))
        span.set_attribute("route_selector.reason", str(state.get("route_selector_reason") or "")[:500])
        span.set_attribute("route_selector.repair_attempted", bool(state.get("route_selector_repair_attempted")))
        span.set_attribute("route_selector.repair_status", str(state.get("route_selector_repair_status") or ""))
        span.set_attribute("route_selector.validation_error_code", str(state.get("route_selector_validation_error_code") or ""))
        span.set_attribute("route_selector.validation_error", str(state.get("route_selector_validation_error") or "")[:500])
        span.set_attribute("routing.catalog_version", str(state.get("routing_catalog_version") or ""))
        span.set_attribute("routing.catalog_origin", str(state.get("routing_catalog_origin") or ""))
        span.set_attribute("routing.schema_version", int(state.get("routing_schema_version") or 0))
        span.set_attribute("knowledge_route_id", str(state.get("knowledge_route_id") or ""))
        span.set_attribute("document_id", str(state.get("document_id") or ""))
        source_file_scope = state.get("source_file_scope")
        if isinstance(source_file_scope, list):
            span.set_attribute("source_file_scope", ",".join(str(item) for item in source_file_scope))
        topic_facets = state.get("topic_facets")
        if isinstance(topic_facets, list):
            span.set_attribute("topic_facets", ",".join(str(item) for item in topic_facets))
        span.set_attribute("finalizer_mode", str(state.get("finalizer_mode") or ""))
        span.set_attribute("retrieval.explicit_wiki_request", bool(state.get("explicit_wiki_request")))
        span.set_attribute("retrieval.guardrail_hits", int(state.get("guardrail_activations", 0)))
        span.set_attribute("company_fact.intent_type", str(state.get("company_fact_intent_type") or ""))
        span.set_attribute("company_fact.payload_relevant", bool(state.get("company_fact_payload_relevant")))
        span.set_attribute("company_fact.finalizer_mode", str(state.get("company_fact_finalizer_mode") or ""))
        span.set_attribute("company_fact.runtime_payload_format", str(state.get("company_fact_runtime_payload_format") or ""))
        span.set_attribute("company_fact.bench_payload_format", str(state.get("company_fact_bench_payload_format") or ""))
        if blocked_tool:
            span.set_attribute("retrieval.guardrail_last_blocked_tool", blocked_tool)
            event_signature = f"guardrail:{blocked_tool}:{state.get('guardrail_activations', 0)}"
            if state.get("_last_observability_event") != event_signature:
                state["_last_observability_event"] = event_signature
                record_span_event(
                    "retrieval.guardrail_blocked",
                    selected_route_id=str(state.get("route_id") or ""),
                    selected_route_family=str(state.get("retrieval_route_family") or ""),
                    selected_route_kind=str(state.get("selected_route_kind") or ""),
                    selected_source=str(state.get("selected_source") or "unknown"),
                    knowledge_route_id=str(state.get("knowledge_route_id") or ""),
                    document_id=str(state.get("document_id") or ""),
                    guardrail_blocked_tool=blocked_tool,
                    routing_guardrail_hits=int(state.get("guardrail_activations", 0)),
                    retrieval_phase=str(state.get("retrieval_phase") or ""),
                    route_selector_status=str(state.get("route_selector_status") or ""),
                    routing_catalog_version=str(state.get("routing_catalog_version") or ""),
                )
                agent_logger.warning(
                    "Routing event=guardrail_blocked blocked_tool=%s route_id=%s route_family=%s route_kind=%s",
                    blocked_tool,
                    state.get("route_id") or "",
                    state.get("retrieval_route_family") or "",
                    state.get("selected_route_kind") or "",
                )
        elif str(state.get("retrieval_close_reason") or ""):
            event_signature = (
                f"closed:{state.get('retrieval_close_reason') or ''}:{state.get('retrieval_phase') or ''}"
            )
            if state.get("_last_observability_event") != event_signature:
                state["_last_observability_event"] = event_signature
                record_span_event(
                    "retrieval.closed",
                    selected_route_id=str(state.get("route_id") or ""),
                    selected_route_family=str(state.get("retrieval_route_family") or ""),
                    selected_route_kind=str(state.get("selected_route_kind") or ""),
                    selected_source=str(state.get("selected_source") or "unknown"),
                    knowledge_route_id=str(state.get("knowledge_route_id") or ""),
                    document_id=str(state.get("document_id") or ""),
                    retrieval_phase=str(state.get("retrieval_phase") or ""),
                    retrieval_evidence_status=str(state.get("retrieval_evidence_status") or ""),
                    retrieval_close_reason=str(state.get("retrieval_close_reason") or ""),
                    route_selector_status=str(state.get("route_selector_status") or ""),
                    routing_catalog_version=str(state.get("routing_catalog_version") or ""),
                    finalizer_mode=str(state.get("finalizer_mode") or ""),
                )
                agent_logger.info(
                    "Routing event=retrieval_closed reason=%s route_id=%s route_family=%s route_kind=%s",
                    state.get("retrieval_close_reason") or "",
                    state.get("route_id") or "",
                    state.get("retrieval_route_family") or "",
                    state.get("selected_route_kind") or "",
                )
        elif str(state.get("finalizer_mode") or "") == "deterministic_fallback":
            event_signature = f"fallback:{state.get('finalizer_mode') or ''}:{state.get('retrieval_phase') or ''}"
            if state.get("_last_observability_event") != event_signature:
                state["_last_observability_event"] = event_signature
                record_span_event(
                    "retrieval.fallback_finalizer",
                    selected_route_id=str(state.get("route_id") or ""),
                    selected_route_family=str(state.get("retrieval_route_family") or ""),
                    selected_route_kind=str(state.get("selected_route_kind") or ""),
                    selected_source=str(state.get("selected_source") or "unknown"),
                    knowledge_route_id=str(state.get("knowledge_route_id") or ""),
                    document_id=str(state.get("document_id") or ""),
                    finalizer_mode=str(state.get("finalizer_mode") or ""),
                    retrieval_phase=str(state.get("retrieval_phase") or ""),
                    route_selector_status=str(state.get("route_selector_status") or ""),
                    routing_catalog_version=str(state.get("routing_catalog_version") or ""),
                )
                agent_logger.warning(
                    "Routing event=fallback_finalizer mode=%s route_id=%s route_family=%s route_kind=%s",
                    state.get("finalizer_mode") or "",
                    state.get("route_id") or "",
                    state.get("retrieval_route_family") or "",
                    state.get("selected_route_kind") or "",
                )
    except Exception:
        return None


def _record_tool_output_contract(name: str, tool_result: ToolResult, state: dict[str, Any]) -> None:
    metadata = tool_result.metadata if isinstance(tool_result.metadata, dict) else {}
    runtime_payload_format = get_runtime_payload_format(metadata)
    bench_payload_format = get_bench_payload_format(metadata)

    if runtime_payload_format:
        runtime_formats = state.get("tool_runtime_output_formats")
        if not isinstance(runtime_formats, dict):
            runtime_formats = {}
            state["tool_runtime_output_formats"] = runtime_formats
        runtime_formats[name] = runtime_payload_format

    if bench_payload_format:
        bench_formats = state.get("tool_bench_output_formats")
        if not isinstance(bench_formats, dict):
            bench_formats = {}
            state["tool_bench_output_formats"] = bench_formats
        bench_formats[name] = bench_payload_format

    if name == "corp_db_search" and state.get("intent") == "company_fact":
        if runtime_payload_format:
            state["company_fact_runtime_payload_format"] = runtime_payload_format
        if bench_payload_format:
            state["company_fact_bench_payload_format"] = bench_payload_format
        _update_routing_observability(state)


def _looks_like_contact_intent(message: str) -> bool:
    return _company_fact_intent_type(message) == "contacts"


def _extract_first_match(pattern: re.Pattern[str], texts: list[str]) -> str:
    for text in texts:
        match = pattern.search(text)
        if match:
            return match.group(0).rstrip(".,;")
    return ""


def _collect_result_texts(payload: dict[str, Any]) -> list[str]:
    previews = _collect_preview_texts(payload)
    if previews:
        return previews
    rows = _company_fact_rows(payload)
    return _collect_row_texts(rows)


def _preferred_company_fact_texts(payload: dict[str, Any], subtype: str) -> list[str]:
    rows = _company_fact_rows(payload)
    if not rows:
        return []

    heading_keywords: tuple[str, ...] = ()
    heading_priority: dict[str, int] = {}
    if subtype == "about_company":
        heading_keywords = ("о компании", "наш профиль", "о заводе", "об организации")
        heading_priority = {
            "о компании": 0,
            "наш профиль": 1,
            "о заводе": 2,
            "об организации": 3,
        }
    elif subtype in {"contacts", "address"}:
        heading_keywords = ("контактная информация", "контакты")
    elif subtype == "requisites":
        heading_keywords = ("реквизиты",)
    elif subtype == "socials":
        heading_keywords = ("социальные сети",)
    elif subtype == "certification":
        heading_keywords = ("сертифик", "декларац", "экспертиз", "сертификац")
    elif subtype == "quality":
        heading_keywords = ("качеств", "комплектующ", "надежн", "надёжн")

    if heading_keywords:
        preferred_rows = [
            row
            for row in rows
            if _texts_contain_any(_collect_row_heading_texts([row]), heading_keywords)
        ]
        if preferred_rows:
            if heading_priority:
                def _row_priority(row: dict[str, Any]) -> tuple[int, int]:
                    heading_text = _normalize_routing_text(" ".join(_collect_row_heading_texts([row])))
                    for keyword, priority in heading_priority.items():
                        if _text_has_any(heading_text, (keyword,)):
                            return priority, rows.index(row)
                    return len(heading_priority), rows.index(row)

                preferred_rows = sorted(preferred_rows, key=_row_priority)
            preferred_payload = {"results": preferred_rows}
            return _collect_result_texts(preferred_payload)

    return _collect_result_texts(payload)


def _render_company_fact_payload(payload: dict[str, Any], message: str) -> str:
    subtype = _company_fact_intent_type(message)
    texts = _preferred_company_fact_texts(payload, subtype)
    if not texts:
        return ""
    website = _extract_first_match(URL_RE, texts)
    email = _extract_first_match(EMAIL_RE, texts)
    phone = _extract_first_match(PHONE_RE, texts)
    year = _extract_first_match(YEAR_RE, texts)
    address = _extract_address_text(texts)
    socials = _extract_social_text(texts)
    requisites = _extract_requisites_text(texts)

    if subtype == "website" and website:
        return f"Официальный сайт компании: {website}"
    if subtype == "year_founded" and year:
        return f"Компания ЛАДзавод светотехники основана в {year} году."
    if subtype == "address" and address:
        return address
    if subtype == "requisites" and requisites:
        return requisites
    if subtype == "socials" and socials:
        return socials
    if subtype == "contacts":
        lines: list[str] = []
        if phone:
            lines.append(f"Телефон: {phone}")
        if email:
            lines.append(f"Email: {email}")
        if address:
            lines.append(f"Адрес: {address}")
        if website:
            lines.append(f"Сайт: {website}")
        if lines:
            return "\n".join(lines)
        return ""

    snippets = texts[:2]
    lines = [snippets[0]]
    if len(snippets) > 1 and snippets[1] != snippets[0]:
        lines.append(snippets[1])
    if website and all(website not in line for line in lines):
        lines.append(f"Сайт: {website}")
    return "\n".join(lines)


def _render_generic_kb_payload(payload: dict[str, Any]) -> str:
    texts = _collect_result_texts(payload)
    if not texts:
        return ""
    lines: list[str] = []
    for text in texts[:2]:
        snippet = str(text).strip()
        if snippet and snippet not in lines:
            lines.append(snippet)
    return "\n".join(lines)


def _render_document_payload(payload: dict[str, Any]) -> str:
    results = payload.get("results") or []
    if not isinstance(results, list) or not results:
        return ""
    row = results[0] if isinstance(results[0], dict) else {}
    title = str(row.get("document_title") or row.get("title") or row.get("relative_path") or "Документ").strip()
    preview = str(row.get("preview") or row.get("snippet") or "").strip()
    url = _extract_first_match(URL_RE, [preview, str(row.get("url") or "")])
    lines = [f"Нашёл документ: {title}"]
    if url:
        lines.append(url)
    if preview:
        lines.append(preview)
    return "\n".join(lines)


def _render_portfolio_payload(payload: dict[str, Any]) -> str:
    results = payload.get("results") or []
    if not isinstance(results, list) or not results:
        return ""
    lines = ["Нашёл примеры объектов по этой сфере:"]
    for row in results[:3]:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or row.get("sphere_name") or "Объект").strip()
        url = str(row.get("url") or "").strip()
        lines.append(f"- {name}{f': {url}' if url else ''}")
    return "\n".join(lines)


def _render_portfolio_entity_payload(payload: dict[str, Any]) -> str:
    results = payload.get("results") or []
    if not isinstance(results, list) or not results:
        return ""
    lines = ["Нашёл релевантные проекты и объекты:"]
    for row in results[:5]:
        if not isinstance(row, dict):
            continue
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        title = str(row.get("title") or row.get("name") or metadata.get("name") or "Объект").strip()
        url = str(row.get("url") or metadata.get("url") or "").strip()
        sphere = str(metadata.get("sphere_name") or "").strip()
        detail = title
        if sphere and sphere.lower() not in detail.lower():
            detail += f" ({sphere})"
        if url:
            detail += f": {url}"
        lines.append(f"- {detail}")
    return "\n".join(lines)


def _render_application_payload(payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "")
    if status == "needs_clarification":
        return str(payload.get("follow_up_question") or "").strip()
    resolved = payload.get("resolved_application") if isinstance(payload.get("resolved_application"), dict) else {}
    sphere_name = str(resolved.get("sphere_name") or "подходящей сферы").strip()
    lamps = payload.get("recommended_lamps") if isinstance(payload.get("recommended_lamps"), list) else []
    portfolio = payload.get("portfolio_examples") if isinstance(payload.get("portfolio_examples"), list) else []
    lines = [f"Подобрал вариант для сферы: {sphere_name}."]
    if lamps:
        lines.append("Подходящие светильники:")
        for row in lamps[:3]:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "Модель").strip()
            url = str(row.get("url") or "").strip()
            reason = str(row.get("recommendation_reason") or "").strip()
            detail = f"{name}{f' — {reason}' if reason else ''}"
            if url:
                detail += f" ({url})"
            lines.append(f"- {detail}")
    if portfolio:
        row = portfolio[0] if isinstance(portfolio[0], dict) else {}
        name = str(row.get("name") or "пример объекта").strip()
        url = str(row.get("url") or "").strip()
        lines.append(f"Пример объекта: {name}{f' — {url}' if url else ''}")
    follow_up = str(payload.get("follow_up_question") or "").strip()
    if follow_up:
        lines.append(follow_up)
    return "\n".join(lines)


def _render_deterministic_tool_output(name: str, args: dict[str, Any], output: str, message: str) -> str:
    payload = _parse_json_object(output)
    if not payload:
        return ""
    if name == "doc_search":
        return _render_document_payload(payload)
    if name != "corp_db_search":
        return ""
    kind = str(args.get("kind") or payload.get("kind") or "")
    if kind == "hybrid_search":
        knowledge_route_id = str(args.get("knowledge_route_id") or "")
        if str(args.get("profile") or "") == "entity_resolver":
            entity_types = args.get("entity_types")
            if isinstance(entity_types, list) and any(str(item) in {"portfolio", "sphere"} for item in entity_types):
                return _render_portfolio_entity_payload(payload)
        if knowledge_route_id in {"corp_kb.luxnet", "corp_kb.lighting_norms"}:
            return _render_generic_kb_payload(payload)
        return _render_company_fact_payload(payload, message)
    if kind == "application_recommendation":
        return _render_application_payload(payload)
    if kind == "portfolio_by_sphere":
        return _render_portfolio_payload(payload)
    return ""


def _build_deterministic_fallback_call(
    message: str,
    route_hint: dict[str, Any] | None,
    routing_state: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    intent = str(routing_state.get("intent") or "other")
    if _is_portfolio_lookup_intent(message):
        name, args, _ = _portfolio_lookup_fallback_call(message)
        return name, args
    if str(routing_state.get("knowledge_route_id") or ""):
        return (
            "corp_db_search",
            _rewrite_authoritative_kb_search_args({}, message, routing_state),
        )
    if route_hint:
        tool_name = str(route_hint.get("tool_name") or "").strip()
        if tool_name:
            args = dict(route_hint.get("tool_args") or {})
            if tool_name == "doc_search":
                args.setdefault("query", message)
                args.setdefault("top", 5)
            elif tool_name == "corp_db_search":
                kind = str(args.get("kind") or "")
                if kind == "hybrid_search":
                    if str(routing_state.get("knowledge_route_id") or ""):
                        args = _rewrite_authoritative_kb_search_args(args, message, routing_state)
                    elif intent == "company_fact":
                        args = _rewrite_company_fact_search_args(args, message)
                    else:
                        args.setdefault("query", message)
                elif kind in {"application_recommendation", "portfolio_by_sphere", "lamp_exact"}:
                    args["query"] = message
                    if kind == "portfolio_by_sphere":
                        args.setdefault("fuzzy", True)
            return tool_name, args
    if intent == "company_fact":
        return (
            "corp_db_search",
            _rewrite_company_fact_search_args({}, message),
        )
    if intent == "document_lookup":
        return ("doc_search", {"query": message, "top": 5})
    if intent == "portfolio_lookup":
        name, args, _ = _portfolio_lookup_fallback_call(message)
        return name, args
    if intent == "application_recommendation":
        return ("corp_db_search", {"kind": "application_recommendation", "query": message})
    return None


async def _deterministic_empty_response_fallback(
    *,
    message: str,
    route_hint: dict[str, Any] | None,
    routing_state: dict[str, Any],
    tool_ctx: ToolContext,
    iteration: int,
) -> str:
    fallback = _build_deterministic_fallback_call(message, route_hint, routing_state)
    if not fallback:
        return ""

    name, args = fallback
    agent_logger.warning(
        "[iter %s] Empty LLM completion, executing deterministic fallback %s with args=%s",
        iteration,
        name,
        json.dumps(args, ensure_ascii=False),
    )
    if routing_state.get("intent") == "company_fact":
        routing_state["company_fact_fallback_reason"] = "empty_llm_completion"
    tool_result = await execute_tool(
        name,
        args,
        tool_ctx,
        tool_call_id=f"fallback-{iteration}-{name}",
        tool_call_seq=0,
    )
    if not tool_result.success:
        agent_logger.warning(
            "[iter %s] Deterministic fallback tool failed: %s",
            iteration,
            tool_result.error or "unknown_error",
        )
        return ""

    bench_artifact = tool_result.metadata.get("bench_artifact") if isinstance(tool_result.metadata, dict) else None
    if isinstance(bench_artifact, dict):
        run_meta_append_artifact(bench_artifact)
    _record_tool_output_contract(name, tool_result, routing_state)
    if name == "doc_search":
        document_id = _document_identifier(args, tool_result.output or "")
        if document_id and not routing_state.get("document_id"):
            routing_state["document_id"] = document_id
            _update_routing_observability(routing_state)

    rendered = _render_deterministic_tool_output(name, args, tool_result.output or "", message)
    if not rendered and name == "corp_db_search" and _looks_like_contact_intent(message):
        routing_state["company_fact_fallback_reason"] = "weak_contact_payload"
        doc_args = {"query": _contact_doc_search_query(message), "top": 5}
        agent_logger.warning(
            "[iter %s] Empty contact payload after corp_db fallback, executing doc_search with args=%s",
            iteration,
            json.dumps(doc_args, ensure_ascii=False),
        )
        doc_result = await execute_tool(
            "doc_search",
            doc_args,
            tool_ctx,
            tool_call_id=f"fallback-{iteration}-doc_search",
            tool_call_seq=0,
        )
        if doc_result.success:
            bench_artifact = doc_result.metadata.get("bench_artifact") if isinstance(doc_result.metadata, dict) else None
            if isinstance(bench_artifact, dict):
                run_meta_append_artifact(bench_artifact)
            _record_tool_output_contract("doc_search", doc_result, routing_state)
            document_id = _document_identifier(doc_args, doc_result.output or "")
            if document_id and not routing_state.get("document_id"):
                routing_state["document_id"] = document_id
                _update_routing_observability(routing_state)
            rendered = _render_deterministic_tool_output("doc_search", doc_args, doc_result.output or "", message)
            if rendered:
                routing_state["selected_source"] = "doc_search"
                routing_state["doc_search_document_success"] = True
                routing_state["company_fact_fast_path"] = True
                routing_state["company_fact_rendered"] = True
                routing_state["company_fact_finalizer_mode"] = "deterministic_fallback"
                routing_state["finalizer_mode"] = "deterministic_fallback"
                _update_routing_observability(routing_state)
                return rendered
    if not rendered:
        return ""

    if name == "doc_search":
        routing_state["selected_source"] = "doc_search"
        routing_state["doc_search_document_success"] = True
    elif name == "corp_db_search":
        kind = str(args.get("kind") or "")
        routing_state["selected_source"] = "corp_db"
        if kind == "hybrid_search":
            routing_state["corp_db_company_fact_success"] = True
            routing_state["company_fact_payload_relevant"] = True
            routing_state["company_fact_fast_path"] = True
            routing_state["company_fact_rendered"] = True
            routing_state["company_fact_finalizer_mode"] = "deterministic_fallback"
            routing_state["finalizer_mode"] = "deterministic_fallback"
        elif kind == "application_recommendation":
            routing_state["corp_db_application_success"] = True
        elif kind == "portfolio_by_sphere":
            routing_state["corp_db_portfolio_success"] = True
    _update_routing_observability(routing_state)
    return rendered


async def _check_userbot_available() -> bool:
    """Check if userbot is available (with caching)"""
    global _userbot_available_cache, _userbot_check_time
    
    now = datetime.now().timestamp()
    if _userbot_available_cache is not None and (now - _userbot_check_time) < USERBOT_CHECK_TTL:
        return _userbot_available_cache
    
    userbot_url = os.getenv("USERBOT_URL", "http://userbot:8080")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{userbot_url}/health", timeout=aiohttp.ClientTimeout(total=1)) as resp:
                available = resp.status == 200
                _userbot_available_cache = available
                _userbot_check_time = now
                return available
    except:
        _userbot_available_cache = False
        _userbot_check_time = now
        return False


def try_fix_json_args(raw_args: str, tool_name: str) -> Optional[dict]:
    """Try to fix malformed JSON from models like DeepSeek
    
    Common issues:
    - Trailing commas: {"a": 1,}
    - Single quotes: {'a': 1}
    - Unquoted keys: {a: 1}
    - Missing closing brace
    - Newlines in strings
    """
    if not raw_args or not raw_args.strip():
        return {}
    
    original = raw_args
    
    # Try basic fixes
    try:
        # Fix trailing commas before } or ]
        fixed = re.sub(r',\s*([}\]])', r'\1', raw_args)
        
        # Fix single quotes to double quotes (careful with nested)
        if "'" in fixed and '"' not in fixed:
            fixed = fixed.replace("'", '"')
        
        # Try parsing
        return json.loads(fixed)
    except:
        pass
    
    # Try extracting JSON from markdown code block
    try:
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw_args)
        if match:
            return json.loads(match.group(1))
    except:
        pass
    
    # Try finding first { to last }
    try:
        start = raw_args.find('{')
        end = raw_args.rfind('}')
        if start != -1 and end != -1 and end > start:
            subset = raw_args[start:end+1]
            return json.loads(subset)
    except:
        pass
    
    # For simple tools, try to extract key-value pairs
    try:
        # Pattern: key: value or "key": value
        pairs = re.findall(r'["\']?(\w+)["\']?\s*:\s*["\']([^"\']+)["\']', raw_args)
        if pairs:
            return dict(pairs)
    except:
        pass
    
    agent_logger.warning(f"Could not fix JSON for {tool_name}: {original[:200]}")
    return None


sessions = SessionManager()


def load_system_prompt_template() -> str:
    """Load system prompt template from file"""
    prompt_file = Path(__file__).parent / "src" / "agent" / "system.txt"
    if prompt_file.exists():
        return prompt_file.read_text()
    
    # Fallback system prompt
    return """You are a helpful AI assistant with access to a Linux environment.
    
You can:
- Execute shell commands
- Read, write, edit, delete files
- Search the web
- Manage reminders and tasks

Always be helpful and concise. Think step by step when solving complex problems.
"""


def format_system_prompt(
    template: str,
    cwd: str,
    tools_list: str,
    user_ports: str,
    skills_list: str = ""
) -> str:
    """Replace placeholders in system prompt template"""
    from datetime import datetime
    
    prompt = template
    prompt = prompt.replace("{{cwd}}", cwd)
    prompt = prompt.replace("{{date}}", datetime.now().strftime("%Y-%m-%d %H:%M"))
    prompt = prompt.replace("{{tools}}", tools_list)
    prompt = prompt.replace("{{userPorts}}", user_ports)
    prompt = prompt.replace("{{skills}}", skills_list)
    
    return prompt


async def load_skill_mentions(user_id: str = None) -> str:
    """Load skill mentions for system prompt (name + description only)
    
    Agent loads full instructions on-demand via read_file when needed.
    Skills are available at /data/skills/{name}/ in the container.
    """
    tools_api_url = os.getenv("TOOLS_API_URL", "http://tools-api:8100")
    
    try:
        url = f"{tools_api_url}/skills/mentions"
        if user_id:
            url += f"?user_id={user_id}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    mentions = data.get("mentions", "")
                    if mentions:
                        return "\n\n" + mentions
    except Exception as e:
        agent_logger.warning(f"Failed to load skill mentions: {e}")
    
    return ""


def trim_history(history: list, max_msgs: int, max_chars: int) -> list:
    """Keep history within limits"""
    if len(history) > max_msgs:
        history = history[-max_msgs:]
    
    # Estimate size
    total = sum(len(json.dumps(m)) for m in history)
    while total > max_chars and len(history) > 2:
        history.pop(0)
        total = sum(len(json.dumps(m)) for m in history)
    
    return history


def save_session_to_file(session: Session):
    """Save session history to SESSION.json file"""
    if getattr(session, "source", "bot") == "web":
        return
    try:
        session_file = os.path.join(session.cwd, "SESSION.json")
        
        # Convert history to user/assistant format for display
        display_history = []
        i = 0
        while i < len(session.history):
            entry = {}
            msg = session.history[i]
            
            if msg.get("role") == "user":
                # Add date prefix
                date_str = datetime.now().strftime("[%Y-%m-%d]")
                entry["user"] = f"{date_str} {msg.get('content', '')}"
                
                # Check if next message is assistant
                if i + 1 < len(session.history) and session.history[i + 1].get("role") == "assistant":
                    entry["assistant"] = session.history[i + 1].get("content", "")
                    i += 1
                
                display_history.append(entry)
            i += 1
        
        # Keep only last 10 entries
        display_history = display_history[-10:]
        
        with open(session_file, 'w') as f:
            json.dump({"history": display_history}, f, ensure_ascii=False, indent=2)
        
        agent_logger.debug(f"Saved session to {session_file}")
    except Exception as e:
        agent_logger.error(f"Failed to save session: {e}")


def is_mlx_model() -> bool:
    """Check if using MLX backend (doesn't support tool calling)"""
    model = get_model().lower()
    # MLX models typically have mlx in name or are local models
    return "mlx" in model or model.startswith("local/")


def estimate_context_size(messages: list) -> int:
    """Estimate context size in characters"""
    return sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)


def _int_env(name: str, default: int, *, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _float_env(name: str, default: float, *, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default))))
    except ValueError:
        return default


def _max_context_chars() -> int:
    return _int_env("MAX_CONTEXT_CHARS", 40000, minimum=1024)


def _llm_max_attempts(purpose: str = "agent_loop") -> int:
    """Maximum number of attempts for transient LLM failures."""
    base_attempts = _int_env("LLM_MAX_ATTEMPTS", 3, minimum=1)
    env_keys = {
        "agent_loop": "LLM_AGENT_LOOP_MAX_ATTEMPTS",
        "route_selector": "LLM_ROUTE_SELECTOR_MAX_ATTEMPTS",
        "route_selector_repair": "LLM_ROUTE_SELECTOR_REPAIR_MAX_ATTEMPTS",
        "finalizer": "LLM_FINALIZER_MAX_ATTEMPTS",
    }
    defaults = {
        "agent_loop": base_attempts,
        "route_selector": min(base_attempts, 2),
        "route_selector_repair": 1,
        "finalizer": min(base_attempts, 2),
    }
    env_name = env_keys.get(purpose)
    if not env_name:
        return base_attempts
    return _int_env(env_name, defaults.get(purpose, base_attempts), minimum=1)


def _llm_request_timeout_s(purpose: str = "agent_loop") -> float:
    base_timeout = _float_env("LLM_TIMEOUT_S", 120.0, minimum=1.0)
    env_keys = {
        "agent_loop": "LLM_AGENT_LOOP_TIMEOUT_S",
        "route_selector": "LLM_ROUTE_SELECTOR_TIMEOUT_S",
        "route_selector_repair": "LLM_ROUTE_SELECTOR_REPAIR_TIMEOUT_S",
        "finalizer": "LLM_FINALIZER_TIMEOUT_S",
    }
    defaults = {
        "agent_loop": base_timeout,
        "route_selector": min(base_timeout, 20.0),
        "route_selector_repair": min(base_timeout, 15.0),
        "finalizer": min(base_timeout, 20.0),
    }
    env_name = env_keys.get(purpose)
    if not env_name:
        return base_timeout
    return _float_env(env_name, defaults.get(purpose, base_timeout), minimum=1.0)


def _llm_retry_delay(attempt: int) -> float:
    """Linear retry backoff in seconds."""
    try:
        base_delay = float(os.getenv("LLM_RETRY_BASE_DELAY_S", "0.75"))
    except ValueError:
        base_delay = 0.75
    return max(0.0, base_delay * max(1, attempt))


def _context_trim_marker(label: str) -> str:
    return f"[{label} trimmed for context budget]"


def _context_tool_call_ids(message: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    tool_calls = message.get("tool_calls") or []
    if not isinstance(tool_calls, list):
        return ids
    for item in tool_calls:
        if not isinstance(item, dict):
            continue
        call_id = str(item.get("id") or "").strip()
        if call_id:
            ids.append(call_id)
    return ids


def _context_message_blocks(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group history into removal-safe blocks.

    Assistant messages with tool_calls and the contiguous tool replies that
    satisfy them are removed as one atomic block. Partial compaction is only
    allowed later at the individual message-content level, never by deleting
    just one side of a tool exchange.
    """
    entries = [{"key": idx, "message": dict(message)} for idx, message in enumerate(messages)]
    blocks: list[dict[str, Any]] = []
    idx = 0
    while idx < len(entries):
        entry = entries[idx]
        message = entry["message"]
        role = str(message.get("role") or "")
        if role == "assistant" and message.get("tool_calls"):
            block_entries = [entry]
            idx += 1
            while idx < len(entries) and str(entries[idx]["message"].get("role") or "") == "tool":
                block_entries.append(entries[idx])
                idx += 1
            blocks.append(
                {
                    "kind": "tool_exchange" if len(block_entries) > 1 else "tool_call_orphan",
                    "entries": block_entries,
                }
            )
            continue
        if role == "tool":
            block_entries = [entry]
            idx += 1
            while idx < len(entries) and str(entries[idx]["message"].get("role") or "") == "tool":
                block_entries.append(entries[idx])
                idx += 1
            blocks.append({"kind": "orphan_tool", "entries": block_entries})
            continue
        blocks.append({"kind": role or "context", "entries": [entry]})
        idx += 1
    return blocks


def _flatten_context_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [entry["message"] for block in blocks for entry in block["entries"]]


def _context_block_is_protected(block: dict[str, Any], protected_keys: set[int]) -> bool:
    return any(entry["key"] in protected_keys for entry in block["entries"])


def _context_drop_priority(block: dict[str, Any]) -> int:
    kind = str(block.get("kind") or "")
    if kind in {"tool_exchange", "tool_call_orphan", "orphan_tool"}:
        return 0
    if kind == "assistant":
        return 2
    if kind == "user":
        return 3
    if kind == "system":
        return 99
    return 4


def _context_truncation_priority(entry_key: int, message: dict[str, Any], protected_keys: set[int]) -> int:
    role = str(message.get("role") or "")
    if role == "system":
        return 99
    if role == "tool":
        return 0 if entry_key not in protected_keys else 1
    if role == "assistant" and message.get("tool_calls"):
        return 99
    if role == "assistant":
        return 3
    if role == "user":
        return 99
    return 98


def _context_messages_have_valid_tool_flow(messages: list[dict[str, Any]]) -> bool:
    idx = 0
    while idx < len(messages):
        message = messages[idx]
        role = str(message.get("role") or "")
        if role == "assistant" and message.get("tool_calls"):
            expected_ids = _context_tool_call_ids(message)
            if not expected_ids:
                return False
            expected = set(expected_ids)
            seen: set[str] = set()
            idx += 1
            while idx < len(messages) and str(messages[idx].get("role") or "") == "tool":
                tool_call_id = str(messages[idx].get("tool_call_id") or "").strip()
                if not tool_call_id or tool_call_id not in expected or tool_call_id in seen:
                    return False
                seen.add(tool_call_id)
                idx += 1
            if seen != expected:
                return False
            continue
        if role == "tool":
            return False
        idx += 1
    return True


def _context_label(message: dict[str, Any]) -> str:
    role = str(message.get("role") or "")
    if role == "tool":
        return "tool output"
    if role == "assistant":
        return "assistant context"
    if role == "user":
        return "user message"
    return "context"


def _compact_context_content(content: str, keep_chars: int, label: str) -> str:
    marker = _context_trim_marker(label)
    if not content:
        return marker
    if keep_chars <= 0:
        return marker
    if len(content) <= keep_chars:
        return content
    if keep_chars <= len(marker) + 8:
        return marker
    body_budget = keep_chars - len(marker) - 2
    if body_budget <= 16:
        return marker
    head = min(len(content), max(16, int(body_budget * 0.65)))
    tail = max(0, body_budget - head)
    if tail == 0:
        return f"{content[:body_budget]}\n{marker}"
    return f"{content[:head]}\n{marker}\n{content[-tail:]}"


def _truncate_message_to_size(message: dict[str, Any], max_message_chars: int, *, label: str) -> dict[str, Any] | None:
    if max_message_chars <= 0:
        return None
    content = message.get("content")
    text = content if isinstance(content, str) else str(content or "")
    if not text:
        return None
    base_message = dict(message)
    base_message["content"] = text
    if estimate_context_size([base_message]) <= max_message_chars:
        return base_message

    low = 0
    high = len(text)
    best: dict[str, Any] | None = None
    while low <= high:
        keep_chars = (low + high) // 2
        candidate = dict(base_message)
        candidate["content"] = _compact_context_content(text, keep_chars, label)
        candidate_size = estimate_context_size([candidate])
        if candidate_size <= max_message_chars:
            best = candidate
            low = keep_chars + 1
        else:
            high = keep_chars - 1

    if best is not None:
        return best

    fallback = dict(base_message)
    fallback["content"] = _context_trim_marker(label)
    if estimate_context_size([fallback]) <= max_message_chars:
        return fallback
    return None


def _protected_context_keys(messages: list[dict[str, Any]]) -> set[int]:
    protected: set[int] = set()
    if not messages:
        return protected
    if str(messages[0].get("role") or "") == "system":
        protected.add(0)
    protected.add(len(messages) - 1)

    for idx in range(len(messages) - 1, -1, -1):
        if str(messages[idx].get("role") or "") == "user":
            protected.add(idx)
            break

    if str(messages[-1].get("role") or "") == "tool":
        for idx in range(len(messages) - 2, -1, -1):
            role = str(messages[idx].get("role") or "")
            if role == "assistant" and messages[idx].get("tool_calls"):
                protected.add(idx)
                break
            if role != "tool":
                break
    return protected


def _update_context_trim_meta(result: ContextBudgetResult, *, purpose: str) -> None:
    meta = run_meta_get()
    if not isinstance(meta, dict):
        return
    meta["context_trim_events"] = int(meta.get("context_trim_events", 0)) + 1
    meta["context_trim_pre_chars_max"] = max(int(meta.get("context_trim_pre_chars_max", 0)), int(result.pre_chars))
    meta["context_trim_post_chars_max"] = max(int(meta.get("context_trim_post_chars_max", 0)), int(result.post_chars))
    meta["context_trim_removed_messages_total"] = int(meta.get("context_trim_removed_messages_total", 0)) + int(result.removed_messages)
    meta["context_trim_truncated_messages_total"] = int(meta.get("context_trim_truncated_messages_total", 0)) + int(result.truncated_messages)
    meta["context_trim_hard_stops"] = int(meta.get("context_trim_hard_stops", 0)) + (1 if result.hard_stop else 0)
    meta["context_trim_last_stage"] = str(purpose or "agent_loop")
    meta["context_trim_last_pre_chars"] = int(result.pre_chars)
    meta["context_trim_last_post_chars"] = int(result.post_chars)
    meta["context_trim_last_removed_messages"] = int(result.removed_messages)
    meta["context_trim_last_truncated_messages"] = int(result.truncated_messages)
    meta["context_trim_last_hard_stop"] = bool(result.hard_stop)
    meta["context_trim_last_reason"] = str(result.reason or "")


def _record_context_trim(result: ContextBudgetResult, *, purpose: str) -> None:
    observe_context_trim(
        purpose=purpose,
        pre_chars=result.pre_chars,
        post_chars=result.post_chars,
        removed_messages=result.removed_messages,
        hard_stop=result.hard_stop,
    )
    _update_context_trim_meta(result, purpose=purpose)
    span = trace.get_current_span()
    try:
        span.set_attribute("llm.context_trim.stage", str(purpose or "agent_loop"))
        span.set_attribute("llm.context_trim.pre_chars", int(result.pre_chars))
        span.set_attribute("llm.context_trim.post_chars", int(result.post_chars))
        span.set_attribute("llm.context_trim.removed_messages", int(result.removed_messages))
        span.set_attribute("llm.context_trim.truncated_messages", int(result.truncated_messages))
        span.set_attribute("llm.context_trim.hard_stop", bool(result.hard_stop))
        span.set_attribute("llm.context_trim.reason", str(result.reason or ""))
    except Exception:
        return None


def enforce_context_budget(messages: list[dict[str, Any]], max_chars: int) -> ContextBudgetResult:
    blocks = _context_message_blocks(messages)
    pre_messages = _flatten_context_blocks(blocks)
    pre_chars = estimate_context_size(pre_messages)
    if pre_chars <= max_chars:
        return ContextBudgetResult(
            messages=pre_messages,
            pre_chars=pre_chars,
            post_chars=pre_chars,
        )

    protected_keys = _protected_context_keys(messages)
    removed_messages = 0
    truncated_keys: set[int] = set()
    current_messages = _flatten_context_blocks(blocks)
    current_size = estimate_context_size(current_messages)

    while current_size > max_chars:
        removable_blocks = [
            block for block in blocks
            if not _context_block_is_protected(block, protected_keys)
        ]
        if not removable_blocks:
            break
        removable_blocks.sort(key=lambda block: (_context_drop_priority(block), block["entries"][0]["key"]))
        block_to_remove = removable_blocks[0]
        blocks = [block for block in blocks if block is not block_to_remove]
        removed_messages += len(block_to_remove["entries"])
        current_messages = _flatten_context_blocks(blocks)
        current_size = estimate_context_size(current_messages)

    while current_size > max_chars:
        truncatable_entries = [
            entry
            for block in blocks
            for entry in block["entries"]
            if _context_truncation_priority(entry["key"], entry["message"], protected_keys) < 99
        ]
        if not truncatable_entries:
            break
        truncatable_entries.sort(
            key=lambda entry: (
                _context_truncation_priority(entry["key"], entry["message"], protected_keys),
                -estimate_context_size([entry["message"]]),
                entry["key"],
            )
        )
        changed = False
        for entry in truncatable_entries:
            current_message_size = estimate_context_size([entry["message"]])
            if current_message_size <= 0:
                continue
            excess_chars = current_size - max_chars
            target_message_size = max(32, current_message_size - excess_chars)
            truncated = _truncate_message_to_size(
                entry["message"],
                target_message_size,
                label=_context_label(entry["message"]),
            )
            if truncated is None:
                continue
            new_message_size = estimate_context_size([truncated])
            if new_message_size >= current_message_size:
                continue
            entry["message"] = truncated
            truncated_keys.add(entry["key"])
            current_messages = _flatten_context_blocks(blocks)
            current_size = estimate_context_size(current_messages)
            changed = True
            break
        if not changed:
            break

    current_messages = _flatten_context_blocks(blocks)
    tool_flow_valid = _context_messages_have_valid_tool_flow(current_messages)
    hard_stop = current_size > max_chars or not tool_flow_valid
    reason = ""
    if hard_stop:
        reason = "tool_protocol_invalid_after_trim" if not tool_flow_valid and current_size <= max_chars else "protected_context_exceeds_budget"
    elif removed_messages or truncated_keys:
        reason = "trimmed_to_budget"
    return ContextBudgetResult(
        messages=current_messages,
        pre_chars=pre_chars,
        post_chars=current_size,
        removed_messages=removed_messages,
        truncated_messages=len(truncated_keys),
        hard_stop=hard_stop,
        reason=reason,
    )


def _should_retry_llm_status(status: int, error_text: str) -> bool:
    """Return True for transient proxy/upstream failures."""
    normalized = (error_text or "").lower()
    if status in {429, 502, 503, 504}:
        return True
    if status == 408:
        transient_markers = (
            "stream disconnected before completion",
            "stream closed before response.completed",
            "request timeout",
            "upstream timed out",
        )
        return any(marker in normalized for marker in transient_markers)
    return False


def _get_language_reminder() -> str:
    """Get language enforcement reminder from locale config"""
    try:
        locale_path = "/data/bot_locale.json"
        if os.path.exists(locale_path):
            with open(locale_path) as f:
                data = json.load(f)
                lang = data.get("language", "ru")
        else:
            lang = "ru"
    except:
        lang = "ru"
    
    reminders = {
        "ru": "\n\n[ВАЖНО: Ответь пользователю НА РУССКОМ ЯЗЫКЕ. Дай краткий ответ по-русски.]",
        "en": "",  # English is default for most models
    }
    return reminders.get(lang, reminders["ru"])


def get_search_model() -> str:
    """Get search response model from env or search config"""
    model = os.getenv("SEARCH_MODEL_NAME", "")
    if model:
        return model
    try:
        config_path = "/data/search_config.json"
        if os.path.exists(config_path):
            with open(config_path) as f:
                cfg = json.load(f)
                return cfg.get("response_model", "")
    except:
        pass
    return ""


async def call_llm(messages: list, tools: list, model_override: str = "", *, purpose: str = "agent_loop") -> dict:
    """Call LLM via proxy. model_override allows using a different model (e.g. for search responses)."""
    if not CONFIG.proxy_url:
        return {"error": "No proxy configured"}

    max_context = _max_context_chars()
    trim_result = enforce_context_budget(messages, max_context)
    if trim_result.pre_chars > max_context:
        _record_context_trim(trim_result, purpose=purpose)
        if trim_result.hard_stop:
            agent_logger.error(
                "Context trim hard stop stage=%s pre=%s post=%s budget=%s removed=%s truncated=%s reason=%s",
                purpose,
                trim_result.pre_chars,
                trim_result.post_chars,
                max_context,
                trim_result.removed_messages,
                trim_result.truncated_messages,
                trim_result.reason or "unknown",
            )
            return {
                "error": (
                    f"Context exceeds MAX_CONTEXT_CHARS ({trim_result.pre_chars} > {max_context}) "
                    "and cannot be trimmed safely"
                )
            }
        agent_logger.warning(
            "Context too large for stage=%s (%s chars > %s), trimming...",
            purpose,
            trim_result.pre_chars,
            max_context,
        )
        agent_logger.info(
            "Trimmed context stage=%s to %s chars (budget=%s removed=%s truncated=%s)",
            purpose,
            trim_result.post_chars,
            max_context,
            trim_result.removed_messages,
            trim_result.truncated_messages,
        )
    messages = trim_result.messages
    
    # MLX doesn't support tool calling - use prompt-based approach
    use_tools = not is_mlx_model() and tools
    
    # Get model and temperature from admin config (dynamic)
    current_model = model_override or get_model()
    current_temp = get_temperature()
    
    if model_override:
        agent_logger.info(f"Using search model: {model_override}")
    
    request_body = {
        "model": current_model,
        "messages": messages,
        "max_tokens": 8000,
        "temperature": current_temp,
    }
    
    if use_tools:
        request_body["tools"] = tools
        request_body["tool_choice"] = "auto"
    else:
        # For MLX: inject tool descriptions into system prompt
        if tools and is_mlx_model():
            agent_logger.info("MLX mode: tool calling disabled, using prompt-based approach")
            # Note: MLX users should use simpler tasks or switch to OpenAI-compatible API
    
    # Log raw request (truncate long content)
    agent_logger.debug("=" * 60)
    agent_logger.debug("RAW REQUEST:")
    for i, msg in enumerate(messages):
        role = msg.get("role", "?")
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls") or []
        
        if role == "system":
            agent_logger.debug(f"  [{i}] system: ({len(content)} chars)")
        elif role == "user":
            agent_logger.debug(f"  [{i}] user: {content[:200]}{'...' if len(content) > 200 else ''}")
        elif role == "assistant":
            if tool_calls:
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    agent_logger.debug(f"  [{i}] assistant tool_call: {fn.get('name')}({fn.get('arguments', '')[:100]})")
            else:
                agent_logger.debug(f"  [{i}] assistant: {content[:200] if content else '(no content)'}{'...' if content and len(content) > 200 else ''}")
        elif role == "tool":
            agent_logger.debug(f"  [{i}] tool[{msg.get('tool_call_id', '?')[:8]}]: {content[:100]}{'...' if len(content) > 100 else ''}")
    agent_logger.debug(f"  tools: {len(tools)} definitions")
    agent_logger.debug("=" * 60)
    
    request_id = OBS_REQUEST_ID.get("-")
    headers = inject_trace_context(request_id=request_id)
    llm_started = perf_counter()
    max_attempts = _llm_max_attempts(purpose)
    request_timeout_s = _llm_request_timeout_s(purpose)

    for attempt in range(1, max_attempts + 1):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{CONFIG.proxy_url}/v1/chat/completions",
                    json=request_body,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=request_timeout_s)
                ) as resp:
                    if resp.status != 200:
                        error = await resp.text()
                        if _should_retry_llm_status(resp.status, error) and attempt < max_attempts:
                            delay = _llm_retry_delay(attempt)
                            agent_logger.warning(
                                "Transient LLM error on attempt %s/%s: status=%s; retrying in %.2fs",
                                attempt,
                                max_attempts,
                                resp.status,
                                delay,
                            )
                            if delay > 0:
                                await asyncio.sleep(delay)
                            continue

                        agent_logger.error(f"RAW RESPONSE ERROR: {resp.status} - {error[:500]}")
                        run_meta_update_llm(
                            duration_ms=(perf_counter() - llm_started) * 1000,
                            usage=None,
                            model=current_model,
                        )
                        return {"error": f"LLM error {resp.status}: {error[:200]}"}
                    
                    result = await resp.json()
                    
                    # Log raw response
                    agent_logger.debug("RAW RESPONSE:")
                    agent_logger.debug(f"  id: {result.get('id', '?')}")
                    agent_logger.debug(f"  model: {result.get('model', '?')}")
                    
                    choices = result.get("choices", [])
                    for i, choice in enumerate(choices):
                        msg = choice.get("message", {})
                        finish = choice.get("finish_reason", "?")
                        content = msg.get("content", "")
                        tool_calls = msg.get("tool_calls", [])
                        
                        agent_logger.debug(f"  choice[{i}] finish_reason: {finish}")
                        if content:
                            agent_logger.debug(f"  choice[{i}] content: {content[:300]}{'...' if len(content) > 300 else ''}")
                        if tool_calls:
                            for tc in tool_calls:
                                fn = tc.get("function", {})
                                agent_logger.debug(f"  choice[{i}] tool_call: {fn.get('name')}({fn.get('arguments', '')[:150]})")
                    
                    usage = result.get("usage", {})
                    agent_logger.debug(f"  usage: prompt={usage.get('prompt_tokens', '?')}, completion={usage.get('completion_tokens', '?')}, total={usage.get('total_tokens', '?')}")
                    agent_logger.debug("=" * 60)
                    
                    run_meta_update_llm(
                        duration_ms=(perf_counter() - llm_started) * 1000,
                        usage=result.get("usage"),
                        model=str(result.get("model") or current_model),
                    )
                    return result
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            if attempt < max_attempts:
                delay = _llm_retry_delay(attempt)
                agent_logger.warning(
                    "Transient LLM transport error on attempt %s/%s: %s; retrying in %.2fs",
                    attempt,
                    max_attempts,
                    e,
                    delay,
                )
                if delay > 0:
                    await asyncio.sleep(delay)
                continue

            agent_logger.error(f"RAW RESPONSE EXCEPTION: {e}")
            try:
                run_meta_update_llm(
                    duration_ms=(perf_counter() - llm_started) * 1000,
                    usage=None,
                    model=current_model,
                )
            except Exception:
                pass
            return {"error": str(e)}
        except Exception as e:
            agent_logger.error(f"RAW RESPONSE EXCEPTION: {e}")
            try:
                run_meta_update_llm(
                    duration_ms=(perf_counter() - llm_started) * 1000,
                    usage=None,
                    model=current_model,
                )
            except Exception:
                pass
            return {"error": str(e)}

    run_meta_update_llm(
        duration_ms=(perf_counter() - llm_started) * 1000,
        usage=None,
        model=current_model,
    )
    return {"error": "LLM request failed after retries"}


async def get_tool_definitions(source: str = "bot", lazy_loading: bool = True) -> list:
    """Get tool definitions from Tools API + bot-specific tools
    
    Shared tools come from Tools API (can be toggled in admin panel)
    Bot-only tools (send_file, send_dm, etc.) are added locally for 'bot' source
    
    If lazy_loading=True, only loads base tools + search_tools capability.
    Agent can discover and load more tools via search_tools/load_tools.
    """
    global _tools_cache, _tools_cache_time
    import time
    
    now = time.time()
    cache_key = f"{source}_{'lazy' if lazy_loading else 'full'}"
    
    # Check if we have cached tools for this source
    if isinstance(_tools_cache, dict) and cache_key in _tools_cache:
        if (now - _tools_cache_time) < TOOLS_CACHE_TTL:
            return _tools_cache[cache_key]
    
    # Initialize cache as dict if needed
    if not isinstance(_tools_cache, dict):
        _tools_cache = {}
    
    tools_api_url = os.getenv("TOOLS_API_URL", "http://tools-api:8100")
    
    try:
        async with aiohttp.ClientSession() as session:
            # Choose endpoint based on lazy_loading
            endpoint = "/tools/base" if lazy_loading else "/tools/enabled"
            
            async with session.get(
                f"{tools_api_url}{endpoint}",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    tools = data.get("tools", [])
                    
                    # Add bot-only tools for 'bot' source
                    if source == "bot":
                        tools.extend(get_bot_only_tools())
                    
                    _tools_cache[cache_key] = tools
                    _tools_cache_time = now
                    mode = "base (lazy)" if lazy_loading else "all"
                    agent_logger.debug(f"Loaded {len(tools)} {mode} tools for source={source}")
                    return tools
                else:
                    agent_logger.error(f"Tools API error: {resp.status}")
    except Exception as e:
        agent_logger.error(f"Failed to fetch tools from API: {e}")
    
    # Fallback to local definitions if API fails
    from tools import TOOL_DEFINITIONS
    agent_logger.warning("Using local TOOL_DEFINITIONS as fallback")
    return TOOL_DEFINITIONS


def get_bot_only_tools() -> list:
    """Bot-specific tools that are always available for telegram bot"""
    return [
        {
            "type": "function",
            "function": {
                "name": "send_file",
                "description": "Send a file from workspace to the chat.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to file in workspace"},
                        "caption": {"type": "string", "description": "Optional caption"}
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "send_dm",
                "description": "Send a SEPARATE private DM to a user. ONLY use from GROUP chats when you need to message someone privately. NEVER use in private/DM chats - your response IS the message!",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "integer", "description": "User ID (usually current user)"},
                        "text": {"type": "string", "description": "Message text"}
                    },
                    "required": ["user_id", "text"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "manage_message",
                "description": "Edit or delete bot messages.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["edit", "delete"]},
                        "message_id": {"type": "integer", "description": "Message ID to edit/delete"},
                        "text": {"type": "string", "description": "New text (for edit)"}
                    },
                    "required": ["action", "message_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "ask_user",
                "description": "Ask user a question and wait for their answer.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "description": "Question to ask"},
                        "timeout": {"type": "integer", "description": "Seconds to wait (default 60)"}
                    },
                    "required": ["question"]
                }
            }
        }
    ]


def clean_response(text: str) -> str:
    """Remove LLM artifacts from response"""
    if not text:
        return ""
    # Remove thinking blocks with content
    text = re.sub(r'<thinking>[\s\S]*?</thinking>', '', text, flags=re.IGNORECASE)
    # Remove standalone XML-like tags
    text = re.sub(r'</?(final|response|answer|output|reply|thinking)>', '', text, flags=re.IGNORECASE)
    return text.strip()


ROUTE_SELECTOR_UNAVAILABLE_MESSAGE = "Извините, сервис сейчас временно недоступен. Попробуйте повторить запрос немного позже."
SPHERE_CONTEXT_FOLLOW_UP_MARKERS = (
    "этой категории",
    "эта категория",
    "эту категорию",
    "из этой категории",
    "из этого списка",
    "этого списка",
    "эти категории",
    "для этой сферы",
    "в этой сфере",
)
SPHERE_CONTEXT_TTL_TURNS = 2


def _route_selector_enabled() -> bool:
    return os.getenv("ROUTE_SELECTOR_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


def _compact_selector_argument_schema(argument_schema: dict[str, Any], locked_args: dict[str, Any]) -> dict[str, Any]:
    properties = argument_schema.get("properties") if isinstance(argument_schema, dict) else {}
    if not isinstance(properties, dict):
        properties = {}
    required = argument_schema.get("required") if isinstance(argument_schema, dict) else []
    compact: dict[str, Any] = {
        "required": list(required) if isinstance(required, list) else [],
        "allowed_args": sorted(str(name) for name in properties.keys()),
    }
    enum_args: dict[str, list[Any]] = {}
    for name, spec in properties.items():
        if not isinstance(spec, dict):
            continue
        values = spec.get("enum")
        if isinstance(values, list) and values:
            enum_args[str(name)] = list(values)
    if enum_args:
        compact["enum_args"] = enum_args
    if isinstance(locked_args, dict) and locked_args:
        compact["locked_arg_keys"] = sorted(str(name) for name in locked_args.keys())
    return compact


def _compact_route_selector_payload(selector_payload: dict[str, Any]) -> dict[str, Any]:
    compact_routes: list[dict[str, Any]] = []
    for route in selector_payload.get("routes") or []:
        if not isinstance(route, dict):
            continue
        locked_args = route.get("locked_args") if isinstance(route.get("locked_args"), dict) else {}
        compact_route = {
            "route_id": str(route.get("route_id") or ""),
            "route_family": str(route.get("route_family") or ""),
            "route_kind": str(route.get("route_kind") or ""),
            "title": str(route.get("title") or "")[:160],
            "summary": str(route.get("summary") or "")[:240],
            "topics": list(route.get("topics") or [])[:6],
            "keywords": list(route.get("keywords") or [])[:12],
            "patterns": list(route.get("patterns") or [])[:6],
            "tool_name": str(route.get("tool_name") or route.get("executor") or ""),
            "locked_args": locked_args,
            "argument_schema": _compact_selector_argument_schema(route.get("argument_schema") or {}, locked_args),
            "argument_hints": dict(route.get("argument_hints") or {}),
            "fallback_route_ids": list(route.get("fallback_route_ids") or []),
        }
        table_scopes = route.get("table_scopes")
        if isinstance(table_scopes, list) and table_scopes:
            compact_route["table_scopes"] = table_scopes[:8]
        document_selectors = route.get("document_selectors")
        if isinstance(document_selectors, list) and document_selectors:
            compact_route["document_selectors"] = document_selectors[:8]
        compact_routes.append(compact_route)

    compact_payload = {
        "query": str(selector_payload.get("query") or ""),
        "catalog_version": str(selector_payload.get("catalog_version") or ""),
        "schema_version": int(selector_payload.get("schema_version") or 0),
        "candidate_route_ids": list(selector_payload.get("candidate_route_ids") or []),
        "routes": compact_routes,
    }
    resolved_sphere_context = selector_payload.get("resolved_sphere_context")
    if isinstance(resolved_sphere_context, dict) and resolved_sphere_context:
        compact_payload["resolved_sphere_context"] = {
            "sphere_name": str(resolved_sphere_context.get("sphere_name") or ""),
            "category_names": list(resolved_sphere_context.get("category_names") or []),
            "confirmed": bool(resolved_sphere_context.get("confirmed")),
        }
    return compact_payload


def _build_route_selector_messages(selector_payload: dict[str, Any]) -> list[dict[str, str]]:
    compact_payload = _compact_route_selector_payload(selector_payload)
    payload = json.dumps(compact_payload, ensure_ascii=False, separators=(",", ":"))
    system = (
        "You are a strict retrieval route selector. Choose exactly one route from the provided routes. "
        "Return only valid JSON with selected_route_id, confidence, reason, tool_args, and optional fallback_route_ids. "
        "tool_args must contain only fields declared by the selected route argument_schema. "
        "Respect locked_args for the chosen route and do not invent routes, tools, SQL, shell commands, file paths, or evidence policy overrides."
    )
    user = (
        "Select the best route and arguments for this user query using only this compact route catalog payload:\n"
        f"{payload}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _selector_args_shape(tool_args: dict[str, Any]) -> list[str]:
    return sorted(str(key) for key in tool_args if str(key).strip())


def _record_route_selector_unavailable(error: str) -> None:
    meta = run_meta_get()
    if isinstance(meta, dict):
        meta["route_selector_status"] = "unavailable"
        meta["route_selector_model"] = get_model()
        meta["route_selector_validation_error"] = str(error or "")[:500]
        meta["retrieval_phase"] = "closed"
        meta["retrieval_evidence_status"] = "error"
        meta["retrieval_close_reason"] = "route_selector_unavailable"
    update_correlation_context(
        route_selector_status="unavailable",
        retrieval_phase="closed",
        retrieval_evidence_status="error",
        retrieval_close_reason="route_selector_unavailable",
    )
    record_span_event(
        "route_selector.unavailable",
        route_selector_status="unavailable",
        retrieval_phase="closed",
        retrieval_evidence_status="error",
        retrieval_close_reason="route_selector_unavailable",
    )


def _next_session_turn_id(session: Session) -> int:
    turn_id = int(getattr(session, "turn_index", 0) or 0) + 1
    setattr(session, "turn_index", turn_id)
    return turn_id


def _get_session_sphere_context(session: Session) -> dict[str, Any] | None:
    context = getattr(session, "resolved_sphere_context", None)
    return dict(context) if isinstance(context, dict) else None


def _clear_session_sphere_context(session: Session) -> None:
    setattr(session, "resolved_sphere_context", None)


def _set_session_sphere_context(session: Session, context: dict[str, Any]) -> None:
    setattr(session, "resolved_sphere_context", dict(context))


def _message_named_canonical_sphere(message: str) -> str:
    normalized = _routing_message_text(message)
    for sphere_name in canonical_sphere_names():
        if _normalize_routing_text(sphere_name) in normalized:
            return sphere_name
    return ""


def _is_local_sphere_follow_up(message: str) -> bool:
    return _text_has_any(_routing_message_text(message), SPHERE_CONTEXT_FOLLOW_UP_MARKERS)


def _prepare_selector_sphere_context(session: Session, routing_message: str, turn_id: int) -> dict[str, Any] | None:
    context = _get_session_sphere_context(session)
    if not context:
        return None

    source_turn_id = int(context.get("source_turn_id") or 0)
    if source_turn_id and (turn_id - source_turn_id) > SPHERE_CONTEXT_TTL_TURNS:
        _clear_session_sphere_context(session)
        return None

    named_sphere = _message_named_canonical_sphere(routing_message)
    if named_sphere and named_sphere != str(context.get("sphere_name") or ""):
        _clear_session_sphere_context(session)
        return None

    if _is_document_lookup_intent(routing_message) or _is_company_fact_intent(routing_message):
        _clear_session_sphere_context(session)
        return None

    if not _is_local_sphere_follow_up(routing_message):
        _clear_session_sphere_context(session)
        return None

    category_names = list(context.get("category_names") or [])
    if not category_names:
        category_names = curated_category_names_for_sphere(str(context.get("sphere_name") or ""))
        context["category_names"] = category_names
    context["last_used_turn_id"] = turn_id
    _set_session_sphere_context(session, context)
    return context


def _resolved_sphere_context_from_tool(
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    tool_result: ToolResult,
    route_hint: dict[str, Any] | None,
    turn_id: int,
) -> dict[str, Any] | None:
    if tool_name != "corp_db_search" or not tool_result.success:
        return None

    payload = _parse_json_object(tool_result.output or "")
    kind = str(tool_args.get("kind") or payload.get("kind") or "")
    sphere_name = ""
    sphere_id: int | None = None
    confidence = 0.0
    category_names: list[str] = []

    if kind == "sphere_curated_categories":
        resolved = payload.get("resolved_sphere") if isinstance(payload.get("resolved_sphere"), dict) else {}
        if resolved.get("sphere_id") is not None:
            sphere_id = int(resolved.get("sphere_id"))
        sphere_name = str(resolved.get("sphere_name") or tool_args.get("sphere") or "").strip()
        confidence = float(resolved.get("confidence") or 0.95)
        results = payload.get("results") if isinstance(payload.get("results"), list) else []
        if sphere_id is None:
            for row in results:
                if isinstance(row, dict) and row.get("sphere_id") is not None:
                    sphere_id = int(row.get("sphere_id"))
                    break
        if not sphere_name:
            for row in results:
                if isinstance(row, dict) and str(row.get("sphere_name") or "").strip():
                    sphere_name = str(row.get("sphere_name") or "").strip()
                    break
        category_names = [
            str(row.get("category_name") or "").strip()
            for row in results
            if isinstance(row, dict) and str(row.get("category_name") or "").strip()
        ]
    elif kind == "application_recommendation":
        if str(payload.get("status") or "") not in {"success", "needs_clarification"}:
            return None
        resolved = payload.get("resolved_application") if isinstance(payload.get("resolved_application"), dict) else {}
        if resolved.get("sphere_id") is not None:
            sphere_id = int(resolved.get("sphere_id"))
        sphere_name = str(resolved.get("sphere_name") or tool_args.get("sphere") or "").strip()
        confidence = float(resolved.get("confidence") or 0.9)
        categories = payload.get("categories") if isinstance(payload.get("categories"), list) else []
        category_names = [
            str(row.get("category_name") or "").strip()
            for row in categories
            if isinstance(row, dict) and str(row.get("category_name") or "").strip()
        ]
    elif kind == "portfolio_by_sphere":
        if str(payload.get("status") or "") != "success":
            return None
        results = payload.get("results") if isinstance(payload.get("results"), list) else []
        if not results:
            return None
        first_row = results[0] if isinstance(results[0], dict) else {}
        if first_row.get("sphere_id") is not None:
            sphere_id = int(first_row.get("sphere_id"))
        sphere_name = str(first_row.get("sphere_name") or tool_args.get("sphere") or "").strip()
        confidence = 0.9
        category_names = curated_category_names_for_sphere(sphere_name)
    else:
        return None

    if not sphere_name or confidence < 0.75:
        return None

    return {
        "sphere_id": sphere_id,
        "sphere_name": sphere_name,
        "category_names": list(dict.fromkeys(category_names)),
        "source_route_id": str((route_hint or {}).get("route_id") or ""),
        "source_turn_id": turn_id,
        "last_used_turn_id": turn_id,
        "confidence": confidence,
        "confirmed": confidence >= 0.85,
    }


def _portfolio_bounded_failure_response(args: dict[str, Any], message: str) -> str:
    sphere_name = str(args.get("sphere") or "").strip()
    if sphere_name and _normalize_routing_text(sphere_name) != _normalize_routing_text(message):
        return (
            f"Не удалось подтвердить реализованные объекты в портфолио для направления «{sphere_name}». "
            "Уточните другую сферу или назовите конкретный объект."
        )
    return (
        "Не удалось однозначно определить сферу для поиска по портфолио. "
        "Уточните сферу применения или назовите конкретный реализованный объект."
    )


def _application_recovery_outcome(name: str, args: dict[str, Any], tool_result: ToolResult) -> str:
    if name != "corp_db_search" or str(args.get("kind") or "") != "application_recommendation":
        return ""
    if not tool_result.success:
        return "stopped_after_primary_error"
    payload = _parse_json_object(tool_result.output or "")
    status = str(payload.get("status") or "").strip().lower()
    if status in {"success", "needs_clarification"}:
        return ""
    if status == "error":
        return "stopped_after_primary_error"
    return "bounded_application_fallback"


def _application_failure_subject(message: str, args: dict[str, Any], payload: dict[str, Any]) -> str:
    resolved = payload.get("resolved_application") if isinstance(payload.get("resolved_application"), dict) else {}
    sphere_name = str(
        resolved.get("sphere_name")
        or args.get("sphere")
        or _message_named_canonical_sphere(message)
        or ""
    ).strip()
    if sphere_name and _normalize_routing_text(sphere_name) != _normalize_routing_text(message):
        return f"для сферы «{sphere_name}»"
    return "по этому запросу"


def _application_bounded_failure_response(message: str, args: dict[str, Any], tool_result: ToolResult) -> str:
    payload = _parse_json_object(tool_result.output or "") if tool_result.success else {}
    follow_up = str(payload.get("follow_up_question") or "").strip() if isinstance(payload, dict) else ""
    if follow_up:
        return follow_up
    subject = _application_failure_subject(message, args, payload if isinstance(payload, dict) else {})
    return (
        f"Не удалось уверенно подобрать рекомендацию {subject}. "
        "Уточните тип объекта, высоту установки или требования к защите."
    )


def _application_primary_error_response(message: str, args: dict[str, Any], tool_result: ToolResult) -> str:
    payload = _parse_json_object(tool_result.output or "") if tool_result.success else {}
    subject = _application_failure_subject(message, args, payload if isinstance(payload, dict) else {})
    return (
        f"Сейчас не удалось получить рекомендацию {subject}. "
        "Повторите запрос позже или уточните условия применения."
    )


def _short_circuit_application_failure(
    *,
    name: str,
    args: dict[str, Any],
    tool_result: ToolResult,
    message: str,
    routing_state: dict[str, Any],
) -> str:
    outcome = _application_recovery_outcome(name, args, tool_result)
    if not outcome:
        return ""
    payload = _parse_json_object(tool_result.output or "") if tool_result.success else {}
    status = str(payload.get("status") or "").strip().lower() if isinstance(payload, dict) else ""
    routing_state["application_recovery_outcome"] = outcome
    routing_state["selected_source"] = "corp_db"
    routing_state["retrieval_evidence_status"] = "error" if outcome == "stopped_after_primary_error" else (status or "empty")
    routing_state["retrieval_phase"] = "closed"
    routing_state["retrieval_close_reason"] = outcome
    routing_state["finalizer_mode"] = "deterministic_error" if outcome == "stopped_after_primary_error" else "deterministic_fallback"
    _update_routing_observability(routing_state)
    if outcome == "stopped_after_primary_error":
        return _application_primary_error_response(message, args, tool_result)
    return _application_bounded_failure_response(message, args, tool_result)


async def _select_route_with_llm(
    routing_message: str,
    *,
    sphere_context: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    selector_started = perf_counter()
    selector_payload = build_route_selector_payload(routing_message, sphere_context=sphere_context)
    candidate_routes = list(selector_payload.get("routes") or [])
    if not candidate_routes:
        raise RuntimeError("route selector has no candidate routes")

    result = await call_llm(_build_route_selector_messages(selector_payload), [], purpose="route_selector")
    selector_model = str(result.get("model") or get_model())
    if "error" in result:
        raise RuntimeError(str(result.get("error") or "route selector LLM error"))
    choices = result.get("choices") or []
    if not choices:
        raise RuntimeError("route selector returned no choices")
    message = choices[0].get("message") or {}
    content = str(message.get("content") or "").strip()
    validation = validate_selector_output(content, candidate_routes)
    first_validation_error_code = ""
    first_validation_error = ""
    repair_attempted = False
    repair_status = "not_needed"
    if not validation.valid and validation.repairable:
        first_validation_error_code = validation.error_code
        first_validation_error = validation.error
        repair_attempted = True
        repair_status = "attempted"
        repair_messages = _build_route_selector_messages(selector_payload)
        repair_messages.append({"role": "assistant", "content": content})
        repair_messages.append({"role": "user", "content": validation.repair_prompt})
        repair_result = await call_llm(repair_messages, [], purpose="route_selector_repair")
        selector_model = str(repair_result.get("model") or selector_model)
        if "error" in repair_result:
            raise RuntimeError(str(repair_result.get("error") or "route selector repair LLM error"))
        repair_choices = repair_result.get("choices") or []
        repair_content = ""
        if repair_choices:
            repair_content = str((repair_choices[0].get("message") or {}).get("content") or "").strip()
        validation = validate_selector_output(repair_content, candidate_routes, repair_attempted=True)
        repair_status = "succeeded" if validation.valid else "failed"
    if not validation.valid:
        raise RuntimeError(f"route selector output rejected: {validation.error_code}: {validation.error}")

    selected_route = dict(validation.route or {})
    selected_route["tool_args"] = dict(validation.tool_args)
    selected_route["selection_reason"] = str(validation.route.get("selection_reason") if validation.route else "") or "llm_selector"
    selected_route["selector_confidence"] = ""
    selected_route["selector_reason"] = ""
    try:
        parsed = json.loads(content)
        selected_route["selector_confidence"] = str(parsed.get("confidence") or "")
        selected_route["selector_reason"] = str(parsed.get("reason") or "")
        if parsed.get("reason"):
            selected_route["selection_reason"] = "llm_selector: " + str(parsed.get("reason"))
    except Exception:
        pass
    selected_route["candidate_route_ids"] = list(selector_payload.get("candidate_route_ids") or [])
    selected_route["fallback_route_ids"] = list(validation.fallback_route_ids)
    selected_route["selector_status"] = "valid"
    selected_route["selector_model"] = selector_model
    selected_route["selector_latency_ms"] = (perf_counter() - selector_started) * 1000
    selected_route["selector_repair_attempted"] = repair_attempted
    selected_route["selector_repair_status"] = repair_status
    selected_route["selector_validation_error_code"] = first_validation_error_code
    selected_route["selector_validation_error"] = first_validation_error
    selected_route["validated_arg_keys"] = _selector_args_shape(validation.tool_args)
    selected_route["routing_catalog_version"] = str(selector_payload.get("catalog_version") or "")
    selected_route["routing_catalog_origin"] = str(selector_payload.get("catalog_origin") or "")
    selected_route["routing_schema_version"] = int(selector_payload.get("schema_version") or 0)

    secondary_candidates = [
        dict(route)
        for route in candidate_routes
        if str(route.get("route_id") or "") != str(selected_route.get("route_id") or "")
    ][:3]
    route_selection = {
        "intent_family": str(selected_route.get("route_intent_family") or selected_route.get("intent_family") or ""),
        "primary_candidate": selected_route,
        "selected": selected_route,
        "candidate_route_ids": list(selector_payload.get("candidate_route_ids") or []),
        "secondary_candidates": secondary_candidates,
        "selection_reason": str(selected_route.get("selection_reason") or ""),
        "selected_route_kind": str(selected_route.get("route_kind") or ""),
        "selected_route_family": str(selected_route.get("route_family") or ""),
        "catalog_version": str(selector_payload.get("catalog_version") or ""),
        "catalog_origin": str(selector_payload.get("catalog_origin") or ""),
        "schema_version": int(selector_payload.get("schema_version") or 0),
        "route_count": int(selector_payload.get("route_count") or 0),
        "selector": {
            "status": "valid",
            "model": selector_model,
            "latency_ms": selected_route.get("selector_latency_ms"),
            "confidence": selected_route.get("selector_confidence"),
            "reason": selected_route.get("selector_reason"),
            "repair_attempted": repair_attempted,
            "repair_status": repair_status,
            "validation_error_code": first_validation_error_code,
            "validation_error": first_validation_error,
            "validated_arg_keys": list(selected_route.get("validated_arg_keys") or []),
            "candidate_route_ids": list(selector_payload.get("candidate_route_ids") or []),
        },
    }
    return route_selection, selected_route, secondary_candidates


def _get_admin_id() -> int:
    """Get admin user ID from config or env"""
    from admin_api import load_config as load_admin_config
    admin_config = load_admin_config()
    access = admin_config.get("access", {})
    return access.get("admin_id", int(os.getenv("ADMIN_USER_ID", "0")))


async def run_agent(
    user_id: int,
    chat_id: int,
    message: str,
    username: str = "",
    chat_type: str = "private",
    source: str = "bot",
    execution_mode: str = EXECUTION_MODE_RUNTIME,
) -> str:
    """Run ReAct agent loop"""
    execution_mode = normalize_execution_mode(execution_mode)
    session = sessions.get(user_id, chat_id, source=source)
    
    # Check if user is admin (bypasses some security patterns)
    is_admin = (user_id == _get_admin_id())
    current_turn_id = _next_session_turn_id(session)
    
    agent_logger.info(
        f"Agent run: user={user_id}, chat={chat_id}, source={source}, admin={is_admin}, execution_mode={execution_mode}"
    )
    agent_logger.info(f"Message: {message[:100]}...")
    
    # Get tool definitions FIRST (needed for system prompt)
    use_lazy_loading = os.getenv("LAZY_TOOL_LOADING", "true").lower() == "true"
    tool_definitions = await get_tool_definitions(source, lazy_loading=use_lazy_loading)
    
    # Check if userbot is available
    userbot_available = await _check_userbot_available()
    tool_definitions = filter_tools_for_session(tool_definitions, chat_type, source, userbot_available)
    
    # Format tools list for prompt
    tools_list = "\n".join([
        f"- {t['function']['name']}: {t['function'].get('description', '')[:100]}"
        for t in tool_definitions
    ])
    
    # Load skill mentions
    skill_mentions = await load_skill_mentions(str(user_id))
    
    # Get user ports
    user_ports = f"{4010 + (user_id % 1000)}-{4010 + (user_id % 1000) + 9}"
    
    # Build system prompt with placeholders replaced
    system_template = load_system_prompt_template()
    system_prompt = format_system_prompt(
        template=system_template,
        cwd=session.cwd,
        tools_list=tools_list,
        user_ports=user_ports,
        skills_list=skill_mentions
    )
    
    # Add workspace info
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    workspace_info = f"\nUser: @{username} (id={user_id})\nWorkspace: {session.cwd}\nTime: {timestamp}\nSource: {source}"
    if source == "web":
        workspace_info += (
            "\nWeb widget formatting hints:"
            "\n- Prefer concise markdown tables for comparisons or ranked numeric results."
            "\n- Prefer short field lists like 'Title:', 'Description:', 'Price:' when highlighting a single result."
        )
    
    # Add Google email if authorized (admin-only)
    google_email = get_google_email()
    if google_email:
        workspace_info += f"\nGoogle: {google_email} (authorized, use as user_google_email for Google Workspace tools)"
    
    routing_message = _routing_query_text(message) or str(message or "")
    selector_sphere_context = _prepare_selector_sphere_context(session, routing_message, current_turn_id)
    explicit_document_request = _is_document_lookup_intent(routing_message)
    if _route_selector_enabled():
        try:
            route_selection, route_hint, secondary_route_candidates = await _select_route_with_llm(
                routing_message,
                sphere_context=selector_sphere_context,
            )
        except Exception as exc:
            agent_logger.error(f"Route selector unavailable or invalid: {exc}")
            _record_route_selector_unavailable(str(exc))
            return ROUTE_SELECTOR_UNAVAILABLE_MESSAGE
    else:
        route_selection = select_route(routing_message, explicit_document_request=explicit_document_request)
        if route_selection.get("catalog_unavailable"):
            agent_logger.error("Routing catalog unavailable: %s", route_selection.get("error") or "unknown")
            return (
                "Маршрутизация временно недоступна: активный каталог маршрутов не опубликован "
                "или не прошел проверку. Повторите запрос позже."
            )
        route_hint = (
            route_selection.get("primary_candidate")
            or route_selection.get("selected")
        )
        secondary_route_candidates = list(route_selection.get("secondary_candidates") or []) if route_selection else []
    if route_hint:
        workspace_info += "\nRouting shortlist:"
        workspace_info += f"\n- primary: {_format_route_candidate_for_prompt(route_hint)}"
        for candidate in secondary_route_candidates[:3]:
            workspace_info += f"\n- secondary: {_format_route_candidate_for_prompt(candidate)}"

    messages = [{"role": "system", "content": system_prompt + workspace_info}]
    messages.extend(session.history)
    messages.append({"role": "user", "content": message})
    
    # Trim if needed
    context_headroom_chars = 2000
    history_budget = max(
        2000,
        _max_context_chars() - estimate_context_size([messages[0], messages[-1]]) - context_headroom_chars,
    )
    messages = [messages[0]] + trim_history(messages[1:], CONFIG.max_context_messages, history_budget)
    
    tool_ctx = ToolContext(
        cwd=session.cwd,
        session_id=f"{user_id}_{chat_id}",
        user_id=user_id,
        chat_id=chat_id,
        chat_type=chat_type,
        source=source,
        is_admin=is_admin
    )
    
    final_response = ""
    iteration = 0
    tool_call_seq = 0
    has_search_tool = False  # Track if search_web was called
    route_hint_args = dict(route_hint.get("tool_args") or {}) if route_hint else {}
    company_fact_intent_type = _company_fact_intent_type(routing_message)
    authoritative_route_id = str(route_hint_args.get("knowledge_route_id") or "")
    source_file_scope = list(route_hint_args.get("source_files") or []) if route_hint_args else []
    topic_facets = list(route_hint_args.get("topic_facets") or []) if route_hint_args else []
    preferred_document_ids = list(route_hint_args.get("preferred_document_ids") or []) if route_hint_args else []
    selected_document_id = str(route_hint.get("document_id") or "") if route_hint else ""
    if not selected_document_id:
        for item in preferred_document_ids:
            value = str(item or "").strip()
            if value:
                selected_document_id = value
                break
    if not topic_facets and authoritative_route_id == "corp_kb.company_common":
        topic_facets = _company_common_topic_facets(routing_message)
    elif not topic_facets and authoritative_route_id == "corp_kb.lighting_norms":
        topic_facets = _lighting_norms_topic_facets(routing_message)
    selected_route_kind = str(
        route_hint.get("selected_route_kind") or route_hint.get("route_kind") or ""
    ) if route_hint else ""
    if not selected_route_kind and route_hint:
        selected_route_kind = "doc_domain" if str(route_hint.get("source") or "") == "doc_search" else "corp_table"
    candidate_route_ids = list(route_hint.get("candidate_route_ids") or route_selection.get("candidate_route_ids") or []) if route_hint else []
    if not candidate_route_ids and route_hint and route_hint.get("route_id"):
        candidate_route_ids = [str(route_hint.get("route_id"))]
    canonical_route_id = str(route_hint.get("route_id") or "") if route_hint else ""
    if company_fact_intent_type and not authoritative_route_id:
        authoritative_route_id = "corp_kb.company_common"
        source_file_scope = list(KB_ROUTE_SPECS[authoritative_route_id]["source_files"])
        if not topic_facets:
            topic_facets = _company_common_topic_facets(routing_message)
    if authoritative_route_id:
        canonical_route_id = authoritative_route_id
        if authoritative_route_id not in candidate_route_ids:
            candidate_route_ids = [authoritative_route_id, *candidate_route_ids]
    selector_meta = route_selection.get("selector") if isinstance(route_selection.get("selector"), dict) else {}
    selector_latency_ms = float(selector_meta.get("latency_ms") or route_hint.get("selector_latency_ms") or 0.0) if route_hint else 0.0
    routing_catalog_version = str(
        route_selection.get("catalog_version")
        or route_hint.get("routing_catalog_version")
        or route_hint.get("catalog_version")
        or ""
    ) if route_hint else str(route_selection.get("catalog_version") or "")
    routing_catalog_origin = str(
        route_selection.get("catalog_origin")
        or route_hint.get("routing_catalog_origin")
        or route_hint.get("catalog_origin")
        or ""
    ) if route_hint else str(route_selection.get("catalog_origin") or "")
    routing_schema_version = int(
        route_selection.get("schema_version")
        or route_hint.get("routing_schema_version")
        or route_hint.get("schema_version")
        or 0
    ) if route_hint else int(route_selection.get("schema_version") or 0)
    retrieval_route_family = ""
    if route_hint:
        retrieval_route_family = str(
            route_hint.get("selected_route_family")
            or route_hint.get("route_family")
            or route_hint.get("route_id")
            or ""
        )
        if "." not in retrieval_route_family and route_hint.get("route_id"):
            retrieval_route_family = str(route_hint.get("route_id") or "")
    intent_family = str(route_selection.get("intent_family") or "").strip()
    if not intent_family:
        intent_family = (
            "document_lookup"
            if _is_document_lookup_intent(routing_message)
            else "portfolio_lookup"
            if _is_portfolio_lookup_intent(routing_message)
            else "application_recommendation"
            if _is_application_recommendation_intent(routing_message)
            else "company_fact"
            if bool(company_fact_intent_type)
            else "other"
        )
    routing_state = {
        "execution_mode": execution_mode,
        "intent": intent_family,
        "selected_source": "unknown",
        "route_id": canonical_route_id,
        "route_source": str(route_hint.get("source") or "") if route_hint else "",
        "route_tool_name": str(route_hint.get("tool_name") or "") if route_hint else "",
        "route_shortlist": [dict(route_hint)] + [dict(item) for item in secondary_route_candidates[:3]] if route_hint else [],
        "selected_route_kind": selected_route_kind,
        "candidate_route_ids": candidate_route_ids,
        "retrieval_route_family": authoritative_route_id or retrieval_route_family,
        "retrieval_phase": "open",
        "retrieval_evidence_status": "",
        "retrieval_retry_count": 0,
        "retrieval_close_reason": "",
        "retrieval_validated_arg_keys": list(route_hint.get("validated_arg_keys") or selector_meta.get("validated_arg_keys") or []) if route_hint else [],
        "retrieval_validation_errors": [
            str(item)
            for item in [
                selector_meta.get("validation_error") or route_hint.get("selector_validation_error")
            ]
            if str(item or "").strip()
        ] if route_hint else [],
        "retrieval_fallback_route_ids": list(route_hint.get("fallback_route_ids") or [] if route_hint else []),
        "route_selector_status": str(selector_meta.get("status") or route_hint.get("selector_status") or "") if route_hint else "",
        "route_selector_model": str(selector_meta.get("model") or route_hint.get("selector_model") or "") if route_hint else "",
        "route_selector_latency_ms": selector_latency_ms,
        "route_selector_confidence": str(selector_meta.get("confidence") or route_hint.get("selector_confidence") or "") if route_hint else "",
        "route_selector_reason": str(selector_meta.get("reason") or route_hint.get("selector_reason") or "") if route_hint else "",
        "route_selector_repair_attempted": bool(selector_meta.get("repair_attempted") or route_hint.get("selector_repair_attempted")) if route_hint else False,
        "route_selector_repair_status": str(selector_meta.get("repair_status") or route_hint.get("selector_repair_status") or "") if route_hint else "",
        "route_selector_validation_error_code": str(selector_meta.get("validation_error_code") or route_hint.get("selector_validation_error_code") or "") if route_hint else "",
        "route_selector_validation_error": str(selector_meta.get("validation_error") or route_hint.get("selector_validation_error") or "") if route_hint else "",
        "routing_catalog_version": routing_catalog_version,
        "routing_catalog_origin": routing_catalog_origin,
        "routing_schema_version": routing_schema_version,
        "authoritative_kb_attempt_count": 0,
        "knowledge_route_id": authoritative_route_id,
        "document_id": selected_document_id,
        "source_file_scope": source_file_scope,
        "topic_facets": topic_facets,
        "finalizer_mode": "",
        "explicit_wiki_request": _is_explicit_wiki_request(routing_message),
        "company_fact_intent_type": company_fact_intent_type,
        "corp_db_company_fact_success": False,
        "corp_db_application_success": False,
        "corp_db_portfolio_success": False,
        "doc_search_document_success": False,
        "application_recovery_outcome": "",
        "guardrail_activations": 0,
        "retrieval_tool_used": False,
        "company_fact_payload_relevant": False,
        "company_fact_finalizer_mode": "",
        "company_fact_runtime_payload_format": "",
        "company_fact_bench_payload_format": "",
        "tool_runtime_output_formats": {},
        "tool_bench_output_formats": {},
        "retrieval_attempt_signatures": [],
        "_last_observability_event": "",
    }
    _update_routing_observability(routing_state)

    if _route_selector_enabled() and route_hint:
        primary_tool_name = _route_tool_name(route_hint)
        primary_args = _route_execution_args(route_hint, routing_message)
        if primary_tool_name:
            try:
                routing_state["retrieval_tool_used"] = True
                _record_retrieval_attempt(primary_tool_name, primary_args, routing_state)
                primary_result = await execute_tool(
                    primary_tool_name,
                    primary_args,
                    tool_ctx,
                    tool_call_id="route-selector-primary",
                    tool_call_seq=0,
                )
                if primary_result.success:
                    _record_tool_output_contract(primary_tool_name, primary_result, routing_state)
                    sphere_context_update = _resolved_sphere_context_from_tool(
                        tool_name=primary_tool_name,
                        tool_args=primary_args,
                        tool_result=primary_result,
                        route_hint=route_hint,
                        turn_id=current_turn_id,
                    )
                    if sphere_context_update:
                        _set_session_sphere_context(session, sphere_context_update)
                evidence_status = _route_evidence_status(
                    primary_tool_name,
                    primary_args,
                    primary_result,
                    routing_message,
                    routing_state,
                )
                routing_state["retrieval_evidence_status"] = evidence_status
                routing_state["selected_source"] = "doc_search" if primary_tool_name == "doc_search" else "corp_db"
                routing_state["retrieval_close_reason"] = ""
                short_circuit_response = _short_circuit_application_failure(
                    name=primary_tool_name,
                    args=primary_args,
                    tool_result=primary_result,
                    message=routing_message,
                    routing_state=routing_state,
                )
                if short_circuit_response:
                    return short_circuit_response
                if evidence_status == "sufficient":
                    routing_state["retrieval_phase"] = "closed"
                    routing_state["retrieval_close_reason"] = "route_selector_payload_sufficient"
                    routing_state["finalizer_mode"] = "llm"
                    _update_routing_observability(routing_state)
                    try:
                        final_response = await _finalize_with_scoped_evidence(
                            base_messages=messages,
                            tool_name=primary_tool_name,
                            tool_args=primary_args,
                            tool_result=primary_result,
                            route_hint=route_hint,
                        )
                    except Exception as exc:
                        agent_logger.error(f"Route finalizer unavailable: {exc}")
                        return ROUTE_SELECTOR_UNAVAILABLE_MESSAGE
                    if final_response:
                        return final_response
                else:
                    fallback_response = await _try_controlled_portfolio_fallback(
                        base_messages=messages,
                        message=routing_message,
                        route_hint=route_hint,
                        routing_state=routing_state,
                        tool_ctx=tool_ctx,
                        evidence_status=evidence_status,
                    )
                    if fallback_response:
                        return fallback_response
                    routing_state["retrieval_phase"] = "open"
                    _update_routing_observability(routing_state)
            except Exception as exc:
                agent_logger.error(f"Selected route execution failed: {exc}")
                return ROUTE_SELECTOR_UNAVAILABLE_MESSAGE

    agent_logger.info(f"Available tools for {chat_type}/{source}: {len(tool_definitions)} (lazy={use_lazy_loading})")
    
    max_iter = get_max_iterations()
    while iteration < max_iter:
        iteration += 1
        ctx_chars = sum(len(json.dumps(m)) for m in messages)
        log_agent_step(iteration, max_iter, len(messages), ctx_chars)
        
        # Use search model for final response after search_web was called
        search_model = get_search_model() if has_search_tool and iteration > 1 else ""
        
        # Call LLM (with search model override if applicable)
        result = await call_llm(messages, tool_definitions, model_override=search_model, purpose="agent_loop")
        
        if "error" in result:
            agent_logger.error(f"LLM error: {result['error']}")
            return f"Error: {result['error']}"
        
        choices = result.get("choices", [])
        if not choices:
            return "No response from model"
        
        msg = choices[0].get("message", {})
        finish_reason = choices[0].get("finish_reason")
        
        # Add assistant message to history
        messages.append(msg)
        
        # Check for tool calls
        tool_calls = msg.get("tool_calls") or []
        content = msg.get("content", "") or ""
        
        # If no content and no tool_calls - model didn't finish, continue the loop
        reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
        if not content and not tool_calls:
            if reasoning:
                agent_logger.info(f"[iter {iteration}] No content/tool_calls but has reasoning, adding continue prompt")
                # Add a continue message to prompt model to finish
                messages.append({
                    "role": "user",
                    "content": "[system: continue - выдай tool_call или финальный ответ в content]"
                })
                continue  # Don't break, continue the loop
            else:
                fallback_response = await _deterministic_empty_response_fallback(
                    message=message,
                    route_hint=route_hint,
                    routing_state=routing_state,
                    tool_ctx=tool_ctx,
                    iteration=iteration,
                )
                if fallback_response:
                    agent_logger.warning(f"[iter {iteration}] Empty response from model, deterministic fallback succeeded")
                    final_response = fallback_response
                    break
                agent_logger.warning(f"[iter {iteration}] Empty response from model")
                content = "(no response)"
                break
        
        # Log what we got
        agent_logger.info(f"[iter {iteration}] finish_reason={finish_reason}, tool_calls={len(tool_calls)}, content={len(content) if content else 0} chars")
        if content:
            agent_logger.info(f"[iter {iteration}] CONTENT: {content[:200]}{'...' if len(content) > 200 else ''}")
        
        if tool_calls:
            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                current_tool_call_id = str(tc.get("id") or "")
                tool_call_seq += 1
                raw_args = fn.get("arguments", "{}")
                
                # Track if search_web was called
                if name == "search_web":
                    has_search_tool = True
                
                agent_logger.info(f"[iter {iteration}] TOOL CALL: {name}")
                agent_logger.debug(f"[iter {iteration}] TOOL ARGS RAW: {raw_args}")
                
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError as e:
                    agent_logger.warning(f"[iter {iteration}] TOOL ARGS PARSE ERROR: {e}")
                    # Try to fix common JSON issues from DeepSeek/other models
                    args = try_fix_json_args(raw_args, name)
                    if args is None:
                        agent_logger.error(f"[iter {iteration}] Could not fix JSON args for {name}")
                    args = {}

                if name == "doc_search":
                    document_id = _document_identifier(args)
                    if document_id and not routing_state.get("document_id"):
                        routing_state["document_id"] = document_id
                        _update_routing_observability(routing_state)

                update_correlation_context(
                    tool_name=name,
                    tool_call_id=current_tool_call_id,
                    tool_call_seq=tool_call_seq,
                    tool_status="planned",
                )

                if (
                    name == "corp_db_search"
                    and _has_authoritative_kb_route(routing_state)
                    and int(routing_state.get("authoritative_kb_attempt_count") or 0) < 2
                    and str(args.get("kind") or "hybrid_search") in {"", "hybrid_search"}
                ):
                    args = _rewrite_authoritative_kb_search_args(args, routing_message, routing_state)
                    agent_logger.info(
                        "[iter %s] Rewrote authoritative KB corp_db args route=%s facets=%s query=%s",
                        iteration,
                        routing_state.get("knowledge_route_id") or "",
                        json.dumps(routing_state.get("topic_facets") or [], ensure_ascii=False),
                        args.get("query") or "",
                    )
                elif (
                    name == "corp_db_search"
                    and routing_state["intent"] == "company_fact"
                    and not routing_state["retrieval_tool_used"]
                ):
                    args = _rewrite_company_fact_search_args(args, routing_message)
                    agent_logger.info(
                        "[iter %s] Rewrote company-fact corp_db args subtype=%s query=%s",
                        iteration,
                        routing_state.get("company_fact_intent_type") or "",
                        args.get("query") or "",
                    )
                
                if (
                    _is_skill_or_doc_browse_attempt(name, args)
                    and _has_high_level_retrieval_hint(routing_state)
                ):
                    routing_state["wiki_after_corp_db_success"] = _is_wiki_tool_attempt(name, args)
                    routing_state["guardrail_activations"] += 1
                    _update_routing_observability(routing_state, blocked_tool=name)
                    update_correlation_context(tool_status="blocked")
                    tool_result = ToolResult(False, error=_raw_browse_error(route_hint, name))
                elif _is_duplicate_retrieval_attempt(name, args, routing_state):
                    routing_state["guardrail_activations"] += 1
                    _update_routing_observability(routing_state, blocked_tool=name)
                    update_correlation_context(tool_status="blocked")
                    tool_result = ToolResult(False, error=_duplicate_retrieval_error(name))
                elif _is_wiki_tool_attempt(name, args):
                    if routing_state["corp_db_company_fact_success"] and not routing_state["explicit_wiki_request"]:
                        routing_state["wiki_after_corp_db_success"] = True
                    routing_state["selected_source"] = "doc_search"
                    _update_routing_observability(routing_state)
                    _record_retrieval_attempt(name, args, routing_state)
                    tool_result = await execute_tool(
                        name,
                        args,
                        tool_ctx,
                        tool_call_id=current_tool_call_id,
                        tool_call_seq=tool_call_seq,
                    )
                else:
                    # Execute tool
                    if _is_authoritative_kb_tool_attempt(name, args, routing_state):
                        routing_state["authoritative_kb_attempt_count"] = int(routing_state.get("authoritative_kb_attempt_count") or 0) + 1
                        routing_state["retrieval_retry_count"] = max(0, int(routing_state["authoritative_kb_attempt_count"]) - 1)
                        _update_routing_observability(routing_state)
                    _record_retrieval_attempt(name, args, routing_state)
                    tool_result = await execute_tool(
                        name,
                        args,
                        tool_ctx,
                        tool_call_id=current_tool_call_id,
                        tool_call_seq=tool_call_seq,
                    )

                if _is_retrieval_tool_attempt(name, args):
                    routing_state["retrieval_tool_used"] = True

                agent_logger.info(f"[iter {iteration}] TOOL RESULT: success={tool_result.success}, output={len(tool_result.output or '')} chars, error={tool_result.error or 'none'}")

                bench_artifact = tool_result.metadata.get("bench_artifact") if isinstance(tool_result.metadata, dict) else None
                if tool_result.success and isinstance(bench_artifact, dict):
                    run_meta_append_artifact(bench_artifact)
                if tool_result.success:
                    _record_tool_output_contract(name, tool_result, routing_state)
                    if name == "doc_search":
                        document_id = _document_identifier(args, tool_result.output or "")
                        if document_id and not routing_state.get("document_id"):
                            routing_state["document_id"] = document_id
                            _update_routing_observability(routing_state)
                    sphere_context_update = _resolved_sphere_context_from_tool(
                        tool_name=name,
                        tool_args=args,
                        tool_result=tool_result,
                        route_hint=route_hint,
                        turn_id=current_turn_id,
                    )
                    if sphere_context_update:
                        _set_session_sphere_context(session, sphere_context_update)

                if name == "doc_search" and _is_doc_domain_route(routing_state):
                    evidence_status = _doc_domain_evidence_status(tool_result, args=args, state=routing_state)
                    routing_state["retrieval_evidence_status"] = evidence_status
                    routing_state["retrieval_close_reason"] = ""
                    if tool_result.success:
                        routing_state["selected_source"] = "doc_search"
                    if evidence_status == "sufficient":
                        routing_state["retrieval_phase"] = "closed"
                        routing_state["retrieval_close_reason"] = "doc_search_payload_sufficient"
                        routing_state["finalizer_mode"] = "llm"
                    else:
                        routing_state["retrieval_phase"] = "open"
                    _update_routing_observability(routing_state)

                if name == "corp_db_search" and _is_authoritative_kb_tool_attempt(name, args, routing_state):
                    evidence_status = _authoritative_kb_evidence_status(args, tool_result, routing_message, routing_state)
                    routing_state["retrieval_evidence_status"] = evidence_status
                    routing_state["selected_source"] = "corp_db" if tool_result.success else routing_state["selected_source"]
                    routing_state["retrieval_close_reason"] = ""
                    if evidence_status == "sufficient":
                        routing_state["retrieval_phase"] = "closed"
                        routing_state["retrieval_close_reason"] = "authoritative_payload_sufficient"
                        if (
                            not routing_state["explicit_wiki_request"]
                            and allows_deterministic_primary_finalization(execution_mode)
                        ):
                            if routing_state["intent"] == "company_fact":
                                rendered = _render_deterministic_tool_output(name, args, tool_result.output or "", message)
                            else:
                                rendered = _render_generic_kb_payload(_parse_json_object(tool_result.output or ""))
                            if rendered:
                                routing_state["finalizer_mode"] = "deterministic_primary"
                                _update_routing_observability(routing_state)
                                final_response = rendered
                            else:
                                routing_state["finalizer_mode"] = "llm"
                        else:
                            routing_state["finalizer_mode"] = "llm"
                    else:
                        routing_state["retrieval_phase"] = "open"
                    _update_routing_observability(routing_state)

                company_fact_success = name == "corp_db_search" and _is_successful_company_fact_kb_search(args, tool_result.output or "", message)
                if name == "corp_db_search" and routing_state["intent"] == "company_fact":
                    routing_state["company_fact_payload_relevant"] = company_fact_success
                    if not company_fact_success and tool_result.success:
                        routing_state["company_fact_fallback_reason"] = "weak_company_fact_payload"

                if company_fact_success:
                    routing_state["corp_db_company_fact_success"] = True
                    routing_state["selected_source"] = "corp_db"
                    _update_routing_observability(routing_state)
                    agent_logger.info(
                        "[iter %s] ROUTING selected_source=corp_db intent=%s explicit_wiki=%s",
                        iteration,
                        routing_state["intent"],
                        routing_state["explicit_wiki_request"],
                    )
                    if not routing_state["explicit_wiki_request"]:
                        routing_state["retrieval_phase"] = "closed"
                        routing_state["retrieval_close_reason"] = routing_state.get("retrieval_close_reason") or "authoritative_payload_sufficient"
                        routing_state["company_fact_fast_path"] = True
                        routing_state["company_fact_fallback_reason"] = ""
                        if allows_deterministic_primary_finalization(execution_mode):
                            rendered = _render_deterministic_tool_output(name, args, tool_result.output or "", message)
                            if rendered:
                                routing_state["company_fact_rendered"] = True
                                routing_state["company_fact_finalizer_mode"] = "deterministic_primary"
                                routing_state["finalizer_mode"] = "deterministic_primary"
                                _update_routing_observability(routing_state)
                                final_response = rendered
                            else:
                                routing_state["company_fact_fast_path"] = False
                                routing_state["company_fact_rendered"] = False
                                routing_state["company_fact_finalizer_mode"] = "llm"
                                routing_state["finalizer_mode"] = "llm"
                                _update_routing_observability(routing_state)
                        else:
                            routing_state["company_fact_rendered"] = False
                            routing_state["company_fact_finalizer_mode"] = "llm"
                            routing_state["finalizer_mode"] = "llm"
                            _update_routing_observability(routing_state)
                if name == "corp_db_search" and _is_successful_application_recommendation(args, tool_result.output or "", message):
                    routing_state["corp_db_application_success"] = True
                    routing_state["selected_source"] = "corp_db"
                    _update_routing_observability(routing_state)
                    agent_logger.info(
                        "[iter %s] ROUTING selected_source=corp_db intent=%s application_fast_path=true",
                        iteration,
                        routing_state["intent"],
                    )
                if name == "corp_db_search" and _is_successful_portfolio_by_sphere(args, tool_result.output or "", message):
                    routing_state["corp_db_portfolio_success"] = True
                    routing_state["selected_source"] = "corp_db"
                    _update_routing_observability(routing_state)
                    agent_logger.info(
                        "[iter %s] ROUTING selected_source=corp_db intent=%s portfolio_lookup=true",
                        iteration,
                        routing_state["intent"],
                    )
                if _is_successful_document_lookup(name, args, tool_result.output or "", message):
                    routing_state["doc_search_document_success"] = True
                    routing_state["selected_source"] = "doc_search"
                    _update_routing_observability(routing_state)
                    agent_logger.info(
                        "[iter %s] ROUTING selected_source=doc_search intent=%s document_lookup=true",
                        iteration,
                        routing_state["intent"],
                    )

                short_circuit_response = _short_circuit_application_failure(
                    name=name,
                    args=args,
                    tool_result=tool_result,
                    message=message,
                    routing_state=routing_state,
                )
                if short_circuit_response:
                    final_response = short_circuit_response
                    break

                # Dynamic tool loading: merge new definitions into active toolkit
                if name == "load_tools" and tool_result.success and tool_result.metadata:
                    new_tools = tool_result.metadata.get("loaded_tools", [])
                    if new_tools:
                        existing_names = {t["function"]["name"] for t in tool_definitions}
                        added = 0
                        for t in new_tools:
                            tname = t["function"]["name"]
                            if tname not in existing_names:
                                tool_definitions.append(t)
                                existing_names.add(tname)
                                added += 1
                        if added:
                            agent_logger.info(f"[iter {iteration}] Dynamic toolkit: +{added} tools → {len(tool_definitions)} total")
                
                # Track SECURITY violations only (not privilege/capability limits)
                # Categories that are actual security threats vs just sandbox limitations
                error_msg = tool_result.error or ""
                is_security_violation = (
                    "BLOCKED" in error_msg and 
                    any(threat in error_msg.lower() for threat in [
                        "secret", "env", "token", "key", "password", "credential",
                        "injection", "/etc/passwd", "/etc/shadow", "proc/self",
                        "base64", "exfiltration", "fork bomb", "rm -rf"
                    ])
                )
                
                if is_security_violation:
                    session.blocked_count += 1
                    agent_logger.warning(f"Security violation detected: {error_msg[:100]}")
                    if session.blocked_count >= CONFIG.max_blocked_commands:
                        agent_logger.warning(f"Too many security violations: {session.blocked_count}")
                        return "🚫 Session locked due to repeated security violations. /clear to reset."
                
                # Add tool result
                output = (tool_result.output or "(empty)") if tool_result.success else f"Error: {tool_result.error or 'Unknown error'}"
                
                # Trim long output
                if len(output) > CONFIG.max_tool_output:
                    head = output[:int(CONFIG.max_tool_output * 0.6)]
                    tail = output[-int(CONFIG.max_tool_output * 0.3):]
                    output = f"{head}\n\n... [TRIMMED] ...\n\n{tail}"
                
                # Add language reminder after tool results to enforce response language
                if tool_result.success:
                    lang_reminder = _get_language_reminder()
                    if lang_reminder:
                        output += lang_reminder
                
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id"),
                    "content": output
                })
                if final_response:
                    break
            if final_response:
                break
        
        else:
            # No tool calls - this is the final response
            agent_logger.info(f"[iter {iteration}] FINAL RESPONSE (no tool calls)")
            if str(routing_state.get("retrieval_phase") or "") == "closed":
                routing_state["finalizer_mode"] = routing_state.get("finalizer_mode") or "llm"
            if (
                routing_state["intent"] == "company_fact"
                and routing_state["corp_db_company_fact_success"]
                and not routing_state["explicit_wiki_request"]
            ):
                routing_state["company_fact_finalizer_mode"] = routing_state.get("company_fact_finalizer_mode") or "llm"
                routing_state["finalizer_mode"] = routing_state.get("finalizer_mode") or "llm"
                _update_routing_observability(routing_state)
            else:
                _update_routing_observability(routing_state)
            final_response = content
            
            # Debug: if content empty but tokens used, log raw message
            if not content:
                agent_logger.warning(f"[iter {iteration}] Empty content! Raw message: {json.dumps(msg, ensure_ascii=False)[:500]}")
            break
        
        if finish_reason == "stop" and not tool_calls:
            final_response = msg.get("content", "")
            break
    
    # Fallback: if no response but had successful tool calls, generate summary
    # BUT: don't use fallback if last tool result was an error
    if not final_response and iteration > 1:
        # Check if last tool result was an error
        last_tool_result = None
        for m in reversed(messages):
            if m.get("role") == "tool":
                last_tool_result = m.get("content", "")
                break
        
        # If last tool failed, don't fallback - let user see the error context
        if last_tool_result and last_tool_result.startswith("Error:"):
            agent_logger.info(f"[fallback] Skipped - last tool failed: {last_tool_result[:100]}")
            final_response = f"Ошибка: {last_tool_result[7:200]}"  # Show error to user
        else:
            # Look for successful tool results
            tool_outputs = []
            for m in messages:
                if m.get("role") == "tool":
                    content = m.get("content", "")
                    if content and not content.startswith("Error:"):
                        first_line = content.split('\n')[0][:100]
                        if first_line and first_line != "(empty)":
                            tool_outputs.append(first_line)
            
            if tool_outputs:
                final_response = f"Готово! {tool_outputs[-1]}" if len(tool_outputs) == 1 else "✅ Готово"
                agent_logger.info(f"[fallback] Generated response from tool outputs")
    
    # Save to history
    session.history.append({"role": "user", "content": message})
    if final_response:
        session.history.append({"role": "assistant", "content": final_response})
    
    # Trim history
    session.history = trim_history(session.history, CONFIG.max_history * 2, 30000)
    
    # Save to file for admin panel
    save_session_to_file(session)
    
    final_response = clean_response(final_response)
    agent_logger.info(f"Response: {final_response[:100]}...")
    
    return final_response or "(no response)"
