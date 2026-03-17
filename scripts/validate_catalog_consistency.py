#!/usr/bin/env python3
"""
Проверяет связность `db/catalog.json`, `db/categories.json`
и `db/etm_oracl_catalog_sku_rows.json`.

Что проверяет:
1. Каждый `categoryId` товара из каталога существует в `categories.json`.
2. Каждый товар из каталога имеет строку в ETM по строгой связке
   `catalog.products[].id == etm_oracl_catalog_sku_rows[].catalog_lamps_id`.
3. Отдельно считает дубли по `catalog.products[].name` и по
   `etm_oracl_catalog_sku_rows[].catalog_lamps_id`, чтобы объяснить расхождения
   по количеству записей.

Примеры:
    python scripts/validate_catalog_consistency.py
    python scripts/validate_catalog_consistency.py --json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ValidationReport:
    catalog_products: int
    categories_count: int
    etm_rows: int
    missing_category_ids: list[dict[str, Any]]
    missing_etm_rows: list[dict[str, Any]]
    duplicate_catalog_names: list[dict[str, Any]]
    duplicate_etm_catalog_lamps_ids: list[dict[str, Any]]
    explanation: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Проверяет categoryId, ETM-связки и объясняет расхождения "
            "между catalog.json и etm_oracl_catalog_sku_rows.json."
        )
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path("db/catalog.json"),
        help="Путь к catalog.json.",
    )
    parser.add_argument(
        "--categories",
        type=Path,
        default=Path("db/categories.json"),
        help="Путь к categories.json.",
    )
    parser.add_argument(
        "--etm",
        type=Path,
        default=Path("db/etm_oracl_catalog_sku_rows.json"),
        help="Путь к ETM JSON.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Печатает результат в JSON.",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SystemExit(f"Файл не найден: {path}") from error
    except json.JSONDecodeError as error:
        raise SystemExit(f"Некорректный JSON в {path}: {error}") from error


def validate_catalog(data: Any, path: Path) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        raise SystemExit(f"Ожидался JSON-объект в {path}")

    products = data.get("products")
    if not isinstance(products, list):
        raise SystemExit(f"Ожидался список 'products' в {path}")

    for product in products:
        if not isinstance(product, dict):
            raise SystemExit(f"Все элементы 'products' в {path} должны быть объектами")

    return products


def validate_categories(data: Any, path: Path) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        raise SystemExit(f"Ожидался JSON-объект в {path}")

    categories = data.get("categories")
    if not isinstance(categories, list):
        raise SystemExit(f"Ожидался список 'categories' в {path}")

    for category in categories:
        if not isinstance(category, dict):
            raise SystemExit(f"Все элементы 'categories' в {path} должны быть объектами")

    return categories


def validate_etm(data: Any, path: Path) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        raise SystemExit(f"Ожидался JSON-массив в {path}")

    for row in data:
        if not isinstance(row, dict):
            raise SystemExit(f"Все элементы в {path} должны быть объектами")

    return data


def build_report(
    products: list[dict[str, Any]],
    categories: list[dict[str, Any]],
    etm_rows: list[dict[str, Any]],
) -> ValidationReport:
    category_ids = {category.get("id") for category in categories}

    etm_by_catalog_lamps_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in etm_rows:
        catalog_lamps_id = str(row.get("catalog_lamps_id") or "").strip()
        etm_by_catalog_lamps_id[catalog_lamps_id].append(row)

    missing_category_ids: list[dict[str, Any]] = []
    missing_etm_rows: list[dict[str, Any]] = []

    for product in products:
        product_id = product.get("id")
        product_name = product.get("name")
        category_id = product.get("categoryId")

        if category_id not in category_ids:
            missing_category_ids.append(
                {
                    "productId": product_id,
                    "productName": product_name,
                    "categoryId": category_id,
                }
            )

        linked_rows = etm_by_catalog_lamps_id.get(str(product_id), [])
        if not linked_rows:
            missing_etm_rows.append(
                {
                    "productId": product_id,
                    "productName": product_name,
                    "categoryId": category_id,
                }
            )

    duplicate_catalog_names = [
        {"name": name, "count": count}
        for name, count in Counter(product.get("name") for product in products).items()
        if name and count > 1
    ]
    duplicate_catalog_names.sort(key=lambda item: (-item["count"], str(item["name"])))

    duplicate_etm_catalog_lamps_ids = [
        {
            "catalog_lamps_id": catalog_lamps_id,
            "count": len(rows),
            "etmIds": [row.get("id") for row in rows],
        }
        for catalog_lamps_id, rows in etm_by_catalog_lamps_id.items()
        if catalog_lamps_id and len(rows) > 1
    ]
    duplicate_etm_catalog_lamps_ids.sort(
        key=lambda item: (-item["count"], str(item["catalog_lamps_id"]))
    )

    explanation = [
        (
            "Валидация связи каталога и ETM выполняется строго по полям "
            "`catalog.products[].id` и `etm_oracl_catalog_sku_rows[].catalog_lamps_id`."
        ),
        (
            f"По текущим данным в каталоге {len(products)} товаров, а в ETM {len(etm_rows)} строк."
        ),
    ]

    if missing_etm_rows:
        explanation.append(
            (
                f"Каталог больше ETM на {len(products) - len(etm_rows)} записей не из-за дублей, "
                f"а потому что у {len(missing_etm_rows)} товаров каталога нет строки в ETM."
            )
        )
    else:
        explanation.append("Все товары каталога имеют строку в ETM по `catalog_lamps_id`.")

    if duplicate_catalog_names:
        explanation.append(
            f"В каталоге найдены дубли по имени: {len(duplicate_catalog_names)}."
        )
    else:
        explanation.append("Дублей по `catalog.products[].name` в каталоге не найдено.")

    if duplicate_etm_catalog_lamps_ids:
        explanation.append(
            "В ETM найдены дубли по `catalog_lamps_id`, они могут искажать счётчики."
        )
    else:
        explanation.append("Дублей по `etm_oracl_catalog_sku_rows[].catalog_lamps_id` не найдено.")

    return ValidationReport(
        catalog_products=len(products),
        categories_count=len(categories),
        etm_rows=len(etm_rows),
        missing_category_ids=missing_category_ids,
        missing_etm_rows=missing_etm_rows,
        duplicate_catalog_names=duplicate_catalog_names,
        duplicate_etm_catalog_lamps_ids=duplicate_etm_catalog_lamps_ids,
        explanation=explanation,
    )


def print_text_report(report: ValidationReport) -> None:
    print(
        "Сводка: "
        f"catalog_products={report.catalog_products}, "
        f"categories={report.categories_count}, "
        f"etm_rows={report.etm_rows}"
    )
    print(f"- missing_category_ids: {len(report.missing_category_ids)}")
    print(f"- missing_etm_rows: {len(report.missing_etm_rows)}")
    print(f"- duplicate_catalog_names: {len(report.duplicate_catalog_names)}")
    print(
        "- duplicate_etm_catalog_lamps_ids: "
        f"{len(report.duplicate_etm_catalog_lamps_ids)}"
    )

    print("\nПояснение:")
    for line in report.explanation:
        print(f"- {line}")

    if report.missing_category_ids:
        print("\nТовары с невалидным categoryId:")
        for item in report.missing_category_ids[:20]:
            print(
                f"- productId={item['productId']} "
                f"name={item['productName']!r} categoryId={item['categoryId']}"
            )

    if report.missing_etm_rows:
        print("\nТовары без строки в ETM:")
        for item in report.missing_etm_rows[:20]:
            print(
                f"- productId={item['productId']} "
                f"name={item['productName']!r} categoryId={item['categoryId']}"
            )


def main() -> int:
    args = parse_args()

    products = validate_catalog(load_json(args.catalog), args.catalog)
    categories = validate_categories(load_json(args.categories), args.categories)
    etm_rows = validate_etm(load_json(args.etm), args.etm)

    report = build_report(products, categories, etm_rows)

    if args.json:
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    else:
        print_text_report(report)

    return 1 if (report.missing_category_ids or report.missing_etm_rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
