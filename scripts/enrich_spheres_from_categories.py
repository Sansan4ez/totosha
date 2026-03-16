#!/usr/bin/env python3
"""
Добавляет `id` и `image` в db/spheres.json на основе db/categories.json.

По умолчанию обновляет файл на месте:
    python scripts/enrich_spheres_from_categories.py

Можно указать свои пути:
    python scripts/enrich_spheres_from_categories.py \
        --spheres db/spheres.json \
        --categories db/categories.json \
        --output db/spheres.json
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
        description="Заполняет id и image для сфер из categories.json."
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
        "--output",
        type=Path,
        default=None,
        help="Куда записать результат. По умолчанию обновляет spheres.json на месте.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только проверить, что все сферы могут быть сопоставлены.",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SystemExit(f"Файл не найден: {path}") from error
    except json.JSONDecodeError as error:
        raise SystemExit(f"Некорректный JSON в {path}: {error}") from error


def build_index(items: list[dict[str, Any]], field: str) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}

    for item in items:
        value = item.get(field)
        if not value:
            continue
        index.setdefault(str(value), []).append(item)

    return index


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

    if "id" not in match or "image" not in match:
        raise SystemExit(
            "В categories.json не хватает id или image для категории "
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
            enriched["image"] = category["image"]
            inserted = True

    if not inserted:
        enriched["id"] = category["id"]
        enriched["image"] = category["image"]

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
    changed_count = 0

    for sphere in spheres:
        category = match_category(sphere, categories_by_name, categories_by_url)
        enriched = enrich_sphere(sphere, category)
        if sphere.get("id") != category["id"] or sphere.get("image") != category["image"]:
            changed_count += 1
        enriched_spheres.append(enriched)

    output_data = dict(spheres_data)
    output_data["spheres"] = enriched_spheres

    if args.dry_run:
        print(f"Проверка пройдена: {len(enriched_spheres)} сфер готовы к обновлению.")
        return 0

    output_path = args.output or args.spheres
    write_json(output_path, output_data)

    print(
        f"Готово: обновлено {changed_count} сфер. "
        f"Результат записан в {output_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
