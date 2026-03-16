#!/usr/bin/env python3
"""
Синхронизирует db/spheres.json и db/categories.json.

Что делает:
1. Добавляет `id` в каждую сферу из подходящей записи в categories.json.
2. Удаляет `image` из сфер, если поле уже было записано ранее.
3. Удаляет из списка `categories` те записи, которые соответствуют сферам.

По умолчанию обновляет оба файла на месте:
    python scripts/enrich_spheres_from_categories.py

Можно указать свои пути:
    python scripts/enrich_spheres_from_categories.py \
        --spheres db/spheres.json \
        --categories db/categories.json \
        --spheres-output db/spheres.json \
        --categories-output db/categories.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Добавляет id в сферы и удаляет эти сферы из categories.json."
    )
    parser.add_argument(
        "--spheres",
        type=Path,
        default=Path("db/spheres.json"),
        help="Путь до spheres.json",
    )
    parser.add_argument(
        "--categories",
        type=Path,
        default=Path("db/categories.json"),
        help="Путь до categories.json",
    )
    parser.add_argument(
        "--spheres-output",
        type=Path,
        default=None,
        help="Куда записать обновленный spheres.json. По умолчанию перезаписывает исходный файл.",
    )
    parser.add_argument(
        "--categories-output",
        type=Path,
        default=None,
        help="Куда записать обновленный categories.json. По умолчанию перезаписывает исходный файл.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только проверить соответствия и показать, сколько записей будет изменено.",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SystemExit(f"Файл не найден: {path}") from error
    except json.JSONDecodeError as error:
        raise SystemExit(f"Некорректный JSON в {path}: {error}") from error


def validate_root(data: Any, key: str, path: Path) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        raise SystemExit(f"Ожидался объект JSON в {path}")

    value = data.get(key)
    if not isinstance(value, list):
        raise SystemExit(f"Ожидался список {key!r} в {path}")

    for item in value:
        if not isinstance(item, dict):
            raise SystemExit(f"Все элементы {key!r} в {path} должны быть объектами")

    return value


def build_index(items: list[dict[str, Any]], field: str) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}

    for item in items:
        value = item.get(field)
        if value:
            index.setdefault(str(value), []).append(item)

    return index


def match_category(
    sphere: dict[str, Any],
    categories_by_name: dict[str, list[dict[str, Any]]],
    categories_by_url: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    sphere_name = sphere.get("sphereName")
    sphere_url = sphere.get("sphereUrl")

    matches_by_name = categories_by_name.get(str(sphere_name), []) if sphere_name else []
    matches_by_url = categories_by_url.get(str(sphere_url), []) if sphere_url else []

    if len(matches_by_name) > 1:
        raise SystemExit(
            "Найдено несколько категорий с name="
            f"{sphere_name!r} в categories.json"
        )

    if len(matches_by_url) > 1:
        raise SystemExit(
            "Найдено несколько категорий с url="
            f"{sphere_url!r} в categories.json"
        )

    match_by_name = matches_by_name[0] if matches_by_name else None
    match_by_url = matches_by_url[0] if matches_by_url else None

    if match_by_name and match_by_url and match_by_name is not match_by_url:
        raise SystemExit(
            "Найдена неоднозначность для сферы "
            f"{sphere_name!r}: совпадения по name и url указывают на разные категории"
        )

    match = match_by_name or match_by_url
    if not match:
        raise SystemExit(
            "Не удалось сопоставить сферу "
            f"{sphere_name!r} ({sphere_url!r}) с записью в categories.json"
        )

    if "id" not in match:
        raise SystemExit(
            "В categories.json не хватает id для категории "
            f"{match.get('name')!r}"
        )

    return match


def enrich_sphere(sphere: dict[str, Any], category: dict[str, Any]) -> dict[str, Any]:
    enriched: dict[str, Any] = {}
    inserted = False

    for key, value in sphere.items():
        if key in {"id", "image"}:
            continue

        enriched[key] = value
        if key == "sphereUrl":
            enriched["id"] = category["id"]
            inserted = True

    if not inserted:
        enriched["id"] = category["id"]

    return enriched


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=4)
        tmp.write("\n")
        temp_path = Path(tmp.name)

    temp_path.replace(path)


def main() -> int:
    args = parse_args()

    spheres_data = load_json(args.spheres)
    categories_data = load_json(args.categories)

    spheres = validate_root(spheres_data, "spheres", args.spheres)
    categories = validate_root(categories_data, "categories", args.categories)

    categories_by_name = build_index(categories, "name")
    categories_by_url = build_index(categories, "url")

    enriched_spheres: list[dict[str, Any]] = []
    matched_category_objects: set[int] = set()
    updated_spheres = 0

    for sphere in spheres:
        category = match_category(sphere, categories_by_name, categories_by_url)
        enriched = enrich_sphere(sphere, category)
        matched_category_objects.add(id(category))

        if enriched != sphere:
            updated_spheres += 1

        enriched_spheres.append(enriched)

    filtered_categories = [
        category for category in categories if id(category) not in matched_category_objects
    ]
    removed_categories = len(categories) - len(filtered_categories)

    if removed_categories != len(spheres):
        raise SystemExit(
            "Ожидалось удалить столько же категорий, сколько сфер найдено. "
            f"Сферы: {len(spheres)}, удалено категорий: {removed_categories}"
        )

    if args.dry_run:
        print(
            "Проверка пройдена: "
            f"обновится сфер: {updated_spheres}, "
            f"удалится категорий: {removed_categories}."
        )
        return 0

    spheres_output_path = args.spheres_output or args.spheres
    categories_output_path = args.categories_output or args.categories

    updated_spheres_data = dict(spheres_data)
    updated_spheres_data["spheres"] = enriched_spheres

    updated_categories_data = dict(categories_data)
    updated_categories_data["categories"] = filtered_categories

    write_json(spheres_output_path, updated_spheres_data)
    write_json(categories_output_path, updated_categories_data)

    print(
        "Готово: "
        f"обновлено сфер: {updated_spheres}, "
        f"удалено категорий: {removed_categories}."
    )
    print(f"spheres.json: {spheres_output_path}")
    print(f"categories.json: {categories_output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
