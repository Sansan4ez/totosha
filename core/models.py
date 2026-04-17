"""Common types for Core"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ToolResult:
    """Result of tool execution"""
    success: bool
    output: str = ""
    error: str = ""
    metadata: Optional[dict] = None  # Optional metadata (e.g. loaded tool definitions)


@dataclass
class ToolContext:
    """Context passed to tool execution"""
    cwd: str
    session_id: str = ""
    user_id: int = 0
    chat_id: int = 0
    chat_type: str = "private"
    source: str = "bot"  # 'bot', 'userbot', or 'web'
    is_admin: bool = False  # Admin users bypass some security patterns


@dataclass
class ChatResponsePayload:
    """Stable API response contract shared by chat channels."""

    response: Optional[str]
    source: str
    disabled: bool = False
    access_denied: bool = False
    ui_artifact: Optional[dict] = None
    conversation: Optional[dict] = None
    error: Optional[str] = None
    meta: Optional[dict] = None
