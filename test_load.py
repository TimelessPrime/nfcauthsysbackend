import argparse
import json
import socket
import sys
import threading
import time
from typing import Any

TEST_STUDENTS = [
    {"uid": "69BDD1E6", "student_id": "HS001", "full_name": "Nguyễn Hoàng Long", "class_name": "12A1"},
    {"uid": "C39C485E", "student_id": "HS002", "full_name": "Trần Minh Thư", "class_name": "12A1"},
    {"uid": "E2801103", "student_id": "HS003", "full_name": "Lê Tuấn Kiệt", "class_name": "12A2"},
    {"uid": "E2801104", "student_id": "HS004", "full_name": "Phạm Quỳnh Anh", "class_name": "12A2"},
    {"uid": "E2801105", "student_id": "HS005", "full_name": "Vũ Hoàng Nam", "class_name": "12A3"},
]

DEVICES = ["ESP32_CONG_CHINH", "ESP32_CONG_PHU"]


def prepare_database_students():
    try:
        from src.database import db
        print("[SETUP] Kiểm tra và đăng ký 5 học sinh mẫu vào CSDL...")
        for s in TEST_STUDENTS:
            existing = db.get_student(s["uid"])
            if not existing:
                db.add_student(s["uid"], s["student_id"], s["full_name"], s["class_name"])
                print(f"  + Đã thêm: [{s['uid']}] {s['student_id']} - {s['full_name']} ({s['class_name']})")
            else:
                print(f"  ✓ Đã có: [{s['uid']}] {existing['student_id']} - {existing['full_name']}")
    except Exception as e:
        print(f"[WARN] Không thể chuẩn bị DB trực tiếp: {e}")


class SimulatedESP32TCP:
    def __init__(self, device_id: str, host: str = "127.0.0.1", port: int = 1337, auth_token: str = "systemauth"):
        self.device_id = device_id
        self.host = host
        self.port = port
        self.auth_token = auth_token
        self.sock: socket.socket | None = None
        self.lock = threading.Lock()

    def connect(self) -> bool:
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5.0)
            self.sock.connect((self.host, self.port))

            handshake_msg = json.dumps({
                "action": "handshake",
                "device_id": self.device_id,
                "auth_token": self.auth_token,
                "nonce": f"sim_{int(time.time()*1000)}"
            }) + "\n"
            self.sock.sendall(handshake_msg.encode("utf-8"))

            resp_raw = self.sock.recv(4096).decode("utf-8")
            if "AUTHENTICATED" in resp_raw:
                return True
            print(f"[{self.device_id}] Handshake failed: {resp_raw.strip()}")
            return False
        except Exception as e:
            print(f"[{self.device_id}] Lỗi kết nối TCP: {e}")
            return False

    def scan_card(self, uid: str) -> tuple[bool, float, dict[str, Any]]:
        t_start = time.perf_counter()
        with self.lock:
            try:
                if not self.sock:
                    return False, 0.0, {"error": "Socket not connected"}

                msg = json.dumps({
                    "action": "scan",
                    "uid": uid,
                    "device_id": self.device_id
                }) + "\n"
                self.sock.sendall(msg.encode("utf-8"))

                data = b""
                while not data.endswith(b"\n"):
                    chunk = self.sock.recv(1024)
                    if not chunk:
                        break
                    data += chunk

                latency_ms = (time.perf_counter() - t_start) * 1000.0
                resp_json = json.loads(data.decode("utf-8").strip())
                is_success = resp_json.get("status") == "SUCCESS"
                return is_success, latency_ms, resp_json
            except Exception as e:
                latency_ms = (time.perf_counter() - t_start) * 1000.0
                return False, latency_ms, {"error": str(e)}

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass


