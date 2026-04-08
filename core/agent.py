"""ReAct Agent implementation"""

import asyncio
import os
import json
import re
import aiohttp
from datetime import datetime
from dataclasses import dataclass
from time import perf_counter
from typing import Optional, Any
from pathlib import Path

from config import CONFIG, get_model, get_temperature, get_max_iterations
from documents.routing import select_route_card
from logger import agent_logger, log_agent_step
from observability import REQUEST_ID as OBS_REQUEST_ID
from run_meta import run_meta_append_artifact, run_meta_get, run_meta_update_llm
from tools import execute_tool, filter_tools_for_session
from models import ToolContext, ToolResult
from opentelemetry import trace

# Cache for tool definitions
_tools_cache = None
_tools_cache_time = 0
TOOLS_CACHE_TTL = 60  # seconds

# Cache for userbot availability
_userbot_available_cache = None
_userbot_check_time = 0
USERBOT_CHECK_TTL = 30  # seconds

COMPANY_FACT_KEYWORDS = (
    "сайт", "официальный сайт", "адрес", "головной офис", "контак", "телефон",
    "email", "e-mail", "почт", "реквизит", "инн", "кпп", "огрн", "соцсет", "телеграм",
    "telegram", "youtube", "ютуб", "vk", "вконтакте", "канал", "год основания",
    "основан", "основана", "сколько лет компании", "о компании", "общая информация о компании",
    "гаранти", "сервис", "консультац",
)
COMPANY_FACT_INTENT_KEYWORDS = {
    "requisites": ("реквизит", "инн", "кпп", "огрн"),
    "year_founded": ("сколько лет", "год основания", "основан", "основана", "история компании"),
    "website": ("официальный сайт", "сайт"),
    "address": ("головной офис", "адрес", "офис", "где находится"),
    "socials": ("соцсет", "телеграм", "telegram", "youtube", "ютуб", "vk", "вконтакте", "канал"),
    "contacts": ("контакт", "телефон", "email", "e-mail", "почт", "связат", "консультац"),
    "about_company": ("о компании", "общая информация о компании", "расскажи о компании", "чем занимается компания", "наш профиль"),
}
DOCUMENT_LOOKUP_KEYWORDS = (
    "сертификат", "пожарный сертификат", "ce", "pdf", "паспорт", "документ",
    "закаленное стекло", "закалённое стекло", "закал", "стекл",
    "чем отличается серия", "отличается серия", "отличие между серией",
)
PORTFOLIO_LOOKUP_KEYWORDS = (
    "портфолио", "пример проекта", "пример объекта", "примеры реализации",
    "какие проекты были", "где применялся", "покажи проекты", "покажи объект",
)
APPLICATION_RECOMMENDATION_KEYWORDS = (
    "стадион", "арена", "спорткомплекс", "футболь", "карьер", "рудник", "гок",
    "аэропорт", "апрон", "перрон", "склад", "логист", "высокие прол", "high-bay",
    "high bay", "офис", "кабинет", "абк", "агрессивн", "мойка", "азс",
)

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


def _normalize_routing_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def _text_has_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _is_explicit_wiki_request(message: str) -> bool:
    return _text_has_any(_normalize_routing_text(message), EXPLICIT_WIKI_KEYWORDS)


def _is_document_lookup_intent(message: str) -> bool:
    return _text_has_any(_normalize_routing_text(message), DOCUMENT_LOOKUP_KEYWORDS)


def _is_portfolio_lookup_intent(message: str) -> bool:
    normalized = _normalize_routing_text(message)
    return _text_has_any(normalized, PORTFOLIO_LOOKUP_KEYWORDS) and _text_has_any(
        normalized,
        APPLICATION_RECOMMENDATION_KEYWORDS + ("наружн", "уличн", "дорожн", "промышлен", "тяжел"),
    )


def _is_company_fact_intent(message: str) -> bool:
    return bool(_company_fact_intent_type(message))


