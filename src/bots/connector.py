from typing import Any, Callable
from src.connector import get_last_unknown_card, add_attendance_listener


def get_pending_card() -> dict[str, Any] | None:
    return get_last_unknown_card()


def register_attendance_hook(callback: Callable[[dict[str, Any]], None]) -> None:
    add_attendance_listener(callback)


def trigger_esp32_discovery() -> dict[str, Any]:
    from src.connector import tcp_connector
    return tcp_connector.discover_and_connect_esp32()


def get_active_esp32_readers() -> list[dict[str, Any]]:
    from src.connector import tcp_connector
    return tcp_connector.get_connected_clients()
