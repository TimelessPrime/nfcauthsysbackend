"""Load application settings from ``config/config.json``."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "server": {
        "debug": False,
        "port": 5000,
        "host": "127.0.0.1",
        "reload": True,
    },
    "logging": {
        "level": "INFO",
        "directory": "log",
        "app_file": "app.log",
        "latest_file": "latest.log",
        "retention_days": 30,
        "console": True,
    },
}


def load_config() -> dict[str, Any]:
    """Create the config file if needed and merge it with default settings."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if not CONFIG_PATH.exists():
        with CONFIG_PATH.open("w", encoding="utf-8") as file:
            json.dump(DEFAULT_CONFIG, file, indent=2, ensure_ascii=False)
            file.write("\n")

    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        loaded = json.load(file)

    if not isinstance(loaded, dict):
        raise ValueError(f"Configuration root must be a JSON object: {CONFIG_PATH}")  # noqa: TRY004

    # Preserve compatibility with older config files that lack newer settings.
    # Each known section must be an object so its values can be merged safely.
    config = deepcopy(DEFAULT_CONFIG)
    for section, values in loaded.items():
        if section not in DEFAULT_CONFIG:
            config[section] = values
            continue

        if not isinstance(values, dict):
            raise ValueError(  # noqa: TRY004
                f"Configuration section '{section}' must be a JSON object: {CONFIG_PATH}"
            )

        config[section].update(values)
    return config


data = load_config()


def get_server_port() -> int:
    return int(data["server"]["port"])


def get_debug_status() -> bool:
    return bool(data["server"]["debug"])


def get_host() -> str:
    return str(data["server"]["host"])


def get_reload() -> bool:
    return bool(data["server"]["reload"])


def get_logging_config() -> dict[str, Any]:
    """Return logger.py's settings without exposing the shared config object."""
    settings = data.get("logging", {})
    if not isinstance(settings, dict):
        raise ValueError(f"Configuration section 'logging' must be a JSON object: {CONFIG_PATH}")  # noqa: TRY004

    # Fill any missing logging keys if a legacy or hand-edited config omits them.
    defaults = DEFAULT_CONFIG["logging"]
    return {**defaults, **deepcopy(settings)}
