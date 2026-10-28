import json
import os
import socket
import ssl
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable

from src.config import (
    get_tcp_host,
    get_tcp_port,
    get_tls_cert_path,
    get_tls_key_path,
    is_auth_required,
    is_tls_enabled,
)
from src.database import db
from src.logger import get_logger
from src.security import (
    create_step2_challenge,
    ensure_ssl_certificates,
    generate_server_handshake_response,
    verify_step3_response,
    verify_token,
)
from src.client_logger import client_logger

logger = get_logger("connector")

BUFFER_SIZE = 4096
MAX_BUFFER_ALLOWED = 16384
SOCKET_TIMEOUT_SECONDS = 60.0

last_unknown_card: dict[str, Any] | None = None
attendance_listeners: list[Callable[[dict[str, Any]], None]] = []


def add_attendance_listener(callback: Callable[[dict[str, Any]], None]) -> None:
    attendance_listeners.append(callback)


def get_last_unknown_card() -> dict[str, Any] | None:
    return last_unknown_card


def clear_last_unknown_card() -> None:
    global last_unknown_card
    last_unknown_card = None



class RateLimiter:
    def __init__(self, max_connections_per_minute: int = 60) -> None:
        self.max_connections = max_connections_per_minute
        self._history: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def is_allowed(self, ip: str) -> bool:
        now = time.time()
        window = now - 60.0
        with self._lock:
            timestamps = self._history.get(ip, [])
            timestamps = [t for t in timestamps if t > window]
            if len(timestamps) >= self.max_connections:
                return False
            timestamps.append(now)
            self._history[ip] = timestamps
            return True


