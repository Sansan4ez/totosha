from __future__ import annotations

import json
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
    return join_nonempty(
        [
            chunk.get("document_title"),
            heading,
            tokenize_text(heading),
            url_tokens(chunk.get("source_file")),
            " ".join(aliases),
        ],
        sep=" ",
    )


def _kb_chunk_doc(chunk: dict) -> dict:
    metadata = _json_object(chunk.get("metadata"))
    metadata.setdefault("source_file", chunk["source_file"])
    metadata.setdefault("document_title", chunk["document_title"])
    return {
        "entity_type": "kb_chunk",
        "entity_id": f"{chunk['source_file']}:{chunk['chunk_index']}",
        "title": chunk["heading"],
        "content": chunk["content"],
        "aliases": _kb_chunk_aliases(chunk),
        "metadata": metadata,
    }


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
