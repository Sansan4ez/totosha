"""Shared admin API authentication helpers for operator-side scripts."""

from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ADMIN_TOKEN_SECRET = "admin_password"


class AdminTokenNotFound(RuntimeError):
    """Raised when an operator script needs admin API authentication."""


def load_admin_token(*, repo_root: Path = REPO_ROOT) -> str:
    """Read the admin API token from configured, container, or repo secret paths."""
    configured_paths = (
        os.getenv("ADMIN_TOKEN_FILE"),
        os.getenv("ADMIN_PASSWORD_FILE"),
    )
    fallback_paths = (
        f"/run/secrets/{DEFAULT_ADMIN_TOKEN_SECRET}",
        str(repo_root / "secrets" / f"{DEFAULT_ADMIN_TOKEN_SECRET}.txt"),
    )

    seen: set[Path] = set()
    for raw_path in (*configured_paths, *fallback_paths):
        if not raw_path:
            continue
        path = Path(raw_path).expanduser()
        if path in seen:
            continue
        seen.add(path)
        try:
            token = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if token:
            return token

    raise AdminTokenNotFound(
        "admin token not found; set ADMIN_TOKEN_FILE or ADMIN_PASSWORD_FILE, "
        f"or create secrets/{DEFAULT_ADMIN_TOKEN_SECRET}.txt"
    )


def admin_headers(*, repo_root: Path = REPO_ROOT) -> dict[str, str]:
    """Return headers required by protected ``/api/admin/*`` endpoints."""
    return {"X-Admin-Token": load_admin_token(repo_root=repo_root)}
