from __future__ import annotations

import json
import re
from collections import defaultdict
from decimal import Decimal

from common import batched, join_nonempty, json_hash, tokenize_text, url_tokens

LIVE_SEARCH_DOCS_TABLE = "corp.corp_search_docs"
STAGE_SEARCH_DOCS_TABLE = "corp.corp_search_docs_stage"
OLD_SEARCH_DOCS_TABLE = "corp.corp_search_docs_old"
APPLICATION_DOC_ALIASES = {
    "Спортивное и освещение высокой мощности": ["стадион", "арена", "спорткомплекс", "футбольное поле"],
    "Тяжелые условия эксплуатации": ["карьер", "открытый карьер", "горнодобыча", "гок", "рудник"],
    "Наружное, уличное и дорожное освещение": ["аэропорт", "апрон", "перрон", "рулежная дорожка"],
    "Складские помещения": ["склад", "логистический центр", "высокие пролеты", "high-bay"],
    "Офисное, торговое, ЖКХ и АБК освещение": ["офис", "кабинет", "абк", "торговый зал"],
    "Светильники специального назначения": ["агрессивная среда", "химическое производство", "мойка", "азс"],
    "LAD LED R500 SPORT": ["стадион", "прожектор для стадиона"],
    "LAD LED R500": ["карьер", "мачтовое освещение", "высокие пролеты"],
    "LAD LED R700": ["карьер", "апрон", "открытая площадка"],
    "LAD LED R500 G": ["апрон", "перрон", "аэропорт"],
    "NL Nova": ["офис", "кабинет"],
    "NL VEGA": ["офис", "абк"],
    "LAD LED LINE-OZ": ["склад", "высокий пролет"],
    "АЗС": ["агрессивная среда", "азс"],
    "Специальное освещение": ["агрессивная среда", "специальное применение"],
}
KB_CHUNK_HEADING_ALIASES = {
    "о компании": [
        "о компании",
        "общая информация о компании",
        "профиль компании",
        "ladzavod",
        "ладзавод",
        "лад завод",
        "ladled",
    ],
    "наш профиль": [
        "о компании",
        "профиль компании",
        "чем занимается компания",
        "ладзавод",
    ],
    "контактная информация": [
        "контакты компании",
        "контактная информация",
        "телефон",
        "email",
        "e-mail",
        "почта",
        "адрес офиса",
        "консультация",
        "ladzavod",
    ],
    "реквизиты": [
        "реквизиты компании",
        "инн",
        "кпп",
        "огрн",
        "юридический адрес",
        "ladzavod",
    ],
    "социальные сети компании": [
        "соцсети компании",
        "социальные сети компании",
        "telegram",
        "youtube",
        "vk",
        "вконтакте",
        "канал компании",
        "ladzavod",
    ],
}
KB_ROUTE_SPECS = {
    "common_information_about_company.md": {
        "knowledge_route_id": "corp_kb.company_common",
        "route_family_aliases": [
            "ladzavod",
            "ладзавод",
            "лад завод",
            "ладзавод светотехники",
            "лайт аудио дизайн",
            "light audio design",
            "общая информация о компании",
            "компания ladzavod",
        ],
        "heading_specs": [
            {
                "match": "о компании",
                "aliases": ["о компании", "общая информация о компании", "профиль компании", "история компании"],
                "topic_facets": ["about_company"],
            },
            {
                "match": "наш профиль",
                "aliases": ["чем занимается компания", "профиль компании", "промышленное освещение", "тяжелые условия эксплуатации"],
                "topic_facets": ["about_company"],
            },
            {
                "match": "наш подход",
                "aliases": ["подход компании", "клиентоориентированность", "инновации", "качество компании"],
                "topic_facets": ["about_company"],
            },
            {
                "match": "инженерные решения",
                "aliases": ["инженерные решения компании", "собственные разработки", "цена качество"],
                "topic_facets": ["about_company"],
            },
            {
                "match": "доступные серии освещения",
                "aliases": ["серии светильников", "доступные серии", "линейки светильников", "lad led r500", "lad led r700", "nl nova", "nl vega"],
                "topic_facets": ["series"],
            },
            {
                "match": "высокое качество продукции",
                "aliases": ["качество продукции", "контроль качества", "стандарты качества", "надежность продукции"],
                "topic_facets": ["quality"],
            },
            {
                "match": "качество комплектующих",
                "aliases": ["качество комплектующих", "cree led", "надежные комплектующие", "проверенные комплектующие"],
                "topic_facets": ["quality"],
            },
            {
                "match": "производство сборка контроль качества",
                "aliases": ["производство в челябинске", "сборка продукции", "контроль качества производства"],
                "topic_facets": ["quality"],
            },
            {
                "match": "сертификация",
                "aliases": ["сертификация продукции", "сертификаты", "сертификат eac", "сертификат ce"],
                "topic_facets": ["certification"],
            },
            {
                "match": "декларации соответствия",
                "aliases": ["декларации соответствия", "декларация eac", "тр еаэс 037 2016"],
                "topic_facets": ["certification"],
            },
            {
                "match": "почему выбирают нас",
                "aliases": ["почему выбирают компанию", "преимущества компании", "бесплатные расчеты", "технические консультации"],
                "topic_facets": ["quality"],
            },
            {
                "match": "гарантия и сервис",
                "aliases": ["гарантия на продукцию", "сервис компании", "гарантийное обслуживание", "постгарантийное обслуживание"],
                "topic_facets": ["quality"],
            },
            {
                "match": "дополнительные испытания",
                "aliases": ["независимые лаборатории", "испытания продукции", "аккредитованные лаборатории"],
                "topic_facets": ["certification", "quality"],
            },
            {
                "match": "бесплатные образцы продукции",
                "aliases": ["бесплатные образцы", "тестовый светильник", "образцы продукции"],
                "topic_facets": ["quality"],
            },
            {
                "match": "новости компании",
                "aliases": ["новости компании", "новости ladzavod"],
                "topic_facets": ["news"],
            },
            {
                "match": "правовая информация",
                "aliases": ["правовая информация", "юридическая информация", "правила и условия использования сайта"],
                "topic_facets": ["legal"],
            },
            {
                "match": "контактная информация",
                "aliases": ["контакты компании", "телефон компании", "email компании", "адрес офиса", "почта компании"],
                "topic_facets": ["contacts"],
            },
            {
                "match": "реквизиты",
                "aliases": ["реквизиты компании", "инн", "кпп", "огрн", "ооо лайт аудио дизайн"],
                "topic_facets": ["requisites"],
            },
            {
                "match": "социальные сети компании",
                "aliases": ["соцсети компании", "telegram компании", "youtube компании", "vk компании", "официальный сайт"],
                "topic_facets": ["socials"],
            },
            {
                "match": "прайс",
                "aliases": ["прайс компании", "прайс лист", "цены компании"],
                "topic_facets": ["price"],
            },
            {
                "match": "расчет освещения",
                "aliases": ["расчет освещения", "расчет освещенности", "светотехнический расчет"],
                "topic_facets": ["lighting_calculation"],
            },
            {
                "match": "классификация пожароопасных зон",
                "aliases": ["пожароопасные зоны", "классификация пожароопасных зон", "пожарная зона"],
                "topic_facets": ["fire_hazard_zones"],
            },
        ],
    },
    "about_Luxnet.md": {
        "knowledge_route_id": "corp_kb.luxnet",
        "route_family_aliases": [
            "luxnet",
            "люкснет",
            "стандарт управления luxnet",
            "система luxnet",
            "беспроводное управление luxnet",
        ],
        "heading_specs": [
            {
                "match": "стандарт управления luxnet",
                "aliases": ["что такое luxnet", "что такое люкснет", "описание luxnet", "система управления luxnet"],
                "topic_facets": ["definition"],
            },
            {
                "match": "luxnet возможности системы",
                "aliases": ["возможности luxnet", "функции luxnet", "что умеет luxnet"],
                "topic_facets": ["capabilities"],
            },
            {
                "match": "преимущества luxnet",
                "aliases": ["преимущества luxnet", "плюсы luxnet", "benefits luxnet"],
                "topic_facets": ["benefits"],
            },
            {
                "match": "эффекты от внедрения luxnet",
                "aliases": ["эффекты от внедрения luxnet", "экономия luxnet", "эффективность luxnet"],
                "topic_facets": ["benefits"],
            },
            {
                "match": "luxnet индивидуальная настройка освещения",
                "aliases": ["настройка освещения luxnet", "управление освещением luxnet", "сценарии luxnet"],
                "topic_facets": ["lighting_control"],
            },
            {
                "match": "luxnet мобильное приложение",
                "aliases": ["мобильное приложение luxnet", "приложение luxnet", "bluetooth luxnet"],
                "topic_facets": ["mobile_app"],
            },
            {
                "match": "luxnet информационные панели и аналитика",
                "aliases": ["аналитика luxnet", "информационные панели luxnet", "отчеты luxnet"],
                "topic_facets": ["analytics"],
            },
            {
                "match": "luxnet 3 года хранения данных",
                "aliases": ["хранение данных luxnet", "база данных luxnet", "3 года хранения luxnet"],
                "topic_facets": ["data_retention"],
            },
            {
                "match": "дополнительное оборудование luxnet",
                "aliases": ["оборудование luxnet", "датчик освещенности luxnet", "модуль luxnet", "персональная метка luxnet"],
                "topic_facets": ["equipment"],
            },
            {
                "match": "обязательная сертификация",
                "aliases": ["сертификация luxnet", "сертификат luxnet", "eac luxnet"],
                "topic_facets": ["certification"],
            },
        ],
    },
    "normy_osveschennosty.md": {
        "knowledge_route_id": "corp_kb.lighting_norms",
        "route_family_aliases": [
            "нормы освещенности",
            "нормы освещённости",
            "нормы освещения",
            "нормативы освещения",
            "lighting norms",
            "основные понятия и определения освещения",
        ],
        "heading_specs": [
            {
                "match": "освещенность",
                "aliases": ["освещенность", "освещенность в люксах", "освещенность лк"],
                "topic_facets": ["definitions"],
            },
            {
                "match": "коэффициент",
                "aliases": ["коэффициенты освещения", "показатели освещения", "нормативные коэффициенты"],
                "topic_facets": ["definitions"],
            },
            {
                "match": "таблица",
                "aliases": ["таблица норм освещенности", "нормативная таблица освещения", "таблица освещения"],
                "topic_facets": ["tables"],
            },
            {
                "match": "норма",
                "aliases": ["нормативы освещения", "нормы освещения", "правила освещения"],
                "topic_facets": ["rules"],
            },
        ],
        "default_topic_facets": ["definitions"],
    },
}
KB_ROUTE_VALIDATION_CASES = (
    {
        "name": "company_common",
        "query": "общая информация о компании ladzavod",
        "expected_source_file": "common_information_about_company.md",
        "expected_headings": {"о компании", "наш профиль"},
    },
    {
        "name": "luxnet",
        "query": "что такое luxnet",
        "expected_source_file": "about_Luxnet.md",
        "expected_headings": {"стандарт управления luxnet"},
    },
    {
        "name": "lighting_norms",
        "query": "нормы освещенности",
        "expected_source_file": "normy_osveschennosty.md",
        "expected_headings": set(),
    },
)
HEADING_NUMBER_PREFIX_RE = re.compile(r"^\s*\d+(?:\.\d+)*(?:[A-Za-zА-Яа-яЁё])?\s*", re.UNICODE)
TEXT_KEY_RE = re.compile(r"[\W_]+", re.UNICODE)


