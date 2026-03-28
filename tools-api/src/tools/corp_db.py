"""Corporate DB tool definitions.

Execution is implemented in core as a thin client calling tools-api routes.
"""

TOOLS = {
    "corp_db_search": {
        "enabled": True,
        "name": "corp_db_search",
        "description": (
            "Search internal corporate Postgres database (server-side via tools-api; read-only). "
            "Supports hybrid KB/entity search, exact code lookups, lamp filters, categories, spheres, "
            "portfolio, and mounting compatibility."
        ),
        "source": "builtin",
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "description": "Operation kind",
                    "enum": [
                        "hybrid_search",
                        "lamp_exact",
                        "lamp_suggest",
                        "sku_by_code",
                        "category_lamps",
                        "portfolio_by_sphere",
                        "sphere_categories",
                        "lamp_filters",
                        "category_mountings",
                    ],
                },
                "limit": {"type": "integer", "description": "Max rows (clamped to <=10)", "default": 5},
                "offset": {"type": "integer", "description": "Offset (clamped to <=200)", "default": 0},
                "query": {"type": "string", "description": "Search query for hybrid/entity search and suggestions"},
                "profile": {
                    "type": "string",
                    "description": "Hybrid-search preset profile",
                    "enum": ["kb_search", "entity_resolver", "candidate_generation", "related_evidence"],
                },
                "entity_types": {
                    "type": "array",
                    "description": "Optional entity-type override for hybrid search",
                    "items": {"type": "string"},
                },
                "include_debug": {"type": "boolean", "description": "Include hybrid ranking debug info", "default": False},
                "name": {"type": "string", "description": "Exact lamp name (kind=lamp_exact)"},
                "etm": {"type": "string", "description": "ETM code (kind=sku_by_code; provide exactly one of etm/oracl)"},
                "oracl": {"type": "string", "description": "ORACL code (kind=sku_by_code; provide exactly one of etm/oracl)"},
                "category": {"type": "string", "description": "Category name (kind=category_lamps)"},
                "sphere": {"type": "string", "description": "Sphere name (kind=portfolio_by_sphere / sphere_categories)"},
                "mounting_type": {"type": "string", "description": "Mounting type name/mark or lamp mounting filter"},
                "ip": {"type": "string", "description": "Ingress protection filter, e.g. IP65"},
                "voltage_kind": {"type": "string", "description": "Voltage kind filter", "enum": ["AC", "DC", "AC/DC"]},
                "explosion_protected": {"type": "boolean", "description": "Explosion-protected filter"},
                "power_w_min": {"type": "integer", "description": "Minimum power in watts"},
                "power_w_max": {"type": "integer", "description": "Maximum power in watts"},
                "flux_lm_min": {"type": "integer", "description": "Minimum luminous flux in lumens"},
                "flux_lm_max": {"type": "integer", "description": "Maximum luminous flux in lumens"},
                "cct_k_min": {"type": "integer", "description": "Minimum color temperature in kelvin"},
                "cct_k_max": {"type": "integer", "description": "Maximum color temperature in kelvin"},
                "temp_c_min": {"type": "integer", "description": "Minimum operating temperature overlap"},
                "temp_c_max": {"type": "integer", "description": "Maximum operating temperature overlap"},
                "fuzzy": {"type": "boolean", "description": "Use FTS fallback when supported", "default": False},
            },
            "required": ["kind"],
        },
    }
}
