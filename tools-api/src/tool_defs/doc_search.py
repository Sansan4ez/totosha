"""Canonical doc_search tool definition."""

TOOLS = {
    "doc_search": {
        "enabled": True,
        "name": "doc_search",
        "description": "Search the normalized local document corpus across Markdown, PDFs, Office files, images, and promoted live records. Legacy doc/xls/ppt content is available only after doc-worker normalization. Use for explicit document context or fallback after corp_db_search empty/error.",
        "source": "builtin",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query for the local document corpus"},
                "top": {"type": "integer", "description": "How many documents to return (default 5)"},
            },
            "required": ["query"],
        },
    }
}
