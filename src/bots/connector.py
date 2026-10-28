from typing import Any, Callable
from src.connector import get_last_unknown_card, add_attendance_listener


def get_pending_card() -> dict[str, Any] | None:
    return get_last_unknown_card()


def clear_pending_card() -> None:
    from src.connector import clear_last_unknown_card
    clear_last_unknown_card()



def register_attendance_hook(callback: Callable[[dict[str, Any]], None]) -> None:
    add_attendance_listener(callback)


def trigger_esp32_discovery() -> dict[str, Any]:
    from src.connector import tcp_connector
    return tcp_connector.discover_and_connect_esp32()


def get_active_esp32_readers() -> list[dict[str, Any]]:
    from src.connector import tcp_connector
    return tcp_connector.get_connected_clients()


def send_config_update(device_id: str, config_data: dict[str, Any]) -> dict[str, Any]:
    from src.connector import tcp_connector
    cmd = {"action": "update_config", "device_id": device_id}
    cmd.update(config_data)
    return tcp_connector.send_command_to_device(device_id, cmd)


def send_reader_reboot(device_id: str) -> dict[str, Any]:
    from src.connector import tcp_connector
    cmd = {"action": "reboot", "device_id": device_id}
    return tcp_connector.send_command_to_device(device_id, cmd)

