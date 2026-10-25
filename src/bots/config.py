import json
import os
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SEARCH_PATHS = [
    PROJECT_ROOT / "config" / "bot_config.json",
    PROJECT_ROOT / "bot_config.json",
]


def _load_bot_json() -> dict[str, Any]:
    for path in SEARCH_PATHS:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        data = json.loads(content)
                        if isinstance(data, dict):
                            return data.get("bot", data)
            except Exception:
                continue
    return {}


_bot_cfg = _load_bot_json()


def is_discord_bot_enabled() -> bool:
    env = os.environ.get("DISCORD_BOT_ENABLED")
    if env is not None:
        return env.lower() in ("true", "1", "yes")
    return bool(_bot_cfg.get("enabled", False) or bool(get_discord_token()))


def get_discord_token() -> str:
    return (os.environ.get("DISCORD_BOT_TOKEN") or _bot_cfg.get("token") or "").strip()


def get_bot_prefix() -> str:
    return (os.environ.get("DISCORD_BOT_PREFIX") or _bot_cfg.get("prefix") or "!").strip()


def get_notification_channel_id() -> int | None:
    raw = os.environ.get("DISCORD_CHANNEL_ID") or _bot_cfg.get("notification_channel_id") or _bot_cfg.get("channel_id")
    if raw:
        try:
            return int(str(raw).strip())
        except ValueError:
            pass
    return None


def get_guild_id() -> int | None:
    raw = os.environ.get("DISCORD_GUILD_ID") or _bot_cfg.get("guild_id")
    if raw:
        try:
            return int(str(raw).strip())
        except ValueError:
            pass
    return None


def is_sync_slash_commands() -> bool:
    return bool(_bot_cfg.get("sync_slash_commands", True))


def is_notifications_enabled() -> bool:
    return bool(_bot_cfg.get("enable_notifications", True))


def get_admin_roles() -> list[str]:
    roles = _bot_cfg.get("admin_roles") or ["Admin", "Teacher", "BanGiamHieu", "QuanTriVien"]
    return [str(r).strip() for r in roles]