def _json_object(value: object) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError(f"Unsupported JSON object payload: {type(value).__name__}")


LAMP_METADATA_FIELDS = (
    "beam_pattern",
    "mounting_type",
    "explosion_protection_marking",
    "is_explosion_protected",
    "color_temperature_k",
    "color_rendering_index_ra",
    "power_factor_operator",
    "power_factor_min",
    "climate_execution",
    "operating_temperature_range_raw",
    "operating_temperature_min_c",
    "operating_temperature_max_c",
    "ingress_protection",
    "electrical_protection_class",
    "supply_voltage_raw",
    "supply_voltage_kind",
    "supply_voltage_nominal_v",
    "supply_voltage_min_v",
    "supply_voltage_max_v",
    "supply_voltage_tolerance_minus_pct",
    "supply_voltage_tolerance_plus_pct",
    "dimensions_raw",
    "length_mm",
    "width_mm",
    "height_mm",
    "warranty_years",
    "weight_kg",
    "power_w",
    "luminous_flux_lm",
)


def _json_scalar(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)
    return value


def _json_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    return []


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = _text_key(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(str(item).strip())
    return result


def _merge_string_lists(existing: object, additions: list[str]) -> list[str]:
    return _dedupe_strings([*_json_string_list(existing), *[item for item in additions if str(item).strip()]])


def _text_key(value: object) -> str:
    return TEXT_KEY_RE.sub(" ", str(value or "").lower()).strip()


def _normalized_heading(heading: object) -> str:
    text = str(heading or "").strip()
    if not text:
        return ""
    stripped = HEADING_NUMBER_PREFIX_RE.sub("", text).strip(" .:-")
    return re.sub(r"\s+", " ", stripped)


def _kb_route_spec(source_file: str) -> dict | None:
    return KB_ROUTE_SPECS.get(str(source_file or "").strip())


def _kb_heading_spec(route_spec: dict | None, heading: str) -> dict:
    if not route_spec:
        return {}
    heading_key = _text_key(heading)
    for spec in route_spec.get("heading_specs", []):
        match_key = _text_key(spec.get("match"))
        if match_key and match_key in heading_key:
            return spec
    return {}


def _lamp_metadata(lamp: dict, category_name: str | None, etm_codes: list[str], oracl_codes: list[str], has_sku: bool) -> dict:
    metadata = {
        "lamp_id": lamp["lamp_id"],
        "name": lamp["name"],
        "category_id": lamp.get("category_id"),
        "category_name": category_name,
        "url": lamp.get("url"),
        "image_url": lamp.get("image_url"),
        "preview": lamp.get("preview"),
        "agent_summary": lamp.get("agent_summary"),
        "facts": _json_object(lamp.get("agent_facts")),
        "etm_codes": sorted(set(etm_codes)),
        "oracl_codes": sorted(set(oracl_codes)),
        "has_sku": has_sku,
    }
    for field in LAMP_METADATA_FIELDS:
        value = lamp.get(field)
        if value is not None:
            metadata[field] = _json_scalar(value)
    return metadata


def _lamp_doc(lamp: dict, skus: list[dict]) -> dict:
    sku_codes = []
    sku_labels = []
    etm_codes = []
    oracl_codes = []
    for sku in skus:
        sku_codes.extend([sku.get("etm_code"), sku.get("oracl_code"), sku.get("short_box_name_wms")])
        sku_labels.extend([sku.get("catalog_1c"), sku.get("box_name"), sku.get("description"), sku.get("comments")])
        if sku.get("etm_code"):
            etm_codes.append(sku["etm_code"])
        if sku.get("oracl_code"):
            oracl_codes.append(sku["oracl_code"])

    category_name = lamp.get("category_name")
    content = lamp.get("search_text") or lamp.get("agent_summary") or lamp.get("preview") or category_name or ""
    aliases = join_nonempty(
        [
            lamp.get("search_aliases"),
            tokenize_text(lamp.get("name")),
            " ".join(value for value in sku_codes if value),
            " ".join(value for value in sku_labels if value),
            url_tokens(lamp.get("url")),
            category_name,
        ],
        sep=" ",
    )
    return {
        "entity_type": "lamp",
        "entity_id": str(lamp["lamp_id"]),
        "title": lamp["name"],
        "content": content,
        "aliases": aliases,
        "metadata": _lamp_metadata(lamp, category_name, etm_codes, oracl_codes, bool(skus)),
    }


def _sku_doc(sku: dict, lamp_name: str | None) -> dict:
    title = " / ".join(part for part in [sku.get("etm_code"), sku.get("oracl_code")] if part) or sku["sku_id"]
    content = join_nonempty(
        [
            lamp_name,
            sku.get("box_name"),
            sku.get("description"),
            sku.get("catalog_1c"),
            sku.get("short_box_name_wms"),
        ]
    )
    aliases = join_nonempty(
        [
            sku.get("comments"),
            sku.get("description"),
            sku.get("catalog_1c"),
            sku.get("short_box_name_wms"),
            sku.get("box_name"),
            lamp_name,
        ],
        sep=" ",
    )
    metadata = {
        "sku_id": sku["sku_id"],
        "lamp_id": sku.get("lamp_id"),
        "lamp_name": lamp_name,
        "etm_code": sku.get("etm_code"),
        "oracl_code": sku.get("oracl_code"),
        "is_active": sku.get("is_active", True),
    }
    return {
        "entity_type": "sku",
        "entity_id": str(sku["sku_id"]),
        "title": title,
        "content": content,
        "aliases": aliases,
        "metadata": metadata,
    }


def _category_doc(category: dict, sphere_names: list[str]) -> dict:
    aliases = APPLICATION_DOC_ALIASES.get(category["name"], [])
    return {
        "entity_type": "category",
        "entity_id": str(category["category_id"]),
        "title": category["name"],
        "content": join_nonempty([", ".join(sorted(sphere_names)) if sphere_names else None]),
        "aliases": join_nonempty(
            [
                tokenize_text(category.get("name")),
                url_tokens(category.get("url")),
                " ".join(sorted(sphere_names)),
                " ".join(aliases),
            ],
            sep=" ",
        ),
        "metadata": {
            "category_id": category["category_id"],
            "name": category["name"],
            "url": category.get("url"),
            "image_url": category.get("image_url"),
            "sphere_names": sorted(sphere_names),
            "application_aliases": aliases,
        },
    }


def _portfolio_doc(portfolio: dict, sphere_name: str | None) -> dict:
    return {
        "entity_type": "portfolio",
        "entity_id": str(portfolio["portfolio_id"]),
        "title": portfolio["name"],
        "content": join_nonempty([portfolio.get("group_name"), sphere_name]),
        "aliases": join_nonempty(
            [
                tokenize_text(portfolio.get("name")),
                portfolio.get("group_name"),
                sphere_name,
                url_tokens(portfolio.get("url")),
            ],
            sep=" ",
        ),
        "metadata": {
            "portfolio_id": portfolio["portfolio_id"],
            "sphere_id": portfolio.get("sphere_id"),
            "name": portfolio["name"],
            "group_name": portfolio.get("group_name"),
            "sphere_name": sphere_name,
            "url": portfolio.get("url"),
            "image_url": portfolio.get("image_url"),
        },
    }


def _sphere_doc(sphere: dict, category_names: list[str], portfolio_names: list[str]) -> dict:
    aliases = APPLICATION_DOC_ALIASES.get(sphere["name"], [])
    return {
        "entity_type": "sphere",
        "entity_id": str(sphere["sphere_id"]),
        "title": sphere["name"],
        "content": join_nonempty(
            [
                ", ".join(category_names[:5]) if category_names else None,
                "; ".join(portfolio_names[:3]) if portfolio_names else None,
            ]
        ),
        "aliases": join_nonempty(
            [
                tokenize_text(sphere.get("name")),
                url_tokens(sphere.get("url")),
                " ".join(category_names[:8]),
                " ".join(portfolio_names[:5]),
                " ".join(aliases),
            ],
            sep=" ",
        ),
        "metadata": {
            "sphere_id": sphere["sphere_id"],
            "name": sphere["name"],
            "url": sphere.get("url"),
            "category_names": category_names[:8],
            "portfolio_examples": portfolio_names[:5],
            "application_aliases": aliases,
        },
    }


def _mounting_type_doc(mounting_type: dict) -> dict:
    return {
        "entity_type": "mounting_type",
        "entity_id": str(mounting_type["mounting_type_id"]),
        "title": mounting_type["name"],
        "content": join_nonempty([mounting_type.get("mark"), mounting_type.get("description")]),
        "aliases": join_nonempty([mounting_type.get("mark"), url_tokens(mounting_type.get("url"))], sep=" "),
        "metadata": {
            "mounting_type_id": mounting_type["mounting_type_id"],
            "name": mounting_type["name"],
            "mark": mounting_type.get("mark"),
            "description": mounting_type.get("description"),
        },
    }


def _category_mounting_doc(category_mounting: dict, category_name: str | None, mounting_type: dict | None) -> dict:
    return {
        "entity_type": "category_mounting",
        "entity_id": str(category_mounting["category_mounting_id"]),
        "title": category_mounting["series"],
        "content": join_nonempty(
            [
                category_name,
                mounting_type.get("name") if mounting_type else None,
                mounting_type.get("mark") if mounting_type else None,
                "default" if category_mounting.get("is_default") else None,
            ]
        ),
        "aliases": join_nonempty(
            [
                category_mounting.get("series"),
                category_name,
                mounting_type.get("mark") if mounting_type else None,
            ],
            sep=" ",
        ),
        "metadata": {
            "series": category_mounting.get("series"),
            "category_id": category_mounting.get("category_id"),
            "category_name": category_name,
            "mounting_type_id": category_mounting.get("mounting_type_id"),
            "mounting_type_name": mounting_type.get("name") if mounting_type else None,
            "mark": mounting_type.get("mark") if mounting_type else None,
            "is_default": category_mounting.get("is_default", False),
        },
    }


def _kb_chunk_aliases(chunk: dict) -> str:
    heading = str(chunk.get("heading") or "").strip()
    heading_key = heading.lower()
    aliases = KB_CHUNK_HEADING_ALIASES.get(heading_key, [])
    normalized_heading = _normalized_heading(heading)
    route_spec = _kb_route_spec(str(chunk.get("source_file") or ""))
    heading_spec = _kb_heading_spec(route_spec, normalized_heading or heading)
    route_aliases = route_spec.get("route_family_aliases", []) if route_spec else []
    heading_aliases = heading_spec.get("aliases", [])
    return join_nonempty(
        [
            chunk.get("document_title"),
            tokenize_text(chunk.get("document_title")),
            heading,
            normalized_heading if normalized_heading and normalized_heading != heading else None,
            tokenize_text(normalized_heading) if normalized_heading else None,
            tokenize_text(heading),
            url_tokens(chunk.get("source_file")),
            " ".join(aliases),
            " ".join(route_aliases),
            " ".join(heading_aliases),
        ],
        sep=" ",
    )


def _kb_chunk_doc(chunk: dict) -> dict:
    metadata = _json_object(chunk.get("metadata"))
    source_file = chunk["source_file"]
    heading = str(chunk.get("heading") or "").strip()
    normalized_heading = _normalized_heading(heading)
    route_spec = _kb_route_spec(source_file)
    heading_spec = _kb_heading_spec(route_spec, normalized_heading or heading)
    route_family_aliases = list(route_spec.get("route_family_aliases", [])) if route_spec else []
    heading_aliases = list(heading_spec.get("aliases", []))
    topic_facets = list(heading_spec.get("topic_facets", []))
    if route_spec and not topic_facets:
        topic_facets = list(route_spec.get("default_topic_facets", []))
    metadata["source_file"] = str(metadata.get("source_file") or source_file)
    metadata["document_title"] = str(metadata.get("document_title") or chunk["document_title"])
    metadata["source_file_scope"] = _merge_string_lists(metadata.get("source_file_scope"), [source_file])
    if normalized_heading:
        metadata["normalized_heading"] = str(metadata.get("normalized_heading") or normalized_heading)
    if route_spec:
        route_id = str(route_spec["knowledge_route_id"])
        metadata["knowledge_route_id"] = str(metadata.get("knowledge_route_id") or route_id)
        metadata["retrieval_route_family"] = str(metadata.get("retrieval_route_family") or route_id)
        metadata["route_family_aliases"] = _merge_string_lists(metadata.get("route_family_aliases"), route_family_aliases)
    if heading_aliases:
        metadata["heading_aliases"] = _merge_string_lists(metadata.get("heading_aliases"), heading_aliases)
    if topic_facets:
        metadata["topic_facets"] = _merge_string_lists(metadata.get("topic_facets"), topic_facets)
    return {
        "entity_type": "kb_chunk",
        "entity_id": f"{source_file}:{chunk['chunk_index']}",
        "title": heading,
        "content": chunk["content"],
        "aliases": _kb_chunk_aliases(chunk),
        "metadata": metadata,
    }


def _validate_kb_route_rows(rows: list[dict]) -> dict:
    errors: list[str] = []
    sources: dict[str, dict] = {}
    for source_file, route_spec in KB_ROUTE_SPECS.items():
        source_rows = [row for row in rows if _json_object(row.get("metadata")).get("source_file") == source_file]
        if not source_rows:
            errors.append(f"missing indexed kb rows for {source_file}")
            sources[source_file] = {"row_count": 0}
            continue
        route_id = str(route_spec["knowledge_route_id"])
        route_aliases = [alias for alias in route_spec.get("route_family_aliases", []) if alias]
        route_rows = 0
        scoped_rows = 0
        faceted_rows = 0
        alias_rows = 0
        for row in source_rows:
            metadata = _json_object(row.get("metadata"))
            aliases_key = _text_key(row.get("aliases"))
            if metadata.get("knowledge_route_id") == route_id and metadata.get("retrieval_route_family") == route_id:
                route_rows += 1
            if source_file in _json_string_list(metadata.get("source_file_scope")):
                scoped_rows += 1
            if _json_string_list(metadata.get("topic_facets")):
                faceted_rows += 1
            if route_aliases and any(_text_key(alias) in aliases_key for alias in route_aliases):
                alias_rows += 1
        if route_rows != len(source_rows):
            errors.append(f"{source_file}: missing knowledge_route_id/retrieval_route_family on some rows")
        if scoped_rows != len(source_rows):
            errors.append(f"{source_file}: missing source_file_scope on some rows")
        if faceted_rows == 0:
            errors.append(f"{source_file}: no topic facets materialized")
        if alias_rows == 0:
            errors.append(f"{source_file}: no route-family aliases materialized")
        sources[source_file] = {
            "row_count": len(source_rows),
            "knowledge_route_id": route_id,
            "route_rows": route_rows,
            "scoped_rows": scoped_rows,
            "faceted_rows": faceted_rows,
            "alias_rows": alias_rows,
        }
    return {"sources": sources, "errors": errors}


async def validate_search_docs(conn) -> dict:
    rows = [
        dict(row)
        for row in await conn.fetch(
            """
            SELECT entity_id, title, aliases, metadata
            FROM corp.corp_search_docs
            WHERE entity_type = 'kb_chunk'
              AND coalesce(metadata->>'source_file', '') = ANY($1::text[])
            ORDER BY entity_id
            """,
            list(KB_ROUTE_SPECS.keys()),
        )
    ]
    report = _validate_kb_route_rows(rows)
    query_results: dict[str, dict] = {}
    for case in KB_ROUTE_VALIDATION_CASES:
        matches = [
            dict(row)
            for row in await conn.fetch(
                """
                SELECT entity_id, title, metadata, score
                FROM corp.corp_hybrid_search(
                    $1::text,
                    NULL::vector,
                    5::integer,
                    1.0::double precision,
                    0.0::double precision,
                    0.6::double precision,
                    60::integer,
                    $2::text[],
                    true::boolean
                )
                """,
                case["query"],
                ["kb_chunk"],
            )
        ]
        top = matches[0] if matches else {}
        top_metadata = _json_object(top.get("metadata"))
        top_source_file = str(top_metadata.get("source_file") or "")
        top_heading = _text_key(top.get("title"))
        passed = bool(matches) and top_source_file == case["expected_source_file"]
        if passed and case["expected_headings"]:
            passed = top_heading in case["expected_headings"]
        if not passed:
            report["errors"].append(
                f"ranking check failed for {case['name']}: expected {case['expected_source_file']}, got {top_source_file or 'empty'}"
            )
        query_results[case["name"]] = {
            "query": case["query"],
            "expected_source_file": case["expected_source_file"],
            "top_source_file": top_source_file,
            "top_heading": str(top.get("title") or ""),
            "top_score": float(top["score"]) if top.get("score") is not None else None,
            "passed": passed,
        }
    report["queries"] = query_results
    if report["errors"]:
        raise RuntimeError("search-doc validation failed: " + "; ".join(report["errors"]))
    return report


async def build_search_docs(conn, *, embeddings_enabled: bool = True) -> dict[str, int]:
    categories = [dict(row) for row in await conn.fetch("SELECT * FROM corp.categories ORDER BY category_id")]
    lamps = [dict(row) for row in await conn.fetch("SELECT * FROM corp.v_catalog_lamps_agent ORDER BY lamp_id")]
    skus = [dict(row) for row in await conn.fetch("SELECT * FROM corp.etm_oracl_catalog_sku ORDER BY sku_id")]
    spheres = [dict(row) for row in await conn.fetch("SELECT * FROM corp.spheres ORDER BY sphere_id")]
    sphere_categories = [dict(row) for row in await conn.fetch("SELECT * FROM corp.sphere_categories ORDER BY sphere_id, category_id")]
    portfolio = [dict(row) for row in await conn.fetch("SELECT * FROM corp.portfolio ORDER BY portfolio_id")]
    mounting_types = [dict(row) for row in await conn.fetch("SELECT * FROM corp.mounting_types ORDER BY mounting_type_id")]
    category_mountings = [dict(row) for row in await conn.fetch("SELECT * FROM corp.category_mountings ORDER BY category_mounting_id")]
    knowledge_chunks = [dict(row) for row in await conn.fetch("SELECT * FROM corp.knowledge_chunks ORDER BY source_file, chunk_index")]

    categories_by_id = {row["category_id"]: row for row in categories}
    spheres_by_id = {row["sphere_id"]: row for row in spheres}
    mounting_types_by_id = {row["mounting_type_id"]: row for row in mounting_types}

    skus_by_lamp_id: dict[int, list[dict]] = defaultdict(list)
    for sku in skus:
        if sku.get("lamp_id") is not None:
            skus_by_lamp_id[int(sku["lamp_id"])].append(sku)

    sphere_names_by_category: dict[int, list[str]] = defaultdict(list)
    category_names_by_sphere: dict[int, list[str]] = defaultdict(list)
    for relation in sphere_categories:
        category = categories_by_id.get(relation["category_id"])
        sphere = spheres_by_id.get(relation["sphere_id"])
        if category and sphere:
            sphere_names_by_category[category["category_id"]].append(sphere["name"])
            category_names_by_sphere[sphere["sphere_id"]].append(category["name"])

    portfolio_names_by_sphere: dict[int, list[str]] = defaultdict(list)
    for row in portfolio:
        if row.get("sphere_id") is not None:
            portfolio_names_by_sphere[int(row["sphere_id"])].append(row["name"])

    docs = []
    for lamp in lamps:
        docs.append(_lamp_doc(lamp, skus_by_lamp_id.get(lamp["lamp_id"], [])))

    lamp_name_by_id = {lamp["lamp_id"]: lamp["name"] for lamp in lamps}
    for sku in skus:
        docs.append(_sku_doc(sku, lamp_name_by_id.get(sku.get("lamp_id"))))

    for category in categories:
        docs.append(_category_doc(category, sphere_names_by_category.get(category["category_id"], [])))

    for row in portfolio:
        sphere = spheres_by_id.get(row.get("sphere_id"))
        docs.append(_portfolio_doc(row, sphere["name"] if sphere else None))

    for sphere in spheres:
        docs.append(_sphere_doc(sphere, category_names_by_sphere.get(sphere["sphere_id"], []), portfolio_names_by_sphere.get(sphere["sphere_id"], [])))

    for mounting_type in mounting_types:
        docs.append(_mounting_type_doc(mounting_type))

    for category_mounting in category_mountings:
        category = categories_by_id.get(category_mounting.get("category_id"))
        mounting_type = mounting_types_by_id.get(category_mounting.get("mounting_type_id"))
        docs.append(_category_mounting_doc(category_mounting, category["name"] if category else None, mounting_type))

    for chunk in knowledge_chunks:
        docs.append(_kb_chunk_doc(chunk))

    for doc in docs:
        doc["content"] = doc.get("content") or ""
        doc["aliases"] = doc.get("aliases") or ""
        doc["source_hash"] = json_hash(doc)

    await conn.execute(f"DROP TABLE IF EXISTS {OLD_SEARCH_DOCS_TABLE}")
    await conn.execute(f"DROP TABLE IF EXISTS {STAGE_SEARCH_DOCS_TABLE}")
    await conn.execute(
        f"""
        CREATE TABLE {STAGE_SEARCH_DOCS_TABLE}
        (LIKE {LIVE_SEARCH_DOCS_TABLE} INCLUDING ALL)
        """
    )
    await conn.execute(f"REVOKE ALL ON TABLE {STAGE_SEARCH_DOCS_TABLE} FROM PUBLIC")
    await conn.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLE {STAGE_SEARCH_DOCS_TABLE} TO corp_rw")
    await conn.execute(f"GRANT SELECT ON TABLE {STAGE_SEARCH_DOCS_TABLE} TO corp_ro")

    for batch in batched(docs, 20):
        batch_items = list(batch)
        if embeddings_enabled:
            from embeddings import get_embeddings
        embeddings = (
            await get_embeddings([f"{item['title']}\n\n{item['content']}" for item in batch_items])
            if embeddings_enabled
            else [None] * len(batch_items)
        )
        await conn.executemany(
            f"""
            INSERT INTO {STAGE_SEARCH_DOCS_TABLE} (
                entity_type, entity_id, title, content, aliases, metadata, source_hash, embedding
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            [
                (
                    item["entity_type"],
                    item["entity_id"],
                    item["title"],
                    item["content"],
                    item["aliases"],
                    json.dumps(item["metadata"], ensure_ascii=False),
                    item["source_hash"],
                    embedding,
                )
                for item, embedding in zip(batch_items, embeddings, strict=True)
            ],
        )

    async with conn.transaction():
        await conn.execute(f"LOCK TABLE {LIVE_SEARCH_DOCS_TABLE} IN ACCESS EXCLUSIVE MODE")
        await conn.execute("ALTER TABLE corp.corp_search_docs RENAME TO corp_search_docs_old")
        await conn.execute("ALTER TABLE corp.corp_search_docs_stage RENAME TO corp_search_docs")
        await conn.execute(f"DROP TABLE {OLD_SEARCH_DOCS_TABLE}")

    counts: dict[str, int] = defaultdict(int)
    for doc in docs:
        counts[doc["entity_type"]] += 1
    return dict(counts)
