FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY common.py /app/common.py
COPY observability.py /app/observability.py
COPY embeddings.py /app/embeddings.py
COPY catalog_loader.py /app/catalog_loader.py
COPY kb_loader.py /app/kb_loader.py
COPY live_migration.py /app/live_migration.py
COPY search_docs.py /app/search_docs.py
COPY transform_catalog_json.py /app/transform_catalog_json.py
COPY worker.py /app/worker.py
COPY knowledge_base_manifest.yaml /app/knowledge_base_manifest.yaml

ENTRYPOINT ["python3", "/app/worker.py"]
CMD ["--help"]