def run_benchmark(duration_sec: int = 6, target_rps: float = 5.0):
    print("=" * 70)
    print("   BENCHMARK ĐIỂM DANH: 5 HỌC SINH / GIÂY TRÊN 2 THIẾT BỊ ESP32")
    print("=" * 70)
    print(f"  • Số lượng thiết bị giả lập: 2 ({DEVICES[0]}, {DEVICES[1]})")
    print(f"  • Mục tiêu tải:              {target_rps:.1f} học sinh / giây")
    print(f"  • Thời gian chạy thử:        {duration_sec} giây")
    print(f"  • Tổng số lượt quét dự kiến: {int(target_rps * duration_sec)}")
    print(f"  • Giao thức:                 TCP Socket Port 1337 (Chuẩn phần cứng ESP32)")
    print("-" * 70)

    prepare_database_students()
    print("-" * 70)

    devices = [SimulatedESP32TCP(dev_id) for dev_id in DEVICES]
    for d in devices:
        print(f"[CONNECT] Đang kết nối và bắt tay thiết bị: {d.device_id}...")
        if not d.connect():
            print(f"[ERROR] Không thể kết nối thiết bị {d.device_id} tới TCP server!")
            return
        print(f"  ✓ Thiết bị {d.device_id} đã xác thực thành công.")

    print("\n[START] Bắt đầu phát luồng quẹt thẻ...")
    start_time = time.time()
    results = []
    interval = 1.0 / target_rps
    card_index = 0
    dev_index = 0

    end_time = start_time + duration_sec
    req_count = 0

    while time.time() < end_time:
        t_loop_start = time.perf_counter()

        current_dev = devices[dev_index % len(devices)]
        current_student = TEST_STUDENTS[card_index % len(TEST_STUDENTS)]

        success, latency, resp = current_dev.scan_card(current_student["uid"])
        status_label = "SUCCESS" if success else "FAIL"
        student_name = current_student["full_name"]
        uid = current_student["uid"]

        req_count += 1
        results.append({
            "device": current_dev.device_id,
            "uid": uid,
            "name": student_name,
            "success": success,
            "latency": latency,
            "timestamp": time.time(),
        })

        color_dot = "🟢" if success else "🔴"
        print(f"  {color_dot} [{req_count:03d}] {current_dev.device_id} -> UID: {uid} ({student_name:18}) | {latency:6.2f} ms | [{status_label}]")

        card_index += 1
        dev_index += 1

        elapsed = time.perf_counter() - t_loop_start
        sleep_time = interval - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)

    total_time = time.time() - start_time
    for d in devices:
        d.close()

    total_reqs = len(results)
    success_reqs = sum(1 for r in results if r["success"])
    latencies = [r["latency"] for r in results]
    latencies.sort()

    avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
    min_lat = latencies[0] if latencies else 0.0
    max_lat = latencies[-1] if latencies else 0.0
    p50_lat = latencies[int(len(latencies) * 0.50)] if latencies else 0.0
    p95_lat = latencies[int(len(latencies) * 0.95)] if latencies else 0.0
    actual_rps = total_reqs / total_time if total_time > 0 else 0.0

    print("\n" + "=" * 70)
    print("                     KẾT QUẢ KIỂM THỬ TẢI")
    print("=" * 70)
    print(f"  Tổng số yêu cầu gửi:      {total_reqs}")
    print(f"  Thành công (SUCCESS):     {success_reqs} / {total_reqs} ({success_reqs/total_reqs*100:.1f}%)")
    print(f"  Thời gian thực thi:       {total_time:.2f} giây")
    print(f"  Tốc độ thực tế:           {actual_rps:.2f} req/giây")
    print("-" * 70)
    print("  ĐỘ TRỄ PHẢN HỒI (LATENCY):")
    print(f"  • Thấp nhất (Min):        {min_lat:.2f} ms")
    print(f"  • Trung bình (Avg):       {avg_lat:.2f} ms")
    print(f"  • Phân vị 50 (P50):       {p50_lat:.2f} ms")
    print(f"  • Phân vị 95 (P95):       {p95_lat:.2f} ms")
    print(f"  • Cao nhất (Max):         {max_lat:.2f} ms")
    print("-" * 70)
    print("  PHÂN BỔ THEO THIẾT BỊ:")
    for dev_id in DEVICES:
        dev_results = [r for r in results if r["device"] == dev_id]
        d_succ = sum(1 for r in dev_results if r["success"])
        d_avg = sum(r["latency"] for r in dev_results) / len(dev_results) if dev_results else 0.0
        print(f"  • {dev_id:20}: {len(dev_results):2d} lượt quét | {d_succ:2d} thành công | Trễ TB: {d_avg:5.2f} ms")
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=6, help="Thời gian test tính bằng giây")
    parser.add_argument("--rps", type=float, default=5.0, help="Số yêu cầu / giây")
    args = parser.parse_args()

    run_benchmark(duration_sec=args.duration, target_rps=args.rps)
