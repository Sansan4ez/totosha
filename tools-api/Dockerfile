FROM python:3.11-slim

ARG BUILD_GIT_SHA=unknown
ARG BUILD_TIME=unknown

ENV BUILD_GIT_SHA=${BUILD_GIT_SHA} \
    BUILD_TIME=${BUILD_TIME} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir fastapi uvicorn httpx pydantic asyncpg openai pgvector PyYAML prometheus-client \
        opentelemetry-sdk opentelemetry-exporter-otlp-proto-http \
        opentelemetry-instrumentation-aiohttp-client opentelemetry-instrumentation-httpx

# Copy application code
COPY src/ ./src/
COPY app.py .

EXPOSE 8100

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8100"]
