"""Deprecated alias for the canonical `doc_search` tool."""

from __future__ import annotations

from models import ToolContext, ToolResult
from tools.doc_search import _run_doc_search_tool


async def tool_corp_wiki_search(args: dict, ctx: ToolContext) -> ToolResult:
    return await _run_doc_search_tool(args, ctx, tool_name="corp_wiki_search", alias_for="doc_search")
