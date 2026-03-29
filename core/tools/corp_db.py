"""Corporate DB tool executor.

Core executes corp_db_search by calling tools-api over internal network.
No database credentials are stored in core or sandbox.
"""

from __future__ import annotations

import aiohttp
import json
import os

from models import ToolResult, ToolContext
from observability import REQUEST_ID as OBS_REQUEST_ID


async def tool_corp_db_search(args: dict, ctx: ToolContext) -> ToolResult:
    tools_api_url = os.getenv("TOOLS_API_URL", "http://tools-api:8100")

    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            request_id = OBS_REQUEST_ID.get("-")
            headers = {
                "X-User-Id": str(ctx.user_id),
                "X-Chat-Type": str(ctx.chat_type),
            }
            if request_id and request_id != "-":
                headers["X-Request-Id"] = request_id
            async with session.post(
                f"{tools_api_url}/corp-db/search",
                json=args,
                headers=headers,
            ) as resp:
                text = await resp.text()

                if resp.status != 200:
                    # tools-api returns plain error strings sometimes; keep short.
                    return ToolResult(False, error=f"corp_db_search failed: {resp.status}: {text[:300]}")

                # Pretty-print JSON for LLM readability when possible.
                try:
                    data = json.loads(text)
                    return ToolResult(True, output=json.dumps(data, ensure_ascii=False, indent=2))
                except Exception:
                    return ToolResult(True, output=text)
    except Exception as e:
        return ToolResult(False, error=f"corp_db_search error: {e}")