class ClientHandler:
    def __init__(self, client: socket.socket, address: tuple[str, int]) -> None:
        self.client = client
        self.address = address
        self.buffer = b""
        self.is_authenticated = not is_auth_required()
        self.device_id: str | None = None
        self.session_token: str | None = None
        self.client_nonce: str | None = None
        self.server_nonce: str | None = None
        self.last_activity = time.time()
        self.last_heartbeat = time.time()
        self.connected_at = time.time()
        self.uptime_s: int | None = None
        self.free_heap: int | None = None
        self.rssi: int | None = None
        self.pending_offline: int = 0

        try:
            self.client.settimeout(SOCKET_TIMEOUT_SECONDS)
        except OSError:
            pass

    def receive_data(self) -> bool:
        try:
            packet = self.client.recv(BUFFER_SIZE)
            if not packet:
                return False

            self.buffer += packet
            self.last_activity = time.time()

            if len(self.buffer) > MAX_BUFFER_ALLOWED:
                logger.warning(
                    f"Client {self.address} exceeded buffer quota ({len(self.buffer)} bytes). Disconnecting."
                )
                return False

            return True
        except socket.timeout:
            logger.info(f"Client {self.address} timed out after {SOCKET_TIMEOUT_SECONDS}s of inactivity")
            return False
        except (socket.error, OSError) as e:
            logger.debug(f"Socket error on {self.address}: {e}")
            return False

    def extract_messages(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []

        while b"\n" in self.buffer:
            line_bytes, self.buffer = self.buffer.split(b"\n", 1)
            line = line_bytes.decode("utf-8", errors="ignore").strip()
            if not line:
                continue

            try:
                data = json.loads(line)
                if isinstance(data, dict):
                    messages.append(data)
                else:
                    messages.append({"raw": data})
            except json.JSONDecodeError:
                if line.startswith("UID:"):
                    messages.append({"uid": line.replace("UID:", "").strip()})
                else:
                    messages.append({"raw_text": line})

        return messages

    def send_json(self, data: dict[str, Any]) -> bool:
        try:
            payload = json.dumps(data, ensure_ascii=False) + "\n"
            self.client.sendall(payload.encode("utf-8"))
            return True
        except (socket.error, OSError) as e:
            logger.warning(f"Error sending to {self.address}: {e}")
            return False

    def send_raw(self, data: bytes) -> bool:
        try:
            self.client.sendall(data)
            return True
        except (socket.error, OSError) as e:
            logger.warning(f"Error sending bytes to {self.address}: {e}")
            return False

    def close(self) -> None:
        try:
            self.client.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.client.close()
        except OSError:
            pass


class TCPConnector:

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        on_message_callback: Callable[[dict[str, Any], ClientHandler], None] | None = None,
    ) -> None:
        self.host = host if host is not None else get_tcp_host()
        self.port = port if port is not None else get_tcp_port()
        self.on_message_callback = on_message_callback or self._default_message_handler
        self.rate_limiter = RateLimiter(max_connections_per_minute=100)
        self._ssl_context: ssl.SSLContext | None = None
        self.connected_clients: dict[str, ClientHandler] = {}
        self._clients_lock = threading.Lock()
        self._device_states: dict[str, str] = {}
        self._device_info: dict[str, dict[str, Any]] = {}
        self._server_socket: socket.socket | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._watchdog_thread: threading.Thread | None = None

    def start(self) -> None:
        """Start listening on TCP socket in background thread."""
        if self._running:
            return

        if is_tls_enabled():
            try:
                cert_path = get_tls_cert_path()
                key_path = get_tls_key_path()
                if ensure_ssl_certificates(cert_path, key_path):
                    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                    ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
                    self._ssl_context = ctx
                    logger.info(f"TLS/SSL socket encryption enabled on TCP Connector with cert: {cert_path}")
                else:
                    logger.warning("Could not generate or verify TLS certificates, continuing with plain TCP.")
            except Exception as e:
                logger.error(f"Failed to initialize TLS/SSL context: {e}. Falling back to plain TCP.")
                self._ssl_context = None

        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            self._server_socket.bind((self.host, self.port))
            self._server_socket.listen(10)
            self._running = True
            logger.info(f"TCP Connector listening on {self.host}:{self.port} (TLS: {self._ssl_context is not None})")

            self._thread = threading.Thread(target=self._listen_loop, daemon=True)
            self._thread.start()

            self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
            self._watchdog_thread.start()
            logger.info("[Device Watchdog] Background heartbeat watchdog started (checking every 5s)")
        except OSError as e:
            logger.error(f"Failed to bind TCP Connector on {self.host}:{self.port} - {e}")
            if self._server_socket:
                self._server_socket.close()
            self._running = False

    def _listen_loop(self) -> None:
        while self._running and self._server_socket:
            try:
                client_sock, client_addr = self._server_socket.accept()
                ip = client_addr[0]

                if not self.rate_limiter.is_allowed(ip):
                    logger.warning(f"Rate limit exceeded for IP {ip}. Dropping connection.")
                    client_sock.close()
                    continue

                if self._ssl_context is not None:
                    try:
                        client_sock = self._ssl_context.wrap_socket(client_sock, server_side=True)
                    except ssl.SSLError as e:
                        logger.warning(f"TLS handshake failed from {client_addr}: {e}")
                        try:
                            client_sock.close()
                        except OSError:
                            pass
                        continue

                client_thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_sock, client_addr),
                    daemon=True,
                )
                client_thread.start()
            except OSError:
                break

    def _handle_client(self, client_sock: socket.socket, client_addr: tuple[str, int]) -> None:
        client_key = f"{client_addr[0]}:{client_addr[1]}"
        handler = ClientHandler(client_sock, client_addr)
        with self._clients_lock:
            self.connected_clients[client_key] = handler
        logger.info(f"TCP client connected from {client_addr}")
        try:
            while self._running:
                if not handler.receive_data():
                    break

                messages = handler.extract_messages()
                for msg in messages:
                    self.on_message_callback(msg, handler)
        finally:
            with self._clients_lock:
                self.connected_clients.pop(client_key, None)
            handler.close()
            logger.info(f"TCP client disconnected from {client_addr}")
            if handler.is_authenticated and handler.device_id:
                self.mark_device_offline(
                    device_id=handler.device_id,
                    handler=handler,
                    reason="Đứt kết nối TCP socket (Nghi vấn bị tắt nguồn / rút dây)"
                )

    def _watchdog_loop(self) -> None:
        while self._running:
            time.sleep(5.0)
            now = time.time()
            stale_handlers: list[tuple[str, ClientHandler, float]] = []
            with self._clients_lock:
                for key, handler in list(self.connected_clients.items()):
                    if handler.is_authenticated and handler.device_id:
                        last_hb = getattr(handler, "last_heartbeat", handler.last_activity)
                        if (now - last_hb) > 25.0:
                            stale_handlers.append((key, handler, now - last_hb))

            for key, handler, idle_time in stale_handlers:
                logger.warning(
                    f"[Device Watchdog] Thiết bị [{handler.device_id}] không có Heartbeat quá {idle_time:.1f}s. Chủ động đóng socket."
                )
                self.mark_device_offline(
                    device_id=handler.device_id,
                    handler=handler,
                    reason=f"Mất tín hiệu Heartbeat quá {int(idle_time)}s (Nghi vấn bị tắt nguồn / rút dây)",
                )
                handler.close()

    def mark_device_online(self, handler: ClientHandler) -> None:
        device_id = handler.device_id or f"ESP32_{handler.address[0]}"
        prev_state = self._device_states.get(device_id)
        self._device_states[device_id] = "ONLINE"
        self._device_info[device_id] = {
            "device_id": device_id,
            "ip": handler.address[0],
            "port": handler.address[1],
            "uptime_s": handler.uptime_s,
            "free_heap": handler.free_heap,
            "rssi": handler.rssi,
            "last_heartbeat": getattr(handler, "last_heartbeat", time.time()),
        }
        if prev_state != "ONLINE":
            logger.info(f"[Device Watchdog] Thiết bị [{device_id}] đã TRỰC TUYẾN (ONLINE)")
            self._notify_device_status({
                "event_type": "DEVICE_STATUS",
                "status": "DEVICE_ONLINE",
                "device_id": device_id,
                "ip": handler.address[0],
                "port": handler.address[1],
                "uptime_s": handler.uptime_s,
                "rssi": handler.rssi,
                "free_heap": handler.free_heap,
                "timestamp": datetime.now().astimezone().isoformat(),
            })

    def mark_device_offline(self, device_id: str, handler: ClientHandler | None = None, reason: str = "") -> None:
        prev_state = self._device_states.get(device_id)
        self._device_states[device_id] = "OFFLINE"
        info = self._device_info.get(device_id, {})
        ip = handler.address[0] if handler else info.get("ip", "N/A")
        port = handler.address[1] if handler else info.get("port", 0)
        uptime_s = handler.uptime_s if handler and handler.uptime_s is not None else info.get("uptime_s")
        last_hb = getattr(handler, "last_heartbeat", None) if handler else info.get("last_heartbeat")

        if prev_state == "ONLINE":
            logger.warning(f"[Device Watchdog] Thiết bị [{device_id}] đã MẤT TÍN HIỆU (OFFLINE): {reason}")
            self._notify_device_status({
                "event_type": "DEVICE_STATUS",
                "status": "DEVICE_OFFLINE",
                "device_id": device_id,
                "ip": ip,
                "port": port,
                "uptime_s": uptime_s,
                "last_heartbeat": last_hb,
                "reason": reason,
                "timestamp": datetime.now().astimezone().isoformat(),
            })

    def _notify_device_status(self, event: dict[str, Any]) -> None:
        for listener in list(attendance_listeners):
            try:
                listener(event)
            except Exception as e:
                logger.warning(f"Error notifying device status listener: {e}")

    def _default_message_handler(self, msg: dict[str, Any], handler: ClientHandler) -> None:
        action = str(msg.get("action", "")).lower()

        if action in ("handshake_step1", "handshake_init"):
            device_id = str(msg.get("device_id", f"ESP32_{handler.address[0]}"))
            client_nonce = str(msg.get("client_nonce") or msg.get("nonce") or "")
            handler.device_id = device_id
            handler.client_nonce = client_nonce

            server_nonce, challenge_resp = create_step2_challenge(
                device_id=device_id,
                client_nonce=client_nonce,
            )
            handler.server_nonce = server_nonce
            logger.info(f"3-Step Handshake: Sent Step 2 challenge to {handler.address} (device: {device_id})")
            handler.send_json(challenge_resp)
            return

        if action in ("handshake_step3", "handshake_verify"):
            device_id = handler.device_id or str(msg.get("device_id", f"ESP32_{handler.address[0]}"))
            client_proof = str(msg.get("client_proof") or "")
            client_nonce = handler.client_nonce or str(msg.get("client_nonce") or "")
            server_nonce = handler.server_nonce or str(msg.get("server_nonce") or "")

            is_valid, session_token = verify_step3_response(
                device_id=device_id,
                client_nonce=client_nonce,
                server_nonce=server_nonce,
                client_proof=client_proof,
            )

            if is_valid and session_token:
                handler.is_authenticated = True
                handler.device_id = device_id
                handler.session_token = session_token
                self.mark_device_online(handler)
                logger.info(f"3-Step Handshake mutual auth verified for [{device_id}] from {handler.address}")
                client_logger.log_event(
                    device_id=device_id,
                    level="INFO",
                    tag="AUTH_3STEP",
                    message="3-Step mutual TLS/HMAC handshake completed successfully",
                    extra={"ip": handler.address[0], "port": handler.address[1]},
                )
                handler.send_json({
                    "action": "handshake_step3_ack",
                    "status": "AUTHENTICATED",
                    "session_token": session_token,
                    "message": "3-Step Handshake xac thuc thanh cong",
                })
            else:
                logger.warning(f"3-Step Handshake failed for {handler.address} (invalid proof)")
                handler.send_json({
                    "action": "handshake_step3_ack",
                    "status": "UNAUTHORIZED",
                    "message": "Xac thuc 3 buoc that bai: client_proof khong hop le",
                })
                handler.close()
            return

        if action == "handshake":
            token = msg.get("auth_token")
            device_id = str(msg.get("device_id", f"ESP32_{handler.address[0]}"))
            client_nonce = str(msg.get("nonce", ""))

            if not verify_token(token):
                logger.warning(f"Handshake failed for {handler.address} (invalid auth_token)")
                handler.send_json({
                    "action": "handshake_ack",
                    "status": "UNAUTHORIZED",
                    "message": "Token xac thuc khong chinh xac",
                })
                handler.close()
                return

            handshake_resp = generate_server_handshake_response(
                device_id=device_id,
                client_nonce=client_nonce,
            )
            handler.is_authenticated = True
            handler.device_id = device_id
            handler.session_token = handshake_resp["session_token"]
            self.mark_device_online(handler)

            logger.info(f"Handshake verified for device [{device_id}] from {handler.address}")
            client_logger.log_event(
                device_id=device_id,
                level="INFO",
                tag="AUTH",
                message="TCP handshake authenticated successfully",
                extra={"ip": handler.address[0], "port": handler.address[1]},
            )
            handler.send_json(handshake_resp)
            return

        if action == "ping":
            device_id = str(msg.get("device_id") or handler.device_id or f"ESP32_{handler.address[0]}")
            handler.device_id = device_id
            handler.uptime_s = msg.get("uptime_s", getattr(handler, "uptime_s", None))
            handler.free_heap = msg.get("free_heap", getattr(handler, "free_heap", None))
            handler.rssi = msg.get("rssi", getattr(handler, "rssi", None))
            handler.pending_offline = msg.get("pending_offline", getattr(handler, "pending_offline", 0))
            handler.last_heartbeat = time.time()
            handler.last_activity = time.time()
            if handler.is_authenticated:
                self.mark_device_online(handler)
            handler.send_json({"action": "pong", "timestamp": int(time.time())})
            return

        if is_auth_required() and not handler.is_authenticated:
            logger.warning(f"Unauthorized packet from {handler.address}")
            handler.send_json({
                "status": "UNAUTHORIZED",
                "message": "Vui long thuc hien handshake voi auth_token truoc khi gui du lieu",
            })
            return

        if action in ("client_log", "log", "client_log_batch", "logs"):
            device_id = handler.device_id or str(msg.get("device_id", f"ESP32_{handler.address[0]}"))
            entries = msg.get("logs") if isinstance(msg.get("logs"), list) else [msg]
            for entry in entries:
                if isinstance(entry, dict):
                    lvl = str(entry.get("level", "INFO"))
                    tag = str(entry.get("tag", "CLIENT"))
                    text = str(entry.get("message") or entry.get("msg") or "")
                    extra = {k: v for k, v in entry.items() if k not in ("action", "device_id", "level", "tag", "message", "msg")}
                    client_logger.log_event(device_id=device_id, level=lvl, tag=tag, message=text, extra=extra)
            handler.send_json({"action": "log_ack", "status": "ok", "count": len(entries)})
            return

        if action in ("config_ack", "reboot_ack", "config_info"):
            device_id = handler.device_id or str(msg.get("device_id", f"ESP32_{handler.address[0]}"))
            logger.info(f"Received {action} from [{device_id}]: {msg}")
            payload = {
                "action": action,
                "device_id": device_id,
                "ip": handler.address[0],
                "data": msg,
                "timestamp": datetime.now().astimezone().isoformat(),
            }
            for listener in list(attendance_listeners):
                try:
                    listener(payload)
                except Exception as e:
                    logger.warning(f"Error notifying listener about {action}: {e}")
            return

        if action in ("offline_scan", "offline_sync"):
            uid = msg.get("uid")
            if uid:
                device_id = handler.device_id or str(msg.get("device_id", f"TCP_{handler.address[0]}"))
                elapsed_ms = msg.get("elapsed_ms")
                if elapsed_ms is not None and isinstance(elapsed_ms, (int, float)) and elapsed_ms >= 0:
                    swipe_time = datetime.now() - timedelta(milliseconds=float(elapsed_ms))
                    scan_timestamp = swipe_time.astimezone().isoformat()
                    seconds_ago = int(elapsed_ms / 1000)
                    if seconds_ago < 60:
                        time_desc = f"{seconds_ago}s truoc"
                    else:
                        mins_ago = seconds_ago // 60
                        time_desc = f"{mins_ago} phut truoc"
                    notes = f"Diem danh offline (Quet luc {swipe_time.strftime('%H:%M:%S')}, {time_desc})"
                else:
                    swipe_time = datetime.now()
                    scan_timestamp = swipe_time.astimezone().isoformat()
                    notes = "Diem danh offline (tu dong dong bo sau khi co mang)"

                result = db.record_attendance(
                    uid=str(uid),
                    device_id=device_id,
                    notes=notes,
                    timestamp=scan_timestamp,
                )
                logger.info(
                    f"[Offline Sync] Dong bo UID [{uid}] ({notes}): {result['status']} - {result['message']}"
                )

                response = {
                    "action": "offline_sync_ack",
                    "status": result["status"],
                    "uid": result["uid"],
                    "message": result["message"],
                    "student": result.get("student"),
                    "timestamp": result["timestamp"],
                    "device_id": device_id,
                    "is_offline": True,
                    "notes": notes,
                }

                for listener in list(attendance_listeners):
                    try:
                        listener(response)
                    except Exception as e:
                        logger.warning(f"Error notifying attendance listener: {e}")

                handler.send_json({
                    "action": "offline_ack",
                    "status": result["status"],
                    "uid": str(uid),
                })
                return

        uid = msg.get("uid")
        if uid:
            device_id = handler.device_id or str(msg.get("device_id", f"TCP_{handler.address[0]}"))
            result = db.record_attendance(uid=str(uid), device_id=device_id)

            global last_unknown_card
            if result.get("status") == "UNKNOWN_CARD":
                last_unknown_card = {
                    "uid": str(result["uid"]),
                    "device_id": device_id,
                    "timestamp": result.get("timestamp") or time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                logger.info(f"Cached last unknown card [{result['uid']}] for Discord bot fast registration")

            log_level = "INFO" if result["status"] == "SUCCESS" else "WARNING"
            client_logger.log_event(
                device_id=device_id,
                level=log_level,
                tag="NFC_SCAN",
                message=f"Quet the UID [{result['uid']}] - {result['message']}",
                extra={"status": result["status"]},
            )

            response = {
                "action": "scan_ack",
                "status": result["status"],
                "uid": result["uid"],
                "message": result["message"],
                "student": result.get("student"),
                "timestamp": result["timestamp"],
                "device_id": device_id,
            }

            for listener in list(attendance_listeners):
                try:
                    listener(response)
                except Exception as e:
                    logger.warning(f"Error notifying attendance listener: {e}")

            handler.send_json(response)
            return

        handler.send_json({"status": "received", "data": msg})

    def get_connected_clients(self) -> list[dict[str, Any]]:
        with self._clients_lock:
            clients = []
            for key, h in self.connected_clients.items():
                clients.append({
                    "key": key,
                    "ip": h.address[0],
                    "port": h.address[1],
                    "device_id": h.device_id or f"ESP32_{h.address[0]}",
                    "authenticated": h.is_authenticated,
                    "session_token": h.session_token,
                    "connected_at": getattr(h, "connected_at", h.last_activity),
                    "last_activity": h.last_activity,
                    "last_heartbeat": getattr(h, "last_heartbeat", h.last_activity),
                    "uptime_s": getattr(h, "uptime_s", None),
                    "free_heap": getattr(h, "free_heap", None),
                    "rssi": getattr(h, "rssi", None),
                    "pending_offline": getattr(h, "pending_offline", 0),
                })
            return clients

    def send_command_to_device(self, device_id: str, command: dict[str, Any]) -> dict[str, Any]:
        with self._clients_lock:
            if not self.connected_clients:
                return {
                    "success": False,
                    "message": "Hiện không có đầu đọc ESP32 nào đang kết nối trực tuyến tới máy chủ."
                }

            target = str(device_id).strip()
            if target.lower() == "all":
                sent_count = 0
                for h in self.connected_clients.values():
                    if h.send_json(command):
                        sent_count += 1
                return {
                    "success": sent_count > 0,
                    "target": "all",
                    "sent_count": sent_count,
                    "total_clients": len(self.connected_clients),
                    "message": f"Đã gửi lệnh thành công tới {sent_count}/{len(self.connected_clients)} đầu đọc trực tuyến."
                }

            for h in self.connected_clients.values():
                h_id = h.device_id or f"ESP32_{h.address[0]}"
                if (
                    h_id.lower() == target.lower()
                    or h.address[0] == target
                    or (h.device_id and h.device_id.lower() == target.lower())
                ):
                    ok = h.send_json(command)
                    return {
                        "success": ok,
                        "device_id": h_id,
                        "ip": h.address[0],
                        "message": "Đã gửi lệnh xuống đầu đọc thành công." if ok else "Lỗi truyền dữ liệu qua TCP socket tới đầu đọc."
                    }

            return {
                "success": False,
                "message": f"Không tìm thấy đầu đọc '{target}' trong danh sách thiết bị đang kết nối trực tuyến."
            }

    def discover_and_connect_esp32(self) -> dict[str, Any]:
        from src.mdns_broadcaster import get_local_ip, start_mdns_broadcaster

        local_ip = get_local_ip()
        start_mdns_broadcaster()

        arp_entries = []
        if os.path.exists("/proc/net/arp"):
            try:
                with open("/proc/net/arp", "r") as f:
                    for line in f.readlines()[1:]:
                        parts = line.split()
                        if len(parts) >= 4 and parts[3] != "00:00:00:00:00:00":
                            arp_entries.append({"ip": parts[0], "mac": parts[3]})
            except Exception as e:
                logger.warning(f"Error inspecting ARP table: {e}")

        espressif_ouis = (
            "20:e7:c8", "24:6f:28", "30:ae:a4", "84:f7:03", "a0:b7:65",
            "cc:50:e3", "3c:61:05", "3c:e9:0e", "48:27:e2", "40:22:d8",
            "54:43:b2", "d8:bc:38"
        )

        discovered = []
        for entry in arp_entries:
            mac = entry["mac"].lower()
            is_espressif = any(mac.startswith(oui) for oui in espressif_ouis)
            can_reach_http = False
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.3)
                    can_reach_http = (s.connect_ex((entry["ip"], 80)) == 0)
            except Exception:
                pass

            if is_espressif or can_reach_http:
                discovered.append({
                    "ip": entry["ip"],
                    "mac": entry["mac"],
                    "is_espressif": is_espressif,
                    "http_portal_active": can_reach_http,
                    "device_id": f"ESP32_{entry['ip'].replace('.', '_')}",
                })

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_sock:
                udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                beacon = json.dumps({
                    "action": "backend_discovery",
                    "host": local_ip,
                    "tcp_port": self.port,
                    "timestamp": int(time.time()),
                }).encode("utf-8")
                udp_sock.sendto(beacon, ("255.255.255.255", 1337))
        except Exception as e:
            logger.debug(f"UDP beacon broadcast error: {e}")

        connected = self.get_connected_clients()
        return {
            "status": "SUCCESS",
            "backend_ip": local_ip,
            "tcp_port": self.port,
            "connected_devices": connected,
            "discovered_lan_devices": discovered,
            "arp_scan_count": len(arp_entries),
        }

    def stop(self) -> None:
        self._running = False
        if self._server_socket:
            try:
                self._server_socket.close()
            except OSError:
                pass
        logger.info("TCP Connector stopped")


tcp_connector = TCPConnector()
