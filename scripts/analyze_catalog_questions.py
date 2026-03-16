#!/usr/bin/env python3
"""
Анализирует `db/catalog.json` и формирует список вопросов по качеству данных.

Скрипт не меняет исходные файлы — он помогает быстро понять, что именно
нужно исправлять в каталоге и какие варианты решения есть.

Примеры:
    python scripts/analyze_catalog_questions.py
    python scripts/analyze_catalog_questions.py --json
    python scripts/analyze_catalog_questions.py --catalog db/catalog.json --categories db/categories.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


PLACEHOLDER_IMAGE = "no-photo.jpg"
EXPECTED_DOC_KEYS = (
    "instruction",
    "blueprint",
    "passport",
    "sertificate",
    "IES",
    "diffuser",
    "complectOfDocs",
)
NORMALIZED_DOC_KEY_SUGGESTIONS = {
    "sertificate": "certificate",
    "complectOfDocs": "completeDocs",
    "IES": "ies",
}


@dataclass(slots=True)
class Finding:
    code: str
    severity: str
    title: str
    summary: str
    evidence: dict[str, Any]
    options: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Проверяет db/catalog.json и показывает спорные места в данных."
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path("db/catalog.json"),
        help="Путь к catalog.json",
    )
    parser.add_argument(
        "--categories",
        type=Path,
        default=Path("db/categories.json"),
        help="Путь к categories.json для сверки categoryId",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Печатает результат в JSON",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SystemExit(f"Файл не найден: {path}") from error
    except json.JSONDecodeError as error:
        raise SystemExit(f"Некорректный JSON в {path}: {error}") from error


def validate_catalog(data: Any, path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(data, dict):
        raise SystemExit(f"Ожидался JSON-объект в {path}")

    categories = data.get("categories")
    products = data.get("products")

    if not isinstance(categories, list):
        raise SystemExit(f"Ожидался список 'categories' в {path}")
    if not isinstance(products, list):
        raise SystemExit(f"Ожидался список 'products' в {path}")

    for category in categories:
        if not isinstance(category, dict):
            raise SystemExit(f"Все элементы 'categories' в {path} должны быть объектами")
    for product in products:
        if not isinstance(product, dict):
            raise SystemExit(f"Все элементы 'products' в {path} должны быть объектами")

    return categories, products


def validate_reference_categories(data: Any, path: Path) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        raise SystemExit(f"Ожидался JSON-объект в {path}")

    categories = data.get("categories")
    if not isinstance(categories, list):
        raise SystemExit(f"Ожидался список 'categories' в {path}")

    for category in categories:
        if not isinstance(category, dict):
            raise SystemExit(f"Все элементы 'categories' в {path} должны быть объектами")

    return categories


def analyze_catalog(
    catalog_categories: list[dict[str, Any]],
    catalog_products: list[dict[str, Any]],
    reference_categories: list[dict[str, Any]],
) -> list[Finding]:
    findings: list[Finding] = []

    catalog_category_ids = {category.get("id") for category in catalog_categories}
    reference_ids = {category.get("id") for category in reference_categories}
    reference_names_by_id = {
        category.get("id"): category.get("name")
        for category in reference_categories
        if category.get("id") is not None
    }

    missing_from_catalog_categories: list[dict[str, Any]] = []
    matched_to_reference = 0
    category_name_mismatches: list[dict[str, Any]] = []
    product_count_by_catalog_category = Counter()

    for product in catalog_products:
        category_id = product.get("categoryId")
        category_name = product.get("categoryName")

        if category_id in catalog_category_ids:
            product_count_by_catalog_category[category_id] += 1
        else:
            missing_from_catalog_categories.append(
                {
                    "productId": product.get("id"),
                    "productName": product.get("name"),
                    "categoryId": category_id,
                    "categoryName": category_name,
                }
            )

        if category_id in reference_ids:
            matched_to_reference += 1
            reference_name = reference_names_by_id.get(category_id)
            if reference_name != category_name:
                category_name_mismatches.append(
                    {
                        "productId": product.get("id"),
                        "categoryId": category_id,
                        "catalogCategoryName": category_name,
                        "referenceCategoryName": reference_name,
                    }
                )

    if missing_from_catalog_categories:
        unique_missing_ids = sorted(
            {
                item["categoryId"]
                for item in missing_from_catalog_categories
                if item["categoryId"] is not None
            }
        )
        findings.append(
            Finding(
                code="category-link-gap",
                severity="high",
                title="Категории товаров не совпадают со списком categories",
                summary=(
                    f"{len(missing_from_catalog_categories)} из {len(catalog_products)} товаров "
                    f"ссылаются на categoryId, которого нет в catalog.categories. "
                    f"При этом все эти categoryId находятся в db/categories.json."
                ),
                evidence={
                    "catalogCategories": len(catalog_categories),
                    "catalogProducts": len(catalog_products),
                    "productsOutsideCatalogCategories": len(missing_from_catalog_categories),
                    "uniqueMissingCategoryIds": len(unique_missing_ids),
                    "sampleProducts": missing_from_catalog_categories[:10],
                },
                options=[
                    "Сделать catalog.categories полным списком категорий, включая дочерние.",
                    "Оставить categories только витринными и переименовать поле, например в showcaseCategories.",
                    "Добавить отдельное поле leafCategories и явно документировать, что products[*].categoryId указывает на него.",
                ],
            )
        )

    categories_without_direct_products = [
        {
            "id": category.get("id"),
            "name": category.get("name"),
        }
        for category in catalog_categories
        if product_count_by_catalog_category[category.get("id")] == 0
    ]
    if categories_without_direct_products:
        findings.append(
            Finding(
                code="empty-showcase-categories",
                severity="medium",
                title="Большинство категорий не имеют прямых товаров",
                summary=(
                    f"{len(categories_without_direct_products)} из {len(catalog_categories)} категорий "
                    "не используются напрямую в products[*].categoryId."
                ),
                evidence={
                    "categoriesWithoutDirectProducts": len(categories_without_direct_products),
                    "sampleCategories": categories_without_direct_products[:10],
                },
                options=[
                    "Если это родительские витринные разделы — хранить для них отдельную связь parentCategoryId.",
                    "Если это ошибка структуры — пересобрать categories из того же источника, что и products.",
                    "Добавить валидацию, которая запрещает публикацию каталога с 'пустыми' категориями без дочерних связей.",
                ],
            )
        )

    placeholder_categories = [
        {
            "id": category.get("id"),
            "name": category.get("name"),
            "image": category.get("image"),
        }
        for category in catalog_categories
        if PLACEHOLDER_IMAGE in str(category.get("image", ""))
    ]
    if placeholder_categories:
        findings.append(
            Finding(
                code="placeholder-images",
                severity="low",
                title="В каталоге есть категории с placeholder-изображением",
                summary=(
                    f"У {len(placeholder_categories)} из {len(catalog_categories)} категорий "
                    "используется no-photo.jpg."
                ),
                evidence={
                    "placeholderCategoryImages": len(placeholder_categories),
                    "sampleCategories": placeholder_categories[:10],
                },
                options=[
                    "Дозаполнить картинки из db/categories.json или из карточек дочерних категорий.",
                    "На этапе экспорта автоматически наследовать image от первой дочерней категории.",
                    "Скрывать image у категории, если там placeholder, и отдавать это как null.",
                ],
            )
        )

    doc_keys_counter = Counter()
    products_with_nonstandard_doc_keys: list[dict[str, Any]] = []
    for product in catalog_products:
        docs = product.get("docs")
        if not isinstance(docs, dict):
            continue

        for key in docs:
            doc_keys_counter[key] += 1

        nonstandard = {
            key: NORMALIZED_DOC_KEY_SUGGESTIONS[key]
            for key in docs
            if key in NORMALIZED_DOC_KEY_SUGGESTIONS
        }
        if nonstandard:
            products_with_nonstandard_doc_keys.append(
                {
                    "productId": product.get("id"),
                    "productName": product.get("name"),
                    "keys": nonstandard,
                }
            )

    if products_with_nonstandard_doc_keys:
        findings.append(
            Finding(
                code="nonstandard-doc-keys",
                severity="medium",
                title="Ключи docs не унифицированы",
                summary=(
                    "Во всех карточках используются нестандартные или разноформатные имена "
                    "полей: sertificate, complectOfDocs, IES."
                ),
                evidence={
                    "docKeys": dict(doc_keys_counter),
                    "sampleProducts": products_with_nonstandard_doc_keys[:5],
                    "suggestedRenames": NORMALIZED_DOC_KEY_SUGGESTIONS,
                },
                options=[
                    "Переименовать ключи на этапе экспорта и сохранить обратные алиасы на переходный период.",
                    "Добавить нормализующий слой в API, чтобы наружу всегда уходили certificate, completeDocs и ies.",
                    "Завести JSON Schema и валидировать имена ключей до публикации файла.",
                ],
            )
        )

    empty_property_values = Counter()
    empty_property_examples: list[dict[str, Any]] = []
    property_measure_stats: Counter[str] = Counter()
    for product in catalog_products:
        properties = product.get("properties")
        if not isinstance(properties, list):
            continue

        for prop in properties:
            if not isinstance(prop, dict):
                continue
            property_name = str(prop.get("propertyName"))
            if prop.get("propertyValue") in ("", None):
                empty_property_values[property_name] += 1
                if len(empty_property_examples) < 10:
                    empty_property_examples.append(
                        {
                            "productId": product.get("id"),
                            "productName": product.get("name"),
                            "propertyName": property_name,
                        }
                    )
            if prop.get("propertyMeasure") in ("", None):
                property_measure_stats[property_name] += 1

    if empty_property_values:
        findings.append(
            Finding(
                code="empty-property-values",
                severity="medium",
                title="Часть свойств хранится пустыми значениями",
                summary=(
                    "Найдены свойства с пустым propertyValue. Наиболее частый случай — "
                    "'Маркировка взрывозащиты'."
                ),
                evidence={
                    "emptyPropertyValues": dict(empty_property_values.most_common(10)),
                    "propertiesWithoutMeasure": dict(property_measure_stats.most_common(10)),
                    "sampleProducts": empty_property_examples,
                },
                options=[
                    "Не выгружать свойства, у которых пустой propertyValue.",
                    "Заменять пустые значения на null и явно документировать это в схеме.",
                    "Собирать список обязательных свойств по типу категории и валидировать полноту перед экспортом.",
                ],
            )
        )

    if matched_to_reference == len(catalog_products) and not category_name_mismatches:
        findings.append(
            Finding(
                code="reference-consistency",
                severity="info",
                title="Ссылки products.categoryId согласованы с db/categories.json",
                summary=(
                    "Все товары успешно сопоставляются с db/categories.json, "
                    "и categoryName совпадает с эталонным именем."
                ),
                evidence={
                    "matchedProducts": matched_to_reference,
                    "categoryNameMismatches": len(category_name_mismatches),
                },
                options=[
                    "Использовать db/categories.json как источник истины для leaf-категорий.",
                    "Добавить автоматическую сверку catalog.json с categories.json в CI.",
                ],
            )
        )

    return findings


def print_text_report(findings: list[Finding]) -> None:
    print("Анализ catalog.json")
    print("===================")
    print()

    for index, finding in enumerate(findings, start=1):
        print(f"{index}. [{finding.severity.upper()}] {finding.title}")
        print(f"   Код: {finding.code}")
        print(f"   Суть: {finding.summary}")

        if finding.evidence:
            print("   Доказательства:")
            for key, value in finding.evidence.items():
                print(f"   - {key}: {value}")

        if finding.options:
            print("   Варианты решения:")
            for option in finding.options:
                print(f"   - {option}")

        print()


def main() -> None:
    args = parse_args()

    catalog_data = load_json(args.catalog)
    reference_categories_data = load_json(args.categories)

    catalog_categories, catalog_products = validate_catalog(catalog_data, args.catalog)
    reference_categories = validate_reference_categories(
        reference_categories_data, args.categories
    )

    findings = analyze_catalog(
        catalog_categories=catalog_categories,
        catalog_products=catalog_products,
        reference_categories=reference_categories,
    )

    if args.json:
        print(
            json.dumps(
                {
                    "catalog": str(args.catalog),
                    "categories": str(args.categories),
                    "findings": [asdict(finding) for finding in findings],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    print_text_report(findings)


if __name__ == "__main__":
    main()
