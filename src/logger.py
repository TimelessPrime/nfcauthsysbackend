import atexit
import logging
import os
import tarfile
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from src.config import BASE_DIR, get_logging_config

_LOG_CONFIG: dict[str, Any] = get_logging_config()
LOG_DIR: Path = BASE_DIR / str(_LOG_CONFIG.get("directory", "log"))
LATEST_LOG_FILE: str = str(_LOG_CONFIG.get("latest_file", "latest.log"))
APP_LOG_FILE: str = str(_LOG_CONFIG.get("app_file", "app.log"))
RETENTION_DAYS: int = int(_LOG_CONFIG.get("retention_days", 30))
MAX_FILE_SIZE_MB: int = int(_LOG_CONFIG.get("max_file_size_mb", 10))
CONSOLE_ENABLED: bool = bool(_LOG_CONFIG.get("console", True))
LOG_LEVEL: str = str(_LOG_CONFIG.get("level", "INFO")).upper()

MAX_BYTES_PER_LOG = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_TOTAL_ARCHIVES = 50
MAX_ARCHIVE_STORAGE_BYTES = 50 * 1024 * 1024

_logger_instance: logging.Logger | None = None


def setup_logger(name: str = "backend") -> logging.Logger:
    global _logger_instance  # noqa: PLW0603

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    logger.setLevel(level)
    logger.propagate = False

    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)

    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if CONSOLE_ENABLED:
        console = logging.StreamHandler()
        console.setLevel(level)
        console.setFormatter(formatter)
        logger.addHandler(console)

    latest_path = LOG_DIR / LATEST_LOG_FILE
    latest_handler = RotatingFileHandler(
        latest_path,
        maxBytes=MAX_BYTES_PER_LOG,
        backupCount=2,
        encoding="utf-8",
    )
    latest_handler.setLevel(level)
    latest_handler.setFormatter(formatter)
    logger.addHandler(latest_handler)

    app_log_path = LOG_DIR / APP_LOG_FILE
    app_handler = RotatingFileHandler(
        app_log_path,
        maxBytes=MAX_BYTES_PER_LOG,
        backupCount=5,
        encoding="utf-8",
    )
    app_handler.setLevel(level)
    app_handler.setFormatter(formatter)
    logger.addHandler(app_handler)

    _logger_instance = logger
    return logger


def get_logger(name: str = "backend") -> logging.Logger:
    global _logger_instance  # noqa: PLW0603
    if _logger_instance is None:
        return setup_logger(name)
    return _logger_instance


def cleanup_old_archives() -> int:
    if not LOG_DIR.exists():
        return 0

    now = datetime.now().astimezone().timestamp()
    max_age_seconds = RETENTION_DAYS * 86400
    removed_count = 0

    archives = sorted(
        [p for p in LOG_DIR.glob("*.tar.*") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
    )

    surviving: list[Path] = []
    for path in archives:
        try:
            stat = path.stat()
            if (now - stat.st_mtime) > max_age_seconds:
                path.unlink()
                removed_count += 1
            else:
                surviving.append(path)
        except OSError:
            pass

    total_size = sum(p.stat().st_size for p in surviving if p.exists())
    while (len(surviving) > MAX_TOTAL_ARCHIVES or total_size > MAX_ARCHIVE_STORAGE_BYTES) and surviving:
        oldest = surviving.pop(0)
        try:
            total_size -= oldest.stat().st_size
            oldest.unlink()
            removed_count += 1
        except OSError:
            pass

    return removed_count


def archive_latest_log() -> Path | None:
    latest_log = LOG_DIR / LATEST_LOG_FILE
    if not latest_log.is_file() or latest_log.stat().st_size == 0:
        return None

    cleanup_old_archives()

    timestamp = datetime.now().astimezone().strftime("%d-%m-%y_%H_%M_%S")
    archive_path = LOG_DIR / f"{timestamp}.tar.zst"

    suffix = 1
    while archive_path.exists():
        archive_path = LOG_DIR / f"{timestamp}_{suffix}.tar.zst"
        suffix += 1

    try:
        with tarfile.open(archive_path, mode="w:zst") as archive:
            archive.add(latest_log, arcname=LATEST_LOG_FILE)
        return archive_path
    except (tarfile.TarError, ValueError, OSError):
        gz_path = archive_path.with_suffix("").with_suffix(".tar.gz")
        with tarfile.open(gz_path, mode="w:gz") as archive:
            archive.add(latest_log, arcname=LATEST_LOG_FILE)
        return gz_path


def tail_log(filepath: Path | None = None, lines: int = 100, max_bytes: int = 65536) -> list[str]:
    target = filepath or (LOG_DIR / LATEST_LOG_FILE)
    if not target.exists() or not target.is_file():
        return []

    file_size = target.stat().st_size
    if file_size == 0:
        return []

    read_len = min(file_size, max_bytes)
    with target.open("rb") as f:
        f.seek(-read_len, os.SEEK_END)
        data = f.read(read_len)

    text = data.decode("utf-8", errors="ignore")
    line_list = text.splitlines()

    if read_len < file_size and len(line_list) > 1:
        line_list = line_list[1:]

    return line_list[-lines:]


def _shutdown_logger():
    if _logger_instance:
        for handler in _logger_instance.handlers[:]:
            handler.flush()
            handler.close()
            _logger_instance.removeHandler(handler)
    try:
        archive_latest_log()
    except Exception:  # noqa: BLE001
        pass


atexit.register(_shutdown_logger)
