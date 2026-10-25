import asyncio
import logging
import threading
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from src.config import BASE_DIR
from src.logger import tail_log

CLIENT_LOG_DIR: Path = BASE_DIR / "client_log"
MAX_LOG_SIZE_BYTES = 10 * 1024 * 1024
BACKUP_COUNT = 5


class ClientLoggerManager:

    def __init__(self, log_dir: Path = CLIENT_LOG_DIR) -> None:
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._device_handlers: dict[str, RotatingFileHandler] = {}
        self._all_handler: RotatingFileHandler | None = None
        self._subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._lock = threading.Lock()
        self._max_handlers = 50
        self._init_global_handler()

    def _init_global_handler(self) -> None:
        all_log_path = self.log_dir / "all_clients.log"
        self._all_handler = RotatingFileHandler(
            all_log_path,
            maxBytes=MAX_LOG_SIZE_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        formatter = logging.Formatter(
            fmt="[%(asctime)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self._all_handler.setFormatter(formatter)

    def _get_device_handler(self, device_id: str) -> RotatingFileHandler:
        clean_id = "".join(c for c in device_id if c.isalnum() or c in ("-", "_")).strip()
        if not clean_id:
            clean_id = "unknown_device"

        with self._lock:
            if clean_id in self._device_handlers:
                return self._device_handlers[clean_id]

            if len(self._device_handlers) >= self._max_handlers:
                oldest_id, oldest_handler = next(iter(self._device_handlers.items()))
                try:
                    oldest_handler.flush()
                    oldest_handler.close()
                except Exception:
                    pass
                del self._device_handlers[oldest_id]

            dev_log_path = self.log_dir / f"{clean_id}.log"
            handler = RotatingFileHandler(
                dev_log_path,
                maxBytes=MAX_LOG_SIZE_BYTES,
                backupCount=BACKUP_COUNT,
                encoding="utf-8",
            )
            formatter = logging.Formatter(
                fmt="[%(asctime)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            handler.setFormatter(formatter)
            self._device_handlers[clean_id] = handler
            return handler

    def log_event(
        self,
        device_id: str,
        level: str,
        tag: str,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now().astimezone()
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        clean_level = level.upper()
        clean_tag = tag.upper()
        clean_device = device_id.strip() or "ESP32_UNKNOWN"

        extra_info = ""
        if extra:
            extra_parts = [f"{k}={v}" for k, v in extra.items() if v is not None]
            if extra_parts:
                extra_info = f" ({', '.join(extra_parts)})"

        formatted_line = f"[{clean_device}] [{clean_level}] [{clean_tag}]: {message}{extra_info}"

        dev_handler = self._get_device_handler(clean_device)
        record = logging.LogRecord(
            name=f"client.{clean_device}",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=formatted_line,
            args=(),
            exc_info=None,
        )
        record.asctime = timestamp_str

        with self._lock:
            dev_handler.emit(record)
            if self._all_handler:
                self._all_handler.emit(record)

        event_payload = {
            "timestamp": timestamp_str,
            "device_id": clean_device,
            "level": clean_level,
            "tag": clean_tag,
            "message": message,
            "extra": extra or {},
            "raw": formatted_line,
        }

        self._broadcast(event_payload)
        return event_payload

    def _broadcast(self, payload: dict[str, Any]) -> None:
        with self._lock:
            subs = list(self._subscribers)

        for loop, q in subs:
            try:
                if loop.is_running():
                    loop.call_soon_threadsafe(q.put_nowait, payload)
                else:
                    q.put_nowait(payload)
            except asyncio.QueueFull:
                pass
            except Exception:
                pass

    def add_subscriber(self, q: asyncio.Queue, loop: asyncio.AbstractEventLoop | None = None) -> None:
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.get_event_loop()

        with self._lock:
            for existing_loop, existing_q in self._subscribers:
                if existing_q is q:
                    return
            self._subscribers.append((loop, q))

    def remove_subscriber(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers = [
                (loop, existing_q) for (loop, existing_q) in self._subscribers if existing_q is not q
            ]

    def get_device_logs(self, device_id: str | None = None, lines: int = 100) -> list[str]:
        if device_id:
            clean_id = "".join(c for c in device_id if c.isalnum() or c in ("-", "_")).strip()
            path = self.log_dir / f"{clean_id}.log"
        else:
            path = self.log_dir / "all_clients.log"

        return tail_log(filepath=path, lines=lines)

    def list_client_devices(self) -> list[str]:
        devices = []
        for p in self.log_dir.glob("*.log"):
            if p.name != "all_clients.log":
                devices.append(p.stem)
        return sorted(devices)

    def close(self) -> None:
        with self._lock:
            if self._all_handler:
                try:
                    self._all_handler.flush()
                    self._all_handler.close()
                except Exception:
                    pass
                self._all_handler = None

            for h in self._device_handlers.values():
                try:
                    h.flush()
                    h.close()
                except Exception:
                    pass
            self._device_handlers.clear()
            self._subscribers.clear()


client_logger = ClientLoggerManager()
