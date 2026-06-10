from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Iterable, Iterator, Sequence
from urllib.parse import quote
from urllib.parse import unquote, urlparse


EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIMENSIONS = 1536

DEFAULT_SOURCES_DIR = Path(os.getenv("CORP_DB_SOURCES_DIR", "/data/corp_pg_db/sources"))
DEFAULT_WIKI_DIR = Path(os.getenv("CORP_DB_WIKI_DIR", "/data/skills/corp-wiki-md-search/wiki"))
DEFAULT_KB_MANIFEST = Path(os.getenv("CORP_DB_KB_MANIFEST", "/app/knowledge_base_manifest.yaml"))
DEFAULT_RW_DSN_SECRET = Path("/run/secrets/corp_db_rw_dsn")
DEFAULT_ADMIN_PASSWORD_SECRET = Path("/run/secrets/postgres_password")
DEFAULT_PROXY_URL = os.getenv("PROXY_URL", "http://proxy:3200/v1").rstrip("/")

WS_RE = re.compile(r"\s+")
TOKEN_SPLIT_RE = re.compile(r"[^0-9A-Za-zА-Яа-я]+")


def read_secret_or_env(secret_path: Path, env_name: str, default: str = "") -> str:
    try:
        value = secret_path.read_text(encoding="utf-8").strip()
        if value:
            return value
    except FileNotFoundError:
        pass
    return os.getenv(env_name, default).strip()


def get_rw_dsn() -> str:
    dsn = read_secret_or_env(DEFAULT_RW_DSN_SECRET, "CORP_DB_RW_DSN")
    if not dsn:
        raise RuntimeError("CORP_DB_RW_DSN is not configured")
    return dsn


def get_admin_dsn() -> str:
    password = read_secret_or_env(DEFAULT_ADMIN_PASSWORD_SECRET, "POSTGRES_PASSWORD")
    if not password:
        raise RuntimeError("postgres admin password is not configured")

    user = os.getenv("CORP_DB_ADMIN_USER", "postgres").strip() or "postgres"
    host = os.getenv("CORP_DB_ADMIN_HOST", "corp-db").strip() or "corp-db"
    port = os.getenv("CORP_DB_PORT", "5432").strip() or "5432"
    dbname = os.getenv("CORP_DB_NAME", "corp_pg_db").strip() or "corp_pg_db"
    return f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}/{quote(dbname, safe='')}"


def normalize_ws(value: object | None) -> str:
    if value is None:
        return ""
    text = str(value).replace("\u00a0", " ").strip()
    if not text:
        return ""
    return WS_RE.sub(" ", text)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json_file(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def json_hash(payload: object) -> str:
    return sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def compact_preview(text: str, limit: int = 240) -> str:
    value = normalize_ws(text)
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def join_nonempty(parts: Sequence[object | None], sep: str = " | ") -> str:
    values = [normalize_ws(part) for part in parts]
    return sep.join(value for value in values if value)


def url_tokens(url: str | None) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    raw = " ".join(part for part in [parsed.path, parsed.query, parsed.fragment] if part)
    normalized = unquote(raw).replace("/", " ").replace("-", " ").replace("_", " ")
    return normalize_ws(normalized)


def tokenize_text(value: str | None) -> str:
    text = normalize_ws(value)
    if not text:
        return ""
    tokens = [token for token in TOKEN_SPLIT_RE.split(text) if token]
    return " ".join(tokens)


def batched(items: Sequence[object], batch_size: int) -> Iterator[Sequence[object]]:
    for index in range(0, len(items), batch_size):
        yield items[index:index + batch_size]


def bool_from_any(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def int_from_any(value: object | None) -> int | None:
    if value is None:
        return None
    text = normalize_ws(value)
    if not text:
        return None
    return int(text)


def stable_portfolio_id(name: str, url: str | None, group_name: str | None, sphere_id: int | None) -> str:
    return "portfolio:" + sha256_text(join_nonempty([url, name, group_name, sphere_id]))[:24]