def _company_fact_intent_type(message: str) -> str:
    normalized = _normalize_routing_text(message)
    if _is_document_lookup_intent(normalized) or _is_portfolio_lookup_intent(normalized) or _is_application_recommendation_intent(normalized):
        return ""
    for subtype in ("requisites", "year_founded", "website", "address", "socials", "contacts", "about_company"):
        if _text_has_any(normalized, COMPANY_FACT_INTENT_KEYWORDS[subtype]):
            return subtype
    if _text_has_any(normalized, COMPANY_FACT_KEYWORDS):
        return "about_company"
    return ""


def _is_application_recommendation_intent(message: str) -> bool:
    return _text_has_any(_normalize_routing_text(message), APPLICATION_RECOMMENDATION_KEYWORDS)


def _parse_json_object(raw_text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_text or "")
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _company_fact_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("results")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _collect_row_texts(rows: list[dict[str, Any]]) -> list[str]:
    texts: list[str] = []
    for row in rows:
        for key in ("heading", "title", "document_title", "preview", "snippet", "value", "source_file"):
            value = str(row.get(key) or "").strip()
            if value:
                texts.append(value)
    return texts


def _collect_preview_texts(payload: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for row in _company_fact_rows(payload):
        preview = str(row.get("preview") or row.get("snippet") or row.get("value") or "").strip()
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
    return _texts_contain_any(texts, ("о компании", "наш профиль", "о заводе", "об организации"))


def _is_successful_company_fact_kb_search(args: dict, tool_output: str, message: str) -> bool:
    if str(args.get("kind") or "") != "hybrid_search":
        return False
    if str(args.get("profile") or "") != "kb_search":
        return False

    payload = _parse_json_object(tool_output)
    entity_types = args.get("entity_types") or []
    if not (
        (isinstance(entity_types, list) and any(str(item).lower() == "company" for item in entity_types))
        or _is_company_fact_intent(message)
        or _text_has_any(_normalize_routing_text(args.get("query")), COMPANY_FACT_KEYWORDS)
    ):
        return False
    return _company_fact_payload_is_relevant(payload, message)


def _is_successful_application_recommendation(args: dict, tool_output: str, message: str) -> bool:
    if str(args.get("kind") or "") != "application_recommendation":
        return False
    payload = _parse_json_object(tool_output)
    status = str(payload.get("status") or "")
    if status not in {"success", "needs_clarification"}:
        return False
    if _is_application_recommendation_intent(message):
        return True
    query = _normalize_routing_text(args.get("query"))
    return _text_has_any(query, APPLICATION_RECOMMENDATION_KEYWORDS)


def _is_successful_portfolio_by_sphere(args: dict, tool_output: str, message: str) -> bool:
    if str(args.get("kind") or "") != "portfolio_by_sphere":
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
    return isinstance(results, list) and len(results) > 0


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
    return kind in {"hybrid_search", "category_lamps", "sphere_categories", "portfolio_by_sphere", "lamp_filters"}


def _is_portfolio_fallback_attempt(name: str, args: dict) -> bool:
    if _is_wiki_tool_attempt(name, args):
        return True
    if name != "corp_db_search":
        return False
    kind = str(args.get("kind") or "")
    return kind in {"hybrid_search", "application_recommendation", "category_lamps", "sphere_categories"}


def _is_document_fallback_attempt(name: str, args: dict) -> bool:
    if name == "corp_db_search":
        return True
    return False


def _is_retrieval_tool_attempt(name: str, args: dict) -> bool:
    if name == "corp_db_search":
        return True
    return _is_wiki_tool_attempt(name, args)


def _preferred_source_error(route_hint: dict[str, Any], attempted_tool: str) -> str:
    source = str(route_hint.get("source") or "")
    tool_name = str(route_hint.get("tool_name") or "")
    tool_args = route_hint.get("tool_args") or {}
    route_id = str(route_hint.get("route_id") or "")
    if source == "corp_db":
        return (
            f"Routing index selected `{route_id}` -> `{tool_name}` before `{attempted_tool}`. "
            f"Сначала вызови `{tool_name}` с args {json.dumps(tool_args, ensure_ascii=False)}."
        )
    if source == "doc_search":
        return (
            f"Routing index selected `{route_id}` -> `{tool_name}` before `{attempted_tool}`. "
            "Сначала используй `doc_search`, потому что вопрос относится к document corpus."
        )
    return ""


def _route_hint_blocks_tool_attempt(route_hint: dict[str, Any] | None, name: str, args: dict, *, explicit_wiki_request: bool) -> bool:
    if not route_hint:
        return False
    source = str(route_hint.get("source") or "")
    route_id = str(route_hint.get("route_id") or "")
    if source == "corp_db":
        if route_id == "corp_db.company_profile" and not explicit_wiki_request and _is_skill_or_doc_browse_attempt(name, args):
            return True
        return not explicit_wiki_request and _is_wiki_tool_attempt(name, args)
    if source == "doc_search":
        return name == "corp_db_search"
    return False


def _update_routing_observability(state: dict[str, Any], *, blocked_tool: str = "") -> None:
    meta = run_meta_get()
    if isinstance(meta, dict):
        meta["retrieval_intent"] = str(state.get("intent") or "")
        meta["retrieval_selected_source"] = str(state.get("selected_source") or "unknown")
        meta["retrieval_route_id"] = str(state.get("route_id") or "")
        meta["retrieval_route_source"] = str(state.get("route_source") or "")
        meta["retrieval_route_score"] = int(state.get("route_score") or 0)
        meta["retrieval_explicit_wiki_request"] = bool(state.get("explicit_wiki_request"))
        meta["retrieval_wiki_after_corp_db_success"] = bool(state.get("wiki_after_corp_db_success"))
        meta["routing_guardrail_hits"] = int(state.get("guardrail_activations", 0))
        meta["company_fact_intent_type"] = str(state.get("company_fact_intent_type") or "")
        meta["company_fact_fast_path"] = bool(state.get("company_fact_fast_path"))
        meta["company_fact_payload_relevant"] = bool(state.get("company_fact_payload_relevant"))
        meta["company_fact_rendered"] = bool(state.get("company_fact_rendered"))
        meta["company_fact_fallback_reason"] = str(state.get("company_fact_fallback_reason") or "")
        if blocked_tool:
            meta["routing_guardrail_last_blocked_tool"] = blocked_tool

    span = trace.get_current_span()
    try:
        span.set_attribute("retrieval.intent", str(state.get("intent") or ""))
        span.set_attribute("retrieval.selected_source", str(state.get("selected_source") or "unknown"))
        span.set_attribute("retrieval.route_id", str(state.get("route_id") or ""))
        span.set_attribute("retrieval.route_source", str(state.get("route_source") or ""))
        span.set_attribute("retrieval.route_score", int(state.get("route_score") or 0))
        span.set_attribute("retrieval.explicit_wiki_request", bool(state.get("explicit_wiki_request")))
        span.set_attribute("retrieval.wiki_after_corp_db_success", bool(state.get("wiki_after_corp_db_success")))
        span.set_attribute("retrieval.guardrail_hits", int(state.get("guardrail_activations", 0)))
        span.set_attribute("company_fact.intent_type", str(state.get("company_fact_intent_type") or ""))
        span.set_attribute("company_fact.fast_path", bool(state.get("company_fact_fast_path")))
        span.set_attribute("company_fact.payload_relevant", bool(state.get("company_fact_payload_relevant")))
        span.set_attribute("company_fact.rendered", bool(state.get("company_fact_rendered")))
        span.set_attribute("company_fact.fallback_reason", str(state.get("company_fact_fallback_reason") or ""))
        if blocked_tool:
            span.set_attribute("retrieval.guardrail_last_blocked_tool", blocked_tool)
    except Exception:
        return None


def _looks_like_contact_intent(message: str) -> bool:
    return _company_fact_intent_type(message) == "contacts"


def _expand_company_fact_query(message: str) -> str:
    subtype = _company_fact_intent_type(message)
    if subtype == "year_founded":
        return "Сколько лет компании ЛАДзавод светотехники? Если точный возраст не знаешь, назови год основания."
    if subtype == "website":
        return "официальный сайт компании ЛАДзавод светотехники"
    if subtype == "address":
        return "челябинск чайковского 3 адрес офиса ladzavod"
    if subtype == "requisites":
        return "реквизиты компании ладзавод инн кпп огрн"
    if subtype == "socials":
        return "telegram youtube vk соцсети ladzavod"
    normalized = _normalize_routing_text(message)
    if _text_has_any(normalized, ("консультац", "расчет", "расчёт", "освещен", "освещён")):
        return "lad@ladled.ru 239-18-11 консультация расчет освещенности"
    if subtype == "contacts":
        return "239-18-11 lad@ladled.ru контакты ladzavod"
    if subtype == "about_company":
        return "общая информация о компании ЛАДзавод светотехники"
    return message


def _contact_doc_search_query(message: str) -> str:
    normalized = _normalize_routing_text(message)
    if _text_has_any(normalized, ("email", "e-mail", "почт")):
        return "lad@ladled.ru"
    if _text_has_any(normalized, ("телефон", "позвон", "связат")):
        return "239-18-11"
    return "lad@ladled.ru"


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
    if subtype == "about_company":
        heading_keywords = ("о компании", "наш профиль", "о заводе", "об организации")
    elif subtype in {"contacts", "address"}:
        heading_keywords = ("контактная информация", "контакты")
    elif subtype == "requisites":
        heading_keywords = ("реквизиты",)
    elif subtype == "socials":
        heading_keywords = ("социальные сети",)

    if heading_keywords:
        preferred_rows = [
            row
            for row in rows
            if _texts_contain_any(_collect_row_texts([row]), heading_keywords)
        ]
        if preferred_rows:
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


def _rewrite_company_fact_search_args(args: dict[str, Any], message: str) -> dict[str, Any]:
    rewritten: dict[str, Any] = {}
    for key in ("limit", "offset"):
        value = args.get(key)
        if isinstance(value, int) and value > 0:
            rewritten[key] = value
    if bool(args.get("include_debug")):
        rewritten["include_debug"] = True
    rewritten["kind"] = "hybrid_search"
    rewritten["profile"] = "kb_search"
    rewritten["entity_types"] = ["company"]
    rewritten["query"] = _expand_company_fact_query(message)
    return rewritten


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
                    args = _rewrite_company_fact_search_args(args, message)
                elif kind in {"application_recommendation", "portfolio_by_sphere", "lamp_exact"}:
                    args["query"] = message
                    if kind == "portfolio_by_sphere":
                        args.setdefault("fuzzy", True)
            return tool_name, args

    intent = str(routing_state.get("intent") or "other")
    if intent == "company_fact":
        return (
            "corp_db_search",
            _rewrite_company_fact_search_args({}, message),
        )
    if intent == "document_lookup":
        return ("doc_search", {"query": message, "top": 5})
    if intent == "portfolio_lookup":
        return ("corp_db_search", {"kind": "portfolio_by_sphere", "query": message, "fuzzy": True})
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
    tool_result = await execute_tool(name, args, tool_ctx)
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

    rendered = _render_deterministic_tool_output(name, args, tool_result.output or "", message)
    if not rendered and name == "corp_db_search" and _looks_like_contact_intent(message):
        routing_state["company_fact_fallback_reason"] = "weak_contact_payload"
        doc_args = {"query": _contact_doc_search_query(message), "top": 5}
        agent_logger.warning(
            "[iter %s] Empty contact payload after corp_db fallback, executing doc_search with args=%s",
            iteration,
            json.dumps(doc_args, ensure_ascii=False),
        )
        doc_result = await execute_tool("doc_search", doc_args, tool_ctx)
        if doc_result.success:
            bench_artifact = doc_result.metadata.get("bench_artifact") if isinstance(doc_result.metadata, dict) else None
            if isinstance(bench_artifact, dict):
                run_meta_append_artifact(bench_artifact)
            rendered = _render_deterministic_tool_output("doc_search", doc_args, doc_result.output or "", message)
            if rendered:
                routing_state["selected_source"] = "doc_search"
                routing_state["doc_search_document_success"] = True
                routing_state["company_fact_rendered"] = True
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
            routing_state["company_fact_rendered"] = True
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


@dataclass
class Session:
    """User session"""
    user_id: int
    chat_id: int
    cwd: str
    history: list
    blocked_count: int = 0
    source: str = "bot"  # 'bot' or 'userbot'


class SessionManager:
    """Manage user sessions"""
    def __init__(self):
        self.sessions: dict[str, Session] = {}
    
    def get_key(self, user_id: int, chat_id: int) -> str:
        return f"{user_id}_{chat_id}"
    
    def get(self, user_id: int, chat_id: int) -> Session:
        key = self.get_key(user_id, chat_id)
        
        if key not in self.sessions:
            cwd = os.path.join(CONFIG.workspace, str(user_id))
            os.makedirs(cwd, exist_ok=True)
            # Ensure directory is writable (for bind mounts)
            try:
                os.chmod(cwd, 0o777)
            except:
                pass
            
            self.sessions[key] = Session(
                user_id=user_id,
                chat_id=chat_id,
                cwd=cwd,
                history=[]
            )
            agent_logger.info(f"New session: {key}")
        
        return self.sessions[key]
    
    def clear(self, user_id: int, chat_id: int):
        key = self.get_key(user_id, chat_id)
        if key in self.sessions:
            self.sessions[key].history = []
            self.sessions[key].blocked_count = 0
            agent_logger.info(f"Session cleared: {key}")


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


def _llm_max_attempts() -> int:
    """Maximum number of attempts for transient LLM failures."""
    try:
        return max(1, int(os.getenv("LLM_MAX_ATTEMPTS", "3")))
    except ValueError:
        return 3


def _llm_retry_delay(attempt: int) -> float:
    """Linear retry backoff in seconds."""
    try:
        base_delay = float(os.getenv("LLM_RETRY_BASE_DELAY_S", "0.75"))
    except ValueError:
        base_delay = 0.75
    return max(0.0, base_delay * max(1, attempt))


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


async def call_llm(messages: list, tools: list, model_override: str = "") -> dict:
    """Call LLM via proxy. model_override allows using a different model (e.g. for search responses)."""
    if not CONFIG.proxy_url:
        return {"error": "No proxy configured"}
    
    # Check context size - MLX struggles with very large contexts
    context_size = estimate_context_size(messages)
    max_context = int(os.getenv("MAX_CONTEXT_CHARS", "40000"))
    
    if context_size > max_context:
        agent_logger.warning(f"Context too large ({context_size} chars > {max_context}), trimming...")
        # Keep system message and trim history
        system_msg = messages[0] if messages and messages[0].get("role") == "system" else None
        user_msg = messages[-1] if messages and messages[-1].get("role") == "user" else None
        
        if system_msg and user_msg:
            # Keep only system + last few messages + user
            middle = messages[1:-1]
            while estimate_context_size([system_msg] + middle + [user_msg]) > max_context and len(middle) > 2:
                middle.pop(0)
            messages = [system_msg] + middle + [user_msg]
            agent_logger.info(f"Trimmed context to {estimate_context_size(messages)} chars")
    
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
    headers = {"X-Request-Id": request_id} if request_id and request_id != "-" else {}
    llm_started = perf_counter()
    max_attempts = _llm_max_attempts()

    for attempt in range(1, max_attempts + 1):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{CONFIG.proxy_url}/v1/chat/completions",
                    json=request_body,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=120)
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
    source: str = "bot"
) -> str:
    """Run ReAct agent loop"""
    session = sessions.get(user_id, chat_id)
    session.source = source
    
    # Check if user is admin (bypasses some security patterns)
    is_admin = (user_id == _get_admin_id())
    
    agent_logger.info(f"Agent run: user={user_id}, chat={chat_id}, source={source}, admin={is_admin}")
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
    
    # Add Google email if authorized (admin-only)
    google_email = get_google_email()
    if google_email:
        workspace_info += f"\nGoogle: {google_email} (authorized, use as user_google_email for Google Workspace tools)"
    
    route_hint = select_route_card(message)
    if route_hint:
        workspace_info += (
            "\nRouting hint: "
            f"route_id={route_hint.get('route_id')} "
            f"preferred_source={route_hint.get('source')} "
            f"tool={route_hint.get('tool_name')} "
            f"tool_args={json.dumps(route_hint.get('tool_args') or {}, ensure_ascii=False)}"
        )

    messages = [{"role": "system", "content": system_prompt + workspace_info}]
    messages.extend(session.history)
    messages.append({"role": "user", "content": message})
    
    # Trim if needed
    messages = [messages[0]] + trim_history(messages[1:], CONFIG.max_context_messages, 50000)
    
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
    has_search_tool = False  # Track if search_web was called
    company_fact_intent_type = _company_fact_intent_type(message)
    routing_state = {
        "intent": (
            "document_lookup"
            if _is_document_lookup_intent(message)
            else "portfolio_lookup"
            if _is_portfolio_lookup_intent(message)
            else "application_recommendation"
            if _is_application_recommendation_intent(message)
            else "company_fact"
            if bool(company_fact_intent_type)
            else "other"
        ),
        "selected_source": "unknown",
        "route_id": str(route_hint.get("route_id") or "") if route_hint else "",
        "route_source": str(route_hint.get("source") or "") if route_hint else "",
        "route_score": int(route_hint.get("score") or 0) if route_hint else 0,
        "explicit_wiki_request": _is_explicit_wiki_request(message),
        "company_fact_intent_type": company_fact_intent_type,
        "corp_db_company_fact_success": False,
        "corp_db_application_success": False,
        "corp_db_portfolio_success": False,
        "doc_search_document_success": False,
        "wiki_after_corp_db_success": False,
        "guardrail_activations": 0,
        "retrieval_tool_used": False,
        "company_fact_fast_path": False,
        "company_fact_payload_relevant": False,
        "company_fact_rendered": False,
        "company_fact_fallback_reason": "",
    }
    _update_routing_observability(routing_state)
    
    agent_logger.info(f"Available tools for {chat_type}/{source}: {len(tool_definitions)} (lazy={use_lazy_loading})")
    
    max_iter = get_max_iterations()
    while iteration < max_iter:
        iteration += 1
        ctx_chars = sum(len(json.dumps(m)) for m in messages)
        log_agent_step(iteration, max_iter, len(messages), ctx_chars)
        
        # Use search model for final response after search_web was called
        search_model = get_search_model() if has_search_tool and iteration > 1 else ""
        
        # Call LLM (with search model override if applicable)
        result = await call_llm(messages, tool_definitions, model_override=search_model)
        
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

                if (
                    name == "corp_db_search"
                    and routing_state["intent"] == "company_fact"
                    and not routing_state["retrieval_tool_used"]
                ):
                    args = _rewrite_company_fact_search_args(args, message)
                    agent_logger.info(
                        "[iter %s] Rewrote company-fact corp_db args subtype=%s query=%s",
                        iteration,
                        routing_state.get("company_fact_intent_type") or "",
                        args.get("query") or "",
                    )
                
                if routing_state["corp_db_application_success"] and not routing_state["explicit_wiki_request"] and _is_application_fallback_attempt(name, args):
                    routing_state["wiki_after_corp_db_success"] = _is_wiki_tool_attempt(name, args)
                    routing_state["guardrail_activations"] += 1
                    _update_routing_observability(routing_state, blocked_tool=name)
                    agent_logger.warning(
                        "[iter %s] ROUTING GUARDRAIL blocked %s after successful corp_db application recommendation",
                        iteration,
                        name,
                    )
                    tool_result = ToolResult(
                        False,
                        error=(
                            "Routing guardrail: `corp_db_search(kind=application_recommendation)` already returned the answer contract "
                            "for this broad-object request. Answer from that payload unless the user explicitly asks for wiki/document context."
                        ),
                    )
                elif routing_state["doc_search_document_success"] and _is_document_fallback_attempt(name, args):
                    routing_state["guardrail_activations"] += 1
                    _update_routing_observability(routing_state, blocked_tool=name)
                    agent_logger.warning(
                        "[iter %s] ROUTING GUARDRAIL blocked %s after successful doc_search document lookup",
                        iteration,
                        name,
                    )
                    tool_result = ToolResult(
                        False,
                        error=(
                            "Routing guardrail: `doc_search` already returned confirmed document evidence for this question. "
                            "Answer from that payload unless the user explicitly asks for an additional structured corp_db lookup."
                        ),
                    )
                elif routing_state["corp_db_portfolio_success"] and not routing_state["explicit_wiki_request"] and _is_portfolio_fallback_attempt(name, args):
                    routing_state["wiki_after_corp_db_success"] = _is_wiki_tool_attempt(name, args)
                    routing_state["guardrail_activations"] += 1
                    _update_routing_observability(routing_state, blocked_tool=name)
                    agent_logger.warning(
                        "[iter %s] ROUTING GUARDRAIL blocked %s after successful corp_db portfolio lookup",
                        iteration,
                        name,
                    )
                    tool_result = ToolResult(
                        False,
                        error=(
                            "Routing guardrail: `corp_db_search(kind=portfolio_by_sphere)` already returned confirmed portfolio examples "
                            "for this query. Answer from that payload unless the user explicitly asks for wiki/document context."
                        ),
                    )
                elif (
                    not routing_state["retrieval_tool_used"]
                    and route_hint
                    and str(route_hint.get("route_id") or "") == "corp_db.company_profile"
                    and not routing_state["explicit_wiki_request"]
                    and _is_skill_or_doc_browse_attempt(name, args)
                ):
                    routing_state["guardrail_activations"] += 1
                    _update_routing_observability(routing_state, blocked_tool=name)
                    tool_result = ToolResult(False, error=_preferred_source_error(route_hint or {}, name))
                elif (
                    not routing_state["retrieval_tool_used"]
                    and _is_retrieval_tool_attempt(name, args)
                    and _route_hint_blocks_tool_attempt(route_hint, name, args, explicit_wiki_request=routing_state["explicit_wiki_request"])
                ):
                    routing_state["guardrail_activations"] += 1
                    _update_routing_observability(routing_state, blocked_tool=name)
                    tool_result = ToolResult(False, error=_preferred_source_error(route_hint or {}, name))
                elif _is_wiki_tool_attempt(name, args):
                    if routing_state["corp_db_company_fact_success"] and not routing_state["explicit_wiki_request"]:
                        routing_state["wiki_after_corp_db_success"] = True
                        routing_state["guardrail_activations"] += 1
                        _update_routing_observability(routing_state, blocked_tool=name)
                        agent_logger.warning(
                            "[iter %s] ROUTING GUARDRAIL blocked %s after successful corp_db company-fact answer",
                            iteration,
                            name,
                        )
                        tool_result = ToolResult(
                            False,
                            error=(
                                "Routing guardrail: `corp_db_search` already returned a confirmed company-fact answer. "
                                "Answer from corp_db unless the user explicitly asks for wiki/document context."
                            ),
                        )
                    else:
                        routing_state["selected_source"] = "doc_search"
                        _update_routing_observability(routing_state)
                        tool_result = await execute_tool(name, args, tool_ctx)
                else:
                    # Execute tool
                    tool_result = await execute_tool(name, args, tool_ctx)

                if _is_retrieval_tool_attempt(name, args):
                    routing_state["retrieval_tool_used"] = True

                agent_logger.info(f"[iter {iteration}] TOOL RESULT: success={tool_result.success}, output={len(tool_result.output or '')} chars, error={tool_result.error or 'none'}")

                bench_artifact = tool_result.metadata.get("bench_artifact") if isinstance(tool_result.metadata, dict) else None
                if tool_result.success and isinstance(bench_artifact, dict):
                    run_meta_append_artifact(bench_artifact)

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
                        rendered = _render_deterministic_tool_output(name, args, tool_result.output or "", message)
                        if rendered:
                            routing_state["company_fact_fast_path"] = True
                            routing_state["company_fact_rendered"] = True
                            routing_state["company_fact_fallback_reason"] = ""
                            _update_routing_observability(routing_state)
                            final_response = rendered
                            break
                        routing_state["company_fact_fallback_reason"] = "company_fact_renderer_empty"
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
