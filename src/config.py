import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
CONFIG_PATHS = [
    CONFIG_DIR / "config.json",
    BASE_DIR / "config.json",
]

DEFAULT_CONFIG: dict[str, Any] = {
    "server": {
        "debug": False,
        "port": 5000,
        "host": "0.0.0.0",
        "reload": True,
    },
    "tcp_server": {
        "enabled": True,
        "host": "0.0.0.0",
        "port": 1337,
        "use_tls": False,
        "certfile": "config/cert.pem",
        "keyfile": "config/key.pem",
    },
    "security": {
        "auth_token": "nfcschool_secret_token_2026",
        "require_auth": True,
        "handshake_version": "3-step",
    },
    "database": {
        "type": "mysql",
        "host": "127.0.0.1",
        "port": 3306,
        "user": "root",
        "password": "2000",
        "name": "nfc_attendance",
        "sqlite_path": "data/attendance.db",
        "failsafe": {
            "enabled": True,
            "user": "nfc_backup",
            "password": "backup_pass_2026",
            "host": "127.0.0.1",
            "port": 3306,
        },
    },
    "logging": {
        "level": "INFO",
        "directory": "log",
        "app_file": "app.log",
        "latest_file": "latest.log",
        "retention_days": 30,
        "max_file_size_mb": 10,
        "console": True,
    },
}


def _deep_merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    for k, v in source.items():
        if k in target and isinstance(target[k], dict) and isinstance(v, dict):
            _deep_merge(target[k], v)
        else:
            target[k] = deepcopy(v)


def load_config() -> dict[str, Any]:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config = deepcopy(DEFAULT_CONFIG)

    for path in CONFIG_PATHS:
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as file:
                    loaded = json.load(file)
                if isinstance(loaded, dict):
                    _deep_merge(config, loaded)
                    break
            except Exception:
                pass

    if "SERVER_HOST" in os.environ or "HOST" in os.environ:
        config["server"]["host"] = os.getenv("SERVER_HOST", os.getenv("HOST"))
    if "SERVER_PORT" in os.environ or "PORT" in os.environ:
        config["server"]["port"] = int(os.getenv("SERVER_PORT", os.getenv("PORT", "5000")))
    if "TCP_HOST" in os.environ:
        config["tcp_server"]["host"] = os.getenv("TCP_HOST")
    if "TCP_PORT" in os.environ:
        config["tcp_server"]["port"] = int(os.getenv("TCP_PORT", "1337"))
    if "TCP_USE_TLS" in os.environ:
        config["tcp_server"]["use_tls"] = os.getenv("TCP_USE_TLS", "false").lower() in ("true", "1", "yes")
    if "AUTH_TOKEN" in os.environ:
        config["security"]["auth_token"] = os.getenv("AUTH_TOKEN")
    if "REQUIRE_AUTH" in os.environ:
        config["security"]["require_auth"] = os.getenv("REQUIRE_AUTH", "true").lower() in ("true", "1", "yes")
    if "LOG_LEVEL" in os.environ:
        config["logging"]["level"] = os.getenv("LOG_LEVEL", "INFO").upper()
    elif config["server"].get("debug", False):
        config["logging"]["level"] = "DEBUG"
    if "DB_TYPE" in os.environ:
        config["database"]["type"] = os.getenv("DB_TYPE")
    if "DB_HOST" in os.environ:
        config["database"]["host"] = os.getenv("DB_HOST")
    if "DB_PORT" in os.environ:
        config["database"]["port"] = int(os.getenv("DB_PORT", "3306"))
    if "DB_USER" in os.environ:
        config["database"]["user"] = os.getenv("DB_USER")
    if "DB_PASSWORD" in os.environ:
        config["database"]["password"] = os.getenv("DB_PASSWORD")
    if "DB_NAME" in os.environ:
        config["database"]["name"] = os.getenv("DB_NAME")
    if "DB_FAILSAFE_USER" in os.environ:
        config["database"]["failsafe"]["user"] = os.getenv("DB_FAILSAFE_USER")
    if "DB_FAILSAFE_PASSWORD" in os.environ:
        config["database"]["failsafe"]["password"] = os.getenv("DB_FAILSAFE_PASSWORD")

    return config


data = load_config()


def get_config(key_path: str, default: Any = None) -> Any:
    keys = key_path.split(".")
    curr: Any = data
    for k in keys:
        if isinstance(curr, dict) and k in curr:
            curr = curr[k]
        else:
            return default
    return curr


def get_server_port() -> int:
    return int(data["server"]["port"])


def get_debug_status() -> bool:
    return bool(data["server"]["debug"])


def get_host() -> str:
    return str(data["server"]["host"])


def get_reload() -> bool:
    return bool(data["server"]["reload"])


def _get_section(name: str) -> dict[str, Any]:
    settings = data.get(name, {})
    default_section = DEFAULT_CONFIG.get(name, {})
    return {**default_section, **deepcopy(settings)}


def get_logging_config() -> dict[str, Any]:
    return _get_section("logging")


def get_tcp_config() -> dict[str, Any]:
    return _get_section("tcp_server")


def get_tcp_host() -> str:
    return str(get_tcp_config().get("host", "0.0.0.0"))


def get_tcp_port() -> int:
    return int(get_tcp_config().get("port", 1337))


def is_tls_enabled() -> bool:
    return bool(get_tcp_config().get("use_tls", False))


def get_tls_cert_path() -> Path:
    return BASE_DIR / str(get_tcp_config().get("certfile", "config/cert.pem"))


def get_tls_key_path() -> Path:
    return BASE_DIR / str(get_tcp_config().get("keyfile", "config/key.pem"))


def get_security_config() -> dict[str, Any]:
    return _get_section("security")


def get_auth_token() -> str:
    return str(get_security_config().get("auth_token", "nfcschool_secret_token_2026"))


def is_auth_required() -> bool:
    return bool(get_security_config().get("require_auth", True))


def get_handshake_version() -> str:
    return str(get_security_config().get("handshake_version", "3-step")).lower()


def get_database_config() -> dict[str, Any]:
    return _get_section("database")


def get_database_failsafe_config() -> dict[str, Any]:
    return get_database_config().get("failsafe", {})
