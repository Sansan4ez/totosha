"""Corporate DB tool definitions.

Execution is implemented in core as a thin client calling tools-api routes.
"""

TOOLS = {
    "corp_db_search": {
        "enabled": True,
        "name": "corp_db_search",
        "description": (
            "Search corporate Supabase/PostgREST database (server-side via tools-api; read-only). "
            "kind: lamp_exact, lamp_suggest, sku_by_code, category_lamps, portfolio_by_sphere, sphere_categories."
        ),
        "source": "builtin",
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "description": "Operation kind",
                    "enum": [
                        "lamp_exact",
                        "lamp_suggest",
                        "sku_by_code",
                        "category_lamps",
                        "portfolio_by_sphere",
                        "sphere_categories",
                    ],
                },
                "limit": {"type": "integer", "description": "Max rows (clamped to <=20)", "default": 5},
                "offset": {"type": "integer", "description": "Offset (clamped to <=200)", "default": 0},
                "name": {"type": "string", "description": "Exact lamp name (kind=lamp_exact)"},
                "query": {"type": "string", "description": "Search query (kind=lamp_suggest)"},
                "etm": {"type": "string", "description": "ETM code (kind=sku_by_code; provide exactly one of etm/oracl)"},
                "oracl": {"type": "string", "description": "ORACL code (kind=sku_by_code; provide exactly one of etm/oracl)"},
                "category": {"type": "string", "description": "Category name (kind=category_lamps)"},
                "sphere": {"type": "string", "description": "Sphere name (kind=portfolio_by_sphere / sphere_categories)"},
                "fuzzy": {"type": "boolean", "description": "Use FTS fallback when supported", "default": False},
            },
            "required": ["kind"],
        },
    }
}
