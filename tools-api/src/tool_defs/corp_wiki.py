"""Corporate wiki search tool definition."""

TOOLS = {
    "corp_wiki_search": {
        "enabled": True,
        "name": "corp_wiki_search",
        "description": "Deprecated alias of doc_search. Search the normalized local document corpus for explicit document context or fallback after corp_db_search empty/error. Legacy doc/xls/ppt content is available only after doc-worker normalization.",
        "source": "builtin",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query for the local document corpus"},
                "top": {"type": "integer", "description": "How many documents to return (default 5)"},
                "include_legacy": {"type": "boolean", "description": "Whether to include the legacy wiki corpus (default true)"},
            },
            "required": ["query"],
        },
    }
}
