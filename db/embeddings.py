from __future__ import annotations

import os

from openai import AsyncOpenAI

from common import DEFAULT_PROXY_URL, EMBEDDING_DIMENSIONS, EMBEDDING_MODEL


_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=DEFAULT_PROXY_URL,
            api_key=os.getenv("PROXY_API_KEY", "proxy"),
        )
    return _client


async def get_embeddings(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    payload = [text if text.strip() else "(empty)" for text in texts]
    response = await get_client().embeddings.create(
        model=EMBEDDING_MODEL,
        input=payload,
        dimensions=EMBEDDING_DIMENSIONS,
    )
    return [item.embedding for item in response.data]
