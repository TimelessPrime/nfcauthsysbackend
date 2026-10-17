"""Central application logging configured through ``src.config``."""

import gzip
import logging
import re
import shutil
import sys
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

from src.config import BASE_DIR, get_logging_config

LOG_FORMAT = "[%(asctime)s %(levelname)s]: %(message)s"
DATE_FORMAT = "%H:%M:%S"
LOGGER_NAME = "nfcauthsysbackend"


def _minecraft_archive_name(default_name: str) -> str:
    
    source = Path(default_name)
    match = re.search(r"(\d{4}-\d{2}-\d{2})$", source.name)
    date_part = match.group(1) if match else datetime.now().strftime("%Y-%m-%d")
    archive_base = source.parent / f"{date_part}-1.log.gz"
    counter = 1
    while archive_base.exists():
        counter += 1
        archive_base = source.parent / f"{date_part}-{counter}.log.gz"
    return str(archive_base)


def _gzip_rotated_log(source: str, destination: str) -> None:
    """Compress a rotated log and remove its uncompressed temporary file."""
    with open(source, "rb") as source_file, gzip.open(destination, "wb") as gzip_file:
        shutil.copyfileobj(source_file, gzip_file)
    Path(source).unlink(missing_ok=True)


def _resolve_log_path(directory: Path, configured_path: str) -> Path:
    """Resolve a configured log path relative to the log directory by default."""
    path = Path(configured_path).expanduser()
    return path if path.is_absolute() else directory / path


def _build_logger() -> logging.Logger:
    settings: dict[str, Any] = get_logging_config()
    level_name = str(settings.get("level", "INFO")).upper()
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        raise ValueError(f"Invalid logging level in config: {level_name!r}")  # noqa: TRY004

    configured_dir = Path(str(settings.get("directory", "log"))).expanduser()
    logs_dir = configured_dir if configured_dir.is_absolute() else BASE_DIR / configured_dir
    logs_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    app_path = _resolve_log_path(logs_dir, str(settings.get("app_file", "app.log")))
    latest_path = _resolve_log_path(logs_dir, str(settings.get("latest_file", "latest.log")))
    app_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.parent.mkdir(parents=True, exist_ok=True)

    app_handler = TimedRotatingFileHandler(
        app_path,
        when="midnight",
        interval=1,
        backupCount=max(0, int(settings.get("retention_days", 30))),
        encoding="utf-8",
    )
    app_handler.namer = _minecraft_archive_name
    app_handler.rotator = _gzip_rotated_log
    app_handler.setFormatter(formatter)

    # latest.log contains only the current process session.
    latest_handler = logging.FileHandler(latest_path, mode="w", encoding="utf-8")
    latest_handler.setFormatter(formatter)

    app_logger = logging.getLogger(LOGGER_NAME)
    app_logger.setLevel(level)
    app_logger.propagate = False
    app_logger.addHandler(app_handler)
    app_logger.addHandler(latest_handler)

    if bool(settings.get("console", True)):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        app_logger.addHandler(console_handler)

    return app_logger


logger = logging.getLogger(LOGGER_NAME)
if not getattr(logger, "_nfcauthsys_configured", False):
    logger = _build_logger()
    logger._nfcauthsys_configured = True  # type: ignore[attr-defined]


def log_program_start() -> None:
    """Record application startup."""
    logger.info("--- Program started ---")


def log_program_exit() -> None:
    """Record application shutdown and flush pending messages."""
    logger.info("--- Program stopped ---")
    for handler in logger.handlers:
        handler.flush()


def handle_exception(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback: Any,
) -> None:
    """Write uncaught exceptions to the configured logs."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logger.critical(
        "Program crashed (uncaught exception)",
        exc_info=(exc_type, exc_value, exc_traceback),
    )


sys.excepthook = handle_exception
