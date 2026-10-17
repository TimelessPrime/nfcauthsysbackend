import json
from pathlib import Path
from typing import Any

# src/config.py -> project root -> config/config.json
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "server": {
        "debug": False,
        "port": 5000,
        "host": "127.0.0.1",
        "reload": True
    }
}


def load_config() -> dict[str, Any]:
    """Create the config directory/file when missing, then load the JSON."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if not CONFIG_PATH.exists():
        with CONFIG_PATH.open("w", encoding="utf-8") as file:
            json.dump(DEFAULT_CONFIG, file, indent=2, ensure_ascii=False)
            file.write("\n")

    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


data = load_config()

def get_server_port() -> int:
    return data["server"]["port"]

def get_debug_status() -> bool:
    return data["server"]["debug"]

def get_host() -> str:
    return data["server"]["host"]

def get_reload() -> bool:
    return data["server"]["reload"]
