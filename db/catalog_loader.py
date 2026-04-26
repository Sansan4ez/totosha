from __future__ import annotations

from pathlib import Path

from common import (
    bool_from_any,
    int_from_any,
    load_json_file,
    sha256_file,
    stable_portfolio_id,
)
from transform_catalog_json import transform_catalog


def build_portfolio_records(portfolio_rows: list[dict], source_hash: str) -> list[tuple]:
    deduped: dict[str, tuple] = {}
    for row in portfolio_rows:
        portfolio_id = stable_portfolio_id(
            row["name"],
            row.get("url"),
            row.get("groupName"),
            row.get("sphereId"),
        )
        deduped[portfolio_id] = (
            portfolio_id,
            row["name"],
            row.get("url"),
            row.get("image"),
            row.get("groupName"),
            row.get("sphereId"),
            source_hash,
        )
    return list(deduped.values())


def build_category_records(category_rows: list[dict], source_hash: str) -> list[tuple]:
    return [
        (
            row["id"],
            row["name"],
            row.get("url"),
            row.get("image"),
            source_hash,
        )
        for row in category_rows
    ]


def build_category_parent_records(category_rows: list[dict]) -> list[tuple]:
    return [
        (
            row["id"],
            row["parent"]["id"],
        )
        for row in category_rows
        if row.get("parent")
    ]


def build_sphere_category_records(sphere_rows: list[dict], source_hash: str) -> list[tuple]:
    return [
        (
            row["id"],
            category_ref["id"],
            source_hash,
        )
        for row in sphere_rows
        for category_ref in row.get("categoriesId", [])
    ]


def build_sphere_curated_category_records(sphere_rows: list[dict], source_hash: str) -> list[tuple]:
    return [
        (
            row["id"],
            category_ref["id"],
            category_ref["position"],
            source_hash,
        )
        for row in sphere_rows
        for category_ref in row.get("curatedCategoryIds", [])
    ]


