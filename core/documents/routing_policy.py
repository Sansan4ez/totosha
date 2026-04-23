"""Shared deterministic routing policy helpers."""

from __future__ import annotations

import re
from typing import Any


COMPANY_FACT_KEYWORDS = (
    "сайт", "официальный сайт", "адрес", "головной офис", "контак", "телефон",
    "email", "e-mail", "почт", "реквизит", "инн", "кпп", "огрн", "соцсет", "телеграм",
    "telegram", "youtube", "ютуб", "vk", "вконтакте", "канал", "год основания",
    "основан", "основана", "сколько лет компании", "о компании", "общая информация о компании",
    "гаранти", "сервис", "консультац", "сертифик", "декларац", "экспертиз", "сертификац",
    "качеств", "комплектующ", "надежн", "надёжн",
)
COMPANY_FACT_INTENT_KEYWORDS = {
    "requisites": ("реквизит", "инн", "кпп", "огрн"),
    "year_founded": ("сколько лет", "год основания", "основан", "основана", "история компании"),
    "website": ("официальный сайт", "сайт"),
    "address": ("головной офис", "адрес", "офис", "где находится"),
    "socials": ("соцсет", "телеграм", "telegram", "youtube", "ютуб", "vk", "вконтакте", "канал"),
    "contacts": ("контакт", "телефон", "email", "e-mail", "почт", "связат", "консультац"),
    "about_company": ("о компании", "общая информация о компании", "расскажи о компании", "чем занимается компания", "наш профиль"),
    "certification": ("сертифик", "декларац", "экспертиз", "сертификац"),
    "quality": ("качеств", "комплектующ", "надежн", "надёжн"),
}
COMPANY_COMMON_FACET_BY_SUBTYPE = {
    "requisites": "requisites",
    "year_founded": "about_company",
    "website": "contacts",
    "address": "contacts",
    "socials": "socials",
    "contacts": "contacts",
    "about_company": "about_company",
    "certification": "certification",
    "quality": "quality",
}
COMPANY_COMMON_FACET_KEYWORDS = {
    "certification": ("сертифик", "декларац", "экспертиз", "сертификац"),
    "news": ("новост",),
    "legal": ("правов", "юридическ", "договор", "политик"),
    "price": ("прайс", "цена", "стоимост"),
    "lighting_calculation": ("расчет освещ", "расчёт освещ", "освещен", "освещён"),
    "fire_hazard_zones": ("пожароопас", "пожарная зона", "пожароопасных зон"),
    "quality": ("качеств", "комплектующ", "надежн", "надёжн"),
    "series": ("серии", "серия", "линейк", "модел"),
}
DOCUMENT_LOOKUP_KEYWORDS = (
    "пожарный сертификат", "сертификат ce", "ce", "pdf", "паспорт", "документ",
    "закаленное стекло", "закалённое стекло", "закал", "стекл",
    "чем отличается серия", "отличается серия", "отличие между серией",
)
PORTFOLIO_LOOKUP_KEYWORDS = (
    "портфолио", "пример проекта", "пример объекта", "примеры реализации",
    "какие проекты были", "где применялся", "покажи проекты", "покажи объект",
    "проект", "проекты", "реализован", "реализация",
    "ржд", "логистический центр", "терминально-логистический", "белый раст",
    "склад", "терминал",
)
APPLICATION_RECOMMENDATION_KEYWORDS = (
    "стадион", "арена", "спорткомплекс", "футболь", "карьер", "рудник", "гок",
    "аэропорт", "апрон", "перрон", "склад", "логист", "высокие прол", "high-bay",
    "high bay", "офис", "кабинет", "абк", "агрессивн", "мойка", "азс",
)
CATALOG_COMPANY_FACT_KEYWORDS = (
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
    "сертификат",
    "сертификаты",
    "сертификац",
    "декларац",
    "экспертиз",
    "качество",
    "качеств",
    "комплектующ",
    "надежн",
    "надёжн",
)
CATALOG_PORTFOLIO_LOOKUP_KEYWORDS = (
    "портфолио",
    "проект",
    "проекты",
    "реализован",
    "пример проекта",
    "пример объекта",
    "примеры проектов",
    "примеры объектов",
    "из портфолио",
    "какие проекты",
    "покажи проекты",
    "реализация",
    "ржд",
    "логистический центр",
    "терминально-логистический",
    "белый раст",
)
CATALOG_APPLICATION_RECOMMENDATION_KEYWORDS = (
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
KB_ROUTE_SPECS = {
    "corp_kb.company_common": {
        "title": "Company common knowledge base",
        "source_files": ["common_information_about_company.md"],
    },
    "corp_kb.luxnet": {
        "title": "Luxnet knowledge base",
        "source_files": ["about_Luxnet.md"],
    },
    "corp_kb.lighting_norms": {
        "title": "Lighting norms knowledge base",
        "source_files": ["normy_osveschennosty.md"],
    },
}
KB_ROUTE_LAMP_FILTER_KEYS = (
    "category",
    "mounting_type",
    "ip",
    "beam_pattern",
    "climate_execution",
    "electrical_protection_class",
    "explosion_protection_marking",
    "supply_voltage_raw",
    "dimensions_raw",
    "power_factor_operator",
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
)


def normalize_routing_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def strip_transport_wrappers(text: Any) -> str:
    lines: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        normalized = normalize_routing_text(line)
        if normalized.startswith("[от:") and normalized.endswith("]"):
            continue
        if normalized.startswith("[реплай на сообщение") and normalized.endswith("]"):
            continue
        if normalized in {"[случайный комментарий]", "[random comment]"}:
            continue
        if "голосовое сообщение" in normalized or "voice message" in normalized:
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def routing_message_text(message: Any) -> str:
    return normalize_routing_text(strip_transport_wrappers(message))


def routing_query_text(message: Any) -> str:
    return re.sub(r"\s+", " ", strip_transport_wrappers(message)).strip()


def dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = normalize_routing_text(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(value)
    return result


def text_has_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def is_document_lookup_intent(message: str) -> bool:
    return text_has_any(routing_message_text(message), DOCUMENT_LOOKUP_KEYWORDS)


def is_portfolio_lookup_intent(message: str) -> bool:
    return text_has_any(routing_message_text(message), PORTFOLIO_LOOKUP_KEYWORDS)


def is_application_recommendation_intent(message: str) -> bool:
    return text_has_any(routing_message_text(message), APPLICATION_RECOMMENDATION_KEYWORDS)


def company_fact_intent_type(message: str) -> str:
    normalized = routing_message_text(message)
    if (
        is_document_lookup_intent(normalized)
        or is_portfolio_lookup_intent(normalized)
        or is_application_recommendation_intent(normalized)
    ):
        return ""
    for subtype in (
        "requisites",
        "year_founded",
        "website",
        "address",
        "socials",
        "contacts",
        "about_company",
        "certification",
        "quality",
    ):
        if text_has_any(normalized, COMPANY_FACT_INTENT_KEYWORDS[subtype]):
            return subtype
    if text_has_any(normalized, COMPANY_FACT_KEYWORDS):
        return "about_company"
    return ""


def is_company_fact_intent(message: str) -> bool:
    return bool(company_fact_intent_type(message))


def company_common_topic_facets(message: str) -> list[str]:
    normalized = routing_message_text(message)
    facets: list[str] = []
    subtype = company_fact_intent_type(message)
    mapped = COMPANY_COMMON_FACET_BY_SUBTYPE.get(subtype)
    if mapped:
        facets.append(mapped)
    for facet, keywords in COMPANY_COMMON_FACET_KEYWORDS.items():
        if text_has_any(normalized, keywords):
            facets.append(facet)
    if not facets and text_has_any(normalized, ("компан", "ладзавод", "ladzavod", "лайт аудио дизайн")):
        facets.append("about_company")
    return dedupe_strings(facets)


def lighting_norms_topic_facets(message: str) -> list[str]:
    normalized = routing_message_text(message)
    facets: list[str] = []
    if text_has_any(normalized, ("таблиц", "нормативн", "lx", "люкс")):
        facets.append("tables")
    if text_has_any(normalized, ("естествен", "искусствен")):
        facets.append("definitions")
    if text_has_any(normalized, ("правил", "требован", "как нужно", "какие нормы")):
        facets.append("rules")
    return dedupe_strings(facets)


def expand_company_fact_query(message: str) -> str:
    subtype = company_fact_intent_type(message)
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
    if subtype == "certification":
        return "сертификаты декларации экспертиза сертификация ЛАДзавод светотехники"
    if subtype == "quality":
        return "качество комплектующие надежность ЛАДзавод светотехники"
    normalized = routing_message_text(message)
    if text_has_any(normalized, ("консультац", "расчет", "расчёт", "освещен", "освещён")):
        return "lad@ladled.ru 239-18-11 консультация расчет освещенности"
    if subtype == "contacts":
        return "239-18-11 lad@ladled.ru контакты ladzavod"
    if subtype == "about_company":
        return "общая информация о компании ЛАДзавод светотехники"
    return message


def contact_doc_search_query(message: str) -> str:
    normalized = routing_message_text(message)
    if text_has_any(normalized, ("email", "e-mail", "почт")):
        return "lad@ladled.ru"
    if text_has_any(normalized, ("телефон", "позвон", "связат")):
        return "239-18-11"
    return "lad@ladled.ru"


def strip_kb_route_lamp_filters(args: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in (args or {}).items() if key not in KB_ROUTE_LAMP_FILTER_KEYS}


def rewrite_authoritative_kb_search_args(args: dict[str, Any], message: str, routing_state: dict[str, Any]) -> dict[str, Any]:
    route_id = str(routing_state.get("knowledge_route_id") or "")
    if not route_id:
        return dict(args or {})
    rewritten = strip_kb_route_lamp_filters(args)
    preserved: dict[str, Any] = {}
    for key in ("limit", "offset"):
        value = rewritten.get(key)
        if isinstance(value, int) and value > 0:
            preserved[key] = value
    if bool(rewritten.get("include_debug")):
        preserved["include_debug"] = True
    preserved["kind"] = "hybrid_search"
    preserved["profile"] = "kb_route_lookup"
    preserved["knowledge_route_id"] = route_id
    source_files = routing_state.get("source_file_scope")
    if isinstance(source_files, list) and source_files:
        preserved["source_files"] = list(source_files)
    topic_facets = routing_state.get("topic_facets")
    if isinstance(topic_facets, list) and topic_facets:
        preserved["topic_facets"] = list(topic_facets)
    if route_id == "corp_kb.company_common":
        preserved["query"] = expand_company_fact_query(message)
    else:
        preserved["query"] = routing_query_text(message) or str(message or "")
    return preserved


def rewrite_company_fact_search_args(args: dict[str, Any], message: str) -> dict[str, Any]:
    routing_state = {
        "knowledge_route_id": "corp_kb.company_common",
        "source_file_scope": list(KB_ROUTE_SPECS["corp_kb.company_common"]["source_files"]),
        "topic_facets": company_common_topic_facets(message),
    }
    return rewrite_authoritative_kb_search_args(args, message, routing_state)
