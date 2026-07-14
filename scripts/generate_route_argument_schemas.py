#!/usr/bin/env python3
"""RFC-029 workstream 4: materialize each route's selector-visible argument schema
into a standalone core/routes/<family>/<leaf>.schema.json file.

The JSON file is the machine-executed contract (validated in CI and loaded by
documents.routing); the YAML card keeps only human-authored prose plus a schema_ref.
Re-run this script when canonical enum sources (db/spheres.json, db/mounting_types.json,
series catalog) or a route's executor template change, then commit the diff.

Run from the repo root inside the core image:
    docker run --rm --entrypoint python -v /home/admin/totosha:/repo -w /repo/core \
        totosha-core ../scripts/generate_route_argument_schemas.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parents[1] / "core"
sys.path.insert(0, str(CORE_DIR))

from documents import routing  # noqa: E402


def main() -> int:
    routes_dir = routing.static_route_catalog_dir()
    written = 0
    for card_path in sorted(routes_dir.glob("*/*.yaml")):
        import yaml

        payload = yaml.safe_load(card_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not payload.get("route_id"):
            continue
        route = dict(payload)
        # Regenerate from the executor template + allowlists, not from any existing
        # schema file, so the script is the single refresh path.
        route.pop("argument_schema", None)
        route.pop("argument_schema_origin", None)
        routing._apply_runtime_argument_overrides(route)
        schema = route.get("argument_schema") or {}
        schema_path = routing._route_schema_file_path(card_path, payload)
        schema_path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written += 1
        print(f"wrote {schema_path.relative_to(routes_dir)}")
    print(f"{written} schema files written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
