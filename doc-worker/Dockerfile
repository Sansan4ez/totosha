FROM python:3.11-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    fd-find \
    imagemagick \
    jq \
    libreoffice \
    nodejs \
    npm \
    ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/fdfind /usr/bin/fd \
    && ln -sf /usr/bin/convert /usr/local/bin/magick \
    && npm install -g @llamaindex/liteparse

COPY core/documents/ /app/documents/
COPY doc-worker/worker.py /app/worker.py
COPY doc-worker/README.md /app/README.md

ENV CORP_DOCS_ROOT=/data/corp_docs \
    DOC_REPO_ROOT=/repo \
    DOC_SEARCH_ENABLE_LEGACY_OFFICE=1

ENTRYPOINT ["python3", "/app/worker.py"]
CMD ["--help"]
