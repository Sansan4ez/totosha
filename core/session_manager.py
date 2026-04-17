"""Session storage and cleanup helpers."""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from time import time
from typing import Optional

from config import CONFIG
from logger import agent_logger


@dataclass
class Session:
    """User session."""

    user_id: int
    chat_id: int
    cwd: str
    history: list
    blocked_count: int = 0
    source: str = "bot"
    created_at: float = 0.0
    last_activity_at: float = 0.0


class SessionManager:
    """Manage user sessions."""

    def __init__(self):
        self.sessions: dict[str, Session] = {}
        self.web_workspace_root = os.path.join(CONFIG.workspace, "_web")

    def get_key(self, user_id: int, chat_id: int, source: str = "bot") -> str:
        if source == "web":
            return f"web:{user_id}_{chat_id}"
        return f"{user_id}_{chat_id}"

    def _web_session_ttl_s(self) -> int:
        try:
            return max(60, int(os.getenv("AGENT_WEB_SESSION_TTL_S", "900")))
        except ValueError:
            return 900

    def _workspace_path(self, user_id: int, chat_id: int, source: str) -> str:
        if source == "web":
            return os.path.join(self.web_workspace_root, f"{user_id}_{chat_id}")
        return os.path.join(CONFIG.workspace, str(user_id))

    def _ensure_workspace(self, cwd: str):
        os.makedirs(cwd, exist_ok=True)
        try:
            os.chmod(cwd, 0o777)
        except:
            pass

    def _remove_web_workspace(self, cwd: str):
        try:
            workspace_root = Path(self.web_workspace_root).resolve()
            cwd_path = Path(cwd).resolve()
        except Exception:
            return
        if cwd_path != workspace_root and workspace_root not in cwd_path.parents:
            return
        shutil.rmtree(cwd_path, ignore_errors=True)

    def reclaim_expired_web_sessions(self, now: Optional[float] = None) -> int:
        now = now if now is not None else time()
        ttl_s = self._web_session_ttl_s()
        reclaimed = 0
        for key, session in list(self.sessions.items()):
            if getattr(session, "source", "bot") != "web":
                continue
            last_activity = getattr(session, "last_activity_at", 0.0) or getattr(
                session,
                "created_at",
                now,
            )
            if now - last_activity < ttl_s:
                continue
            self.sessions.pop(key, None)
            self._remove_web_workspace(session.cwd)
            agent_logger.info(f"Expired web session reclaimed: {key}")
            reclaimed += 1
        return reclaimed

    def get(self, user_id: int, chat_id: int, source: str = "bot") -> Session:
        if source == "web":
            self.reclaim_expired_web_sessions()
        key = self.get_key(user_id, chat_id, source)
        now = time()

        if key not in self.sessions:
            cwd = self._workspace_path(user_id, chat_id, source)
            self._ensure_workspace(cwd)
            self.sessions[key] = Session(
                user_id=user_id,
                chat_id=chat_id,
                cwd=cwd,
                history=[],
                source=source,
                created_at=now,
                last_activity_at=now,
            )
            agent_logger.info(f"New session: {key}")
        else:
            self.sessions[key].source = source
            self.sessions[key].last_activity_at = now

        return self.sessions[key]

    def reclaim(self, user_id: int, chat_id: int, source: str = "web") -> bool:
        key = self.get_key(user_id, chat_id, source)
        session = self.sessions.pop(key, None)
        if not session:
            return False
        if getattr(session, "source", source) == "web":
            self._remove_web_workspace(session.cwd)
        agent_logger.info(f"Session reclaimed: {key}")
        return True

    def clear(self, user_id: int, chat_id: int):
        key = self.get_key(user_id, chat_id)
        if key in self.sessions:
            self.sessions[key].history = []
            self.sessions[key].blocked_count = 0
            agent_logger.info(f"Session cleared: {key}")
