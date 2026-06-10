"""Core configuration"""

import os
import json
from dataclasses import dataclass
from typing import Any


ADMIN_CONFIG_FILE = "/workspace/_shared/admin_config.json"


def read_secret(name: str, default: str = "") -> str:
    """Read secret from Docker Secrets or env"""
    paths = [f"/run/secrets/{name}", f"/run/secrets/{name}.txt"]
    for path in paths:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    value = f.read().strip()
                    if value:
                        return value
            except:
                pass
    return default


@dataclass
class Config:
    """Central configuration"""
    # API
    api_port: int = 4000
    proxy_url: str = ""
    model: str = "gpt-4"
    temperature: float = 0.7
    
    # Agent
    max_iterations: int = 30
    max_history: int = 10
    max_tool_output: int = 8000
    max_context_messages: int = 40
    max_blocked_commands: int = 10
    
    # Timeouts (seconds)
    tool_timeout: int = 120
    command_timeout: int = 60
    web_timeout: int = 30
    
    # Storage
    max_memory_chars: int = 4000
    max_chat_history_chars: int = 15000
    max_chat_messages: int = 200
    
    # Paths
    workspace: str = "/workspace"
    shared_dir: str = "/workspace/_shared"
    
    # Callbacks
    bot_url: str = "http://bot:4001"
    userbot_url: str = "http://userbot:8080"
    web_enabled: bool = False


def _load_admin_config() -> dict:
    """Load admin config from JSON file"""
    if os.path.exists(ADMIN_CONFIG_FILE):
        try:
            with open(ADMIN_CONFIG_FILE) as f:
                return json.load(f)
        except:
            pass
    return {}


def get_agent_config(key: str, default: Any = None) -> Any:
    """Get agent config value, preferring admin config over defaults
    
    Priority: admin_config.json > env > default
    """
    admin_cfg = _load_admin_config()
    agent_cfg = admin_cfg.get("agent", {})
    return agent_cfg.get(key, default)


def get_access_mode() -> str:
    """Return effective core access mode.

    Priority: admin_config.json > env > default.
    """
    admin_cfg = _load_admin_config()
    access_cfg = admin_cfg.get("access", {})
    mode = access_cfg.get("mode")
    if mode:
        return mode

    env_mode = os.getenv("ACCESS_MODE", "admin_only")
    if env_mode == "admin":
        return "admin_only"
    return env_mode


# Base config from env/secrets (defaults)
_base_model = read_secret("model_name", os.getenv("MODEL_NAME", "gpt-4"))

CONFIG = Config(
    api_port=int(os.getenv("API_PORT", "4000")),
    proxy_url=os.getenv("PROXY_URL", ""),
    model=_base_model,
    temperature=float(os.getenv("MODEL_TEMPERATURE", "0.7")),
    workspace=os.getenv("WORKSPACE", "/workspace"),
    bot_url=os.getenv("BOT_URL", "http://bot:4001"),
    userbot_url=os.getenv("USERBOT_URL", "http://userbot:8080"),
    web_enabled=os.getenv("WEB_ENABLED", "false").lower() == "true",
)


def get_model() -> str:
    """Get current model name (from admin config or default)"""
    return get_agent_config("model", CONFIG.model)


def get_temperature() -> float:
    """Get current temperature (from admin config or default)"""
    return float(get_agent_config("temperature", CONFIG.temperature))


def get_max_iterations() -> int:
    """Get max iterations (from admin config or default)"""
    return int(get_agent_config("max_iterations", CONFIG.max_iterations))
