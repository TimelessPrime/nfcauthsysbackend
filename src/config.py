"""Đọc và kiểm tra cấu hình của ứng dụng."""

import json
from pathlib import Path
from typing import Any


# Xác định đường dẫn dựa trên vị trí file này, không phụ thuộc thư mục chạy lệnh.
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "config.json"


def load_config() -> dict[str, Any]:
    """Đọc file JSON, kiểm tra dữ liệu rồi trả về cấu hình."""
    try:
        # Dùng UTF-8 để đọc file JSON ổn định trên các hệ điều hành.
        with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
            config = json.load(config_file)
    except FileNotFoundError as exc:
        # Báo rõ đường dẫn nếu file cấu hình không tồn tại.
        raise FileNotFoundError(f"Configuration file not found: {CONFIG_PATH}") from exc
    except json.JSONDecodeError as exc:
        # Báo lỗi khi JSON sai cú pháp, chẳng hạn thiếu dấu phẩy hoặc ngoặc.
        raise ValueError(f"Invalid JSON in configuration file: {CONFIG_PATH}") from exc

    # Cấu hình gốc phải là một object JSON, tương ứng với dict trong Python.
    if not isinstance(config, dict):
        raise ValueError("Configuration root must be a JSON object.")

    # Giá trị mặc định được dùng nếu khóa chưa có trong file.
    debug = config.get("debug", False)
    port = config.get("port", 5000)

    # debug chỉ nhận true hoặc false, không nhận chuỗi "True"/"False".
    if not isinstance(debug, bool):
        raise ValueError("'debug' must be a Boolean (true or false).")

    # Cổng mạng phải là số nguyên trong khoảng hợp lệ 1–65535.
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("'port' must be an integer between 1 and 65535.")

    # Chuẩn hóa các khóa đã kiểm tra trước khi trả cấu hình về.
    config["debug"] = debug
    config["port"] = port
    return config


# Đọc cấu hình một lần khi module được import lần đầu.
data = load_config()


def get_port() -> int:
    """Trả về cổng mà máy chủ sẽ sử dụng."""
    return data["port"]


def get_debug() -> bool:
    """Trả về trạng thái bật/tắt chế độ debug."""
    return data["debug"]


async def get_port_dt() -> int:
    """Hàm tương thích cho nơi gọi cũ đang dùng await; có thể bỏ nếu không cần."""
    return get_port()
