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


def _parse_channel_id(val: Any) -> int | None:
    if val:
        try:
            return int(str(val).strip())
        except ValueError:
            pass
    return None


def get_noti_channel_id() -> int | None:
    raw = (
        os.environ.get("DISCORD_NOTI_CHANNEL_ID")
        or os.environ.get("DISCORD_CHANNEL_ID")
        or _bot_cfg.get("channel_noti")
        or _bot_cfg.get("noti_channel_id")
        or _bot_cfg.get("notification_channel_id")
        or _bot_cfg.get("channel_id")
    )
    return _parse_channel_id(raw)


def get_status_channel_id() -> int | None:
    raw = (
        os.environ.get("DISCORD_STATUS_CHANNEL_ID")
        or _bot_cfg.get("channel_status")
        or _bot_cfg.get("status_channel_id")
    )
    ch = _parse_channel_id(raw)
    return ch if ch else get_noti_channel_id()


def get_reg_channel_id() -> int | None:
    raw = (
        os.environ.get("DISCORD_REG_CHANNEL_ID")
        or _bot_cfg.get("channel_reg")
        or _bot_cfg.get("reg_channel_id")
    )
    ch = _parse_channel_id(raw)
    return ch if ch else get_noti_channel_id()


def get_info_channel_id() -> int | None:
    raw = (
        os.environ.get("DISCORD_INFO_CHANNEL_ID")
        or _bot_cfg.get("channel_info")
        or _bot_cfg.get("info_channel_id")
    )
    ch = _parse_channel_id(raw)
    return ch if ch else get_noti_channel_id()


def get_notification_channel_id() -> int | None:
    return get_noti_channel_id()


def get_all_channel_ids() -> dict[str, int | None]:
    return {
        "status": get_status_channel_id(),
        "noti": get_noti_channel_id(),
        "reg": get_reg_channel_id(),
        "info": get_info_channel_id(),
    }


def set_channel_id(channel_type: str, channel_id: int | str) -> bool:
    global _bot_cfg
    norm_type = channel_type.strip().lower()
    type_keys = {
        "status": "channel_status",
        "noti": "channel_noti",
        "notification": "channel_noti",
        "reg": "channel_reg",
        "registration": "channel_reg",
        "info": "channel_info",
    }
    key = type_keys.get(norm_type)
    if not key:
        return False

    val_str = str(channel_id).strip()
    _bot_cfg[key] = val_str
    if key == "channel_noti":
        _bot_cfg["channel_id"] = val_str
        _bot_cfg["notification_channel_id"] = val_str

    for path in SEARCH_PATHS:
        try:
            full_data = {}
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        full_data = json.loads(content)
            if "bot" in full_data and isinstance(full_data["bot"], dict):
                full_data["bot"][key] = val_str
                if key == "channel_noti":
                    full_data["bot"]["channel_id"] = val_str
                    full_data["bot"]["notification_channel_id"] = val_str
            else:
                full_data[key] = val_str
                if key == "channel_noti":
                    full_data["channel_id"] = val_str
                    full_data["notification_channel_id"] = val_str

            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(full_data, f, indent=2, ensure_ascii=False)
            return True
        except Exception:
            continue
    return False


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
