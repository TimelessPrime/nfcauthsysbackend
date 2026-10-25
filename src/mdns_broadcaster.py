import socket
import threading
from typing import Any

from src.config import get_server_port, get_tcp_port
from src.logger import setup_logger

logger = setup_logger("mdns")

_zeroconf_instance: Any = None
_service_info: Any = None


def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def start_mdns_broadcaster() -> bool:
    global _zeroconf_instance, _service_info  # noqa: PLW0603

    try:
        from zeroconf import IPVersion, ServiceInfo, Zeroconf
    except ImportError:
        logger.warning("Package 'zeroconf' not installed. mDNS auto-discovery will be disabled.")
        return False

    try:
        local_ip = get_local_ip()
        tcp_port = get_tcp_port()
        http_port = get_server_port()

        logger.info(f"Starting mDNS broadcast on {local_ip} (Host: nfc-server.local)")

        desc = {
            "tcp_port": str(tcp_port),
            "http_port": str(http_port),
            "service": "nfc_school_auth",
            "version": "1.2.0",
        }

        _zeroconf_instance = Zeroconf(ip_version=IPVersion.V4Only)

        _service_info = ServiceInfo(
            type_="_nfcauth._tcp.local.",
            name="NFC School Auth Backend._nfcauth._tcp.local.",
            addresses=[socket.inet_aton(local_ip)],
            port=tcp_port,
            properties=desc,
            server="nfc-server.local.",
        )

        _zeroconf_instance.register_service(_service_info)
        logger.info(f"mDNS service registered: nfc-server.local -> {local_ip}:{tcp_port}")
        return True
    except Exception as e:
        logger.warning(f"Could not initialize mDNS service: {e}")
        return False


def stop_mdns_broadcaster() -> None:
    global _zeroconf_instance, _service_info  # noqa: PLW0603

    try:
        if _zeroconf_instance and _service_info:
            logger.info("Unregistering mDNS service...")
            _zeroconf_instance.unregister_service(_service_info)
            _zeroconf_instance.close()
            _zeroconf_instance = None
            _service_info = None
    except Exception as e:
        logger.warning(f"Error stopping mDNS: {e}")
