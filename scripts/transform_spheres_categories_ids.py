#!/usr/bin/env python3
"""
Преобразует `db/spheres.json`:

1. В каждом списке `categoriesInSphere` добавляет поле `id` из `db/categories.json`
   по точному совпадению поля `name`.
2. Удаляет поле `url` у элементов списка.
3. Переименовывает поле `categoriesInSphere` в `categoriesId`.

Если в `categories.json` найдено несколько записей с одинаковым `name`, скрипт
пытается однозначно выбрать запись по `url` исходного элемента из `spheres.json`.
Если это не удаётся, выполнение завершается с ошибкой.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Добавляет category id в spheres.json и переименовывает categoriesInSphere в categoriesId."
    )
    parser.add_argument(
        "--spheres",
        type=Path,
        default=Path("db/spheres.json"),
        help="Путь к файлу spheres.json",
    )
    parser.add_argument(
        "--categories",
        type=Path,
        default=Path("db/categories.json"),
        help="Путь к файлу categories.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Куда записать результат. По умолчанию перезаписывает spheres.json.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Проверяет соответствия и показывает краткую статистику без записи файла.",
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
        raise SystemExit(f"Ожидался JSON-объект в {path}")

    value = data.get(key)
    if not isinstance(value, list):
        raise SystemExit(f"Ожидался список {key!r} в {path}")

    for item in value:
        if not isinstance(item, dict):
            raise SystemExit(f"Все элементы {key!r} в {path} должны быть объектами")

    return value


def build_categories_index(
    categories: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}

    for category in categories:
        name = category.get("name")
        category_id = category.get("id")
        if not name:
            continue
        if category_id is None:
            raise SystemExit(f"У категории {name!r} отсутствует поле 'id'")
        index.setdefault(str(name), []).append(category)

    return index


def resolve_category_id(
    category_item: dict[str, Any],
    categories_by_name: dict[str, list[dict[str, Any]]],
    sphere_name: str,
) -> int:
    name = category_item.get("name")
    if not name:
        raise SystemExit(
            f"В сфере {sphere_name!r} найдена категория без поля 'name': {category_item}"
        )

    matches = categories_by_name.get(str(name), [])
    if not matches:
        raise SystemExit(
            f"Не найдена категория с точным name={name!r} для сферы {sphere_name!r}"
        )

    if len(matches) == 1:
        return int(matches[0]["id"])

    source_url = category_item.get("url")
    if source_url:
        url_matches = [match for match in matches if match.get("url") == source_url]
        if len(url_matches) == 1:
            return int(url_matches[0]["id"])

    existing_id = category_item.get("id")
    if existing_id is not None:
        id_matches = [match for match in matches if match.get("id") == existing_id]
        if len(id_matches) == 1:
            return int(id_matches[0]["id"])

    match_descriptions = ", ".join(
        f"id={match.get('id')}, url={match.get('url')!r}" for match in matches
    )
    raise SystemExit(
        "Найдено несколько категорий с одинаковым "
        f"name={name!r} для сферы {sphere_name!r}. "
        f"Кандидаты: {match_descriptions}"
    )


def transform_category_item(
    item: dict[str, Any],
    categories_by_name: dict[str, list[dict[str, Any]]],
    sphere_name: str,
) -> dict[str, Any]:
    category_id = resolve_category_id(item, categories_by_name, sphere_name)
    return {"id": category_id}


def transform_categories_list(
    items: Any,
    categories_by_name: dict[str, list[dict[str, Any]]],
    sphere_name: str,
) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        raise SystemExit(
            f"Ожидался список категорий в сфере {sphere_name!r}, получено: {type(items).__name__}"
        )

    transformed_items: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise SystemExit(
                f"Все элементы категорий в сфере {sphere_name!r} должны быть объектами"
            )
        transformed_items.append(
            transform_category_item(item, categories_by_name, sphere_name)
        )

    return transformed_items


def transform_sphere(
    sphere: dict[str, Any],
    categories_by_name: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    transformed: dict[str, Any] = {}
    sphere_name = str(sphere.get("name", "<unknown sphere>"))

    for key, value in sphere.items():
        if key == "categoriesInSphere":
            transformed["categoriesId"] = transform_categories_list(
                value, categories_by_name, sphere_name
            )
            continue

        if key == "categoriesId" and "categoriesInSphere" not in sphere:
            transformed["categoriesId"] = transform_categories_list(
                value, categories_by_name, sphere_name
            )
            continue

        transformed[key] = value

    return transformed


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
    categories_by_name = build_categories_index(categories)

    transformed_spheres = [
        transform_sphere(sphere, categories_by_name) for sphere in spheres
    ]

    output_data = dict(spheres_data)
    output_data["spheres"] = transformed_spheres

    categories_count = sum(
        len(sphere.get("categoriesId", [])) for sphere in transformed_spheres
    )

    if args.dry_run:
        print(
            "Проверка пройдена: "
            f"сфер={len(transformed_spheres)}, категорий обновлено={categories_count}"
        )
        return 0

    output_path = args.output or args.spheres
    write_json(output_path, output_data)
    print(
        f"Готово: обновлено сфер={len(transformed_spheres)}, "
        f"категорий={categories_count}, файл={output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