async def seed_json_sources(conn, sources_dir: Path) -> dict[str, int]:
    catalog_path = sources_dir / "catalog.json"
    categories_path = sources_dir / "categories.json"
    sku_path = sources_dir / "etm_oracl_catalog_sku.json"
    mountings_path = sources_dir / "lamp_mountings.json"
    mounting_types_path = sources_dir / "mounting_types.json"
    portfolio_path = sources_dir / "portfolio.json"
    spheres_path = sources_dir / "spheres.json"

    category_rows = load_json_file(categories_path)["categories"]
    sku_rows = load_json_file(sku_path)
    category_mounting_rows = load_json_file(mountings_path)["lampMountings"]
    mounting_type_rows = load_json_file(mounting_types_path)["mountingTypes"]
    portfolio_rows = load_json_file(portfolio_path)["portfolio"]
    sphere_rows = load_json_file(spheres_path)["spheres"]
    catalog_rows = transform_catalog(catalog_path)

    category_hash = sha256_file(categories_path)
    sku_hash = sha256_file(sku_path)
    category_mounting_hash = sha256_file(mountings_path)
    mounting_type_hash = sha256_file(mounting_types_path)
    portfolio_hash = sha256_file(portfolio_path)
    sphere_hash = sha256_file(spheres_path)
    catalog_hash = sha256_file(catalog_path)
    category_name_by_id = {row["id"]: row["name"] for row in category_rows}
    portfolio_records = build_portfolio_records(portfolio_rows, portfolio_hash)
    category_records = build_category_records(category_rows, category_hash)
    category_parent_records = build_category_parent_records(category_rows)
    sphere_category_records = build_sphere_category_records(sphere_rows, sphere_hash)
    sphere_curated_category_records = build_sphere_curated_category_records(sphere_rows, sphere_hash)

    async with conn.transaction():
        await conn.execute(
            """
            TRUNCATE TABLE
                corp.catalog_lamp_properties_raw,
                corp.catalog_lamp_documents,
                corp.etm_oracl_catalog_sku,
                corp.category_mountings,
                corp.portfolio,
                corp.sphere_curated_categories,
                corp.sphere_categories,
                corp.catalog_lamps,
                corp.mounting_types,
                corp.spheres,
                corp.categories
            CASCADE
            """
        )

        await conn.executemany(
            """
            INSERT INTO corp.categories (category_id, name, url, image_url, source_hash)
            VALUES ($1, $2, $3, $4, $5)
            """,
            category_records,
        )

        if category_parent_records:
            await conn.executemany(
                """
                UPDATE corp.categories
                SET parent_category_id = $2
                WHERE category_id = $1
                """,
                category_parent_records,
            )

        await conn.executemany(
            """
            INSERT INTO corp.mounting_types (
                mounting_type_id, name, mark, description, image_url, url, source_hash
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            [
                (
                    row["id"],
                    row["name"],
                    row.get("mark"),
                    row.get("description"),
                    row.get("image_url"),
                    row.get("url"),
                    mounting_type_hash,
                )
                for row in mounting_type_rows
            ],
        )

        await conn.executemany(
            """
            INSERT INTO corp.spheres (sphere_id, name, url, source_hash)
            VALUES ($1, $2, $3, $4)
            """,
            [
                (
                    row["id"],
                    row["name"],
                    row.get("url"),
                    sphere_hash,
                )
                for row in sphere_rows
            ],
        )

        await conn.executemany(
            """
            INSERT INTO corp.sphere_categories (sphere_id, category_id, source_hash)
            VALUES ($1, $2, $3)
            """,
            sphere_category_records,
        )

        await conn.executemany(
            """
            INSERT INTO corp.sphere_curated_categories (
                sphere_id, category_id, position, source_hash
            )
            VALUES ($1, $2, $3, $4)
            """,
            sphere_curated_category_records,
        )

        await conn.executemany(
            """
            INSERT INTO corp.portfolio (
                portfolio_id, name, url, image_url, group_name, sphere_id, source_hash
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            portfolio_records,
        )

        await conn.executemany(
            """
            INSERT INTO corp.category_mountings (
                category_mounting_id, category_id, series, mounting_type_id, is_default, source_hash
            )
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            [
                (
                    row["id"],
                    row.get("categoryId"),
                    row["series"],
                    row.get("mounting_type_id"),
                    bool_from_any(row.get("is_default")),
                    category_mounting_hash,
                )
                for row in category_mounting_rows
            ],
        )

        await conn.executemany(
            """
            INSERT INTO corp.catalog_lamps (
                lamp_id, category_id, category_name, name, url, image_url,
                luminous_flux_lm, power_w, beam_pattern, mounting_type,
                explosion_protection_marking, is_explosion_protected, color_temperature_k,
                color_rendering_index_ra, power_factor_operator, power_factor_min,
                climate_execution, operating_temperature_range_raw,
                operating_temperature_min_c, operating_temperature_max_c,
                ingress_protection, electrical_protection_class, supply_voltage_raw,
                supply_voltage_kind, supply_voltage_nominal_v, supply_voltage_min_v,
                supply_voltage_max_v, supply_voltage_tolerance_minus_pct,
                supply_voltage_tolerance_plus_pct, dimensions_raw, length_mm, width_mm,
                height_mm, warranty_years, weight_kg, source_hash
            )
            VALUES (
                $1, $2, $3, $4, $5, $6,
                $7, $8, $9, $10,
                $11, $12, $13, $14, $15, $16,
                $17, $18, $19, $20,
                $21, $22, $23, $24, $25, $26,
                $27, $28, $29, $30, $31, $32,
                $33, $34, $35, $36
            )
            """,
            [
                (
                    row["lamp_id"],
                    row["category_id"],
                    category_name_by_id.get(row["category_id"]),
                    row["name"],
                    row.get("url"),
                    row.get("image_url"),
                    row.get("luminous_flux_lm"),
                    row.get("power_w"),
                    row.get("beam_pattern"),
                    row.get("mounting_type"),
                    row.get("explosion_protection_marking"),
                    bool_from_any(row.get("is_explosion_protected")),
                    row.get("color_temperature_k"),
                    row.get("color_rendering_index_ra"),
                    row.get("power_factor_operator"),
                    row.get("power_factor_min"),
                    row.get("climate_execution"),
                    row.get("operating_temperature_range_raw"),
                    row.get("operating_temperature_min_c"),
                    row.get("operating_temperature_max_c"),
                    row.get("ingress_protection"),
                    row.get("electrical_protection_class"),
                    row.get("supply_voltage_raw"),
                    row.get("supply_voltage_kind"),
                    row.get("supply_voltage_nominal_v"),
                    row.get("supply_voltage_min_v"),
                    row.get("supply_voltage_max_v"),
                    row.get("supply_voltage_tolerance_minus_pct"),
                    row.get("supply_voltage_tolerance_plus_pct"),
                    row.get("dimensions_raw"),
                    row.get("length_mm"),
                    row.get("width_mm"),
                    row.get("height_mm"),
                    row.get("warranty_years"),
                    row.get("weight_kg"),
                    catalog_hash,
                )
                for row in catalog_rows["lamps"]
            ],
        )

        await conn.executemany(
            """
            INSERT INTO corp.catalog_lamp_documents (
                lamp_id, instruction_url, blueprint_url, passport_url,
                certificate_url, ies_url, diffuser_url, complete_docs_url, source_hash
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            [
                (
                    row["lamp_id"],
                    row.get("instruction_url"),
                    row.get("blueprint_url"),
                    row.get("passport_url"),
                    row.get("certificate_url"),
                    row.get("ies_url"),
                    row.get("diffuser_url"),
                    row.get("complete_docs_url"),
                    catalog_hash,
                )
                for row in catalog_rows["documents"]
            ],
        )

        await conn.executemany(
            """
            INSERT INTO corp.catalog_lamp_properties_raw (
                lamp_id, property_code, property_name_ru, property_value_raw, property_measure_raw, source_hash
            )
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            [
                (
                    row["lamp_id"],
                    row["property_code"],
                    row["property_name_ru"],
                    row.get("property_value_raw"),
                    row.get("property_measure_raw"),
                    catalog_hash,
                )
                for row in catalog_rows["raw_properties"]
            ],
        )

        await conn.executemany(
            """
            INSERT INTO corp.etm_oracl_catalog_sku (
                sku_id, lamp_id, etm_code, oracl_code, short_box_name_wms,
                catalog_1c, box_name, description, comments, is_active, archived_at, source_hash
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            """,
            [
                (
                    str(row["id"]),
                    int_from_any(row.get("catalog_lamps_id")),
                    row.get("etm_code") or None,
                    row.get("oracl_code") or None,
                    row.get("short_box_name_wms") or None,
                    row.get("catalog_1c") or None,
                    row.get("box_name") or None,
                    row.get("description") or None,
                    row.get("comments") or None,
                    bool_from_any(row.get("is_active"), default=True),
                    row.get("archived_at") or None,
                    sku_hash,
                )
                for row in sku_rows
            ],
        )

    return {
        "categories": len(category_rows),
        "category_parent_links": len(category_parent_records),
        "mounting_types": len(mounting_type_rows),
        "spheres": len(sphere_rows),
        "sphere_categories": len(sphere_category_records),
        "sphere_curated_categories": len(sphere_curated_category_records),
        "portfolio": len(portfolio_records),
        "category_mountings": len(category_mounting_rows),
        "catalog_lamps": len(catalog_rows["lamps"]),
        "catalog_lamp_documents": len(catalog_rows["documents"]),
        "catalog_lamp_properties_raw": len(catalog_rows["raw_properties"]),
        "etm_oracl_catalog_sku": len(sku_rows),
    }
