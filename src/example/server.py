import socket
import random
import os
import time

# Xóa màn hình cho gọn
os.system("cls")
print("//~~ Server Side (Running) ~~//")

# Cấu hình IP và Port (Dùng 0.0.0.0 để máy khác trong mạng LAN có thể kết nối vào, hoặc 127.0.0.1 nếu chạy cùng 1 máy)
host, port = ("192.168.1.212", 1337)

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind((host, port))
sock.listen(5)  # Cho phép hàng đợi tối đa 5 kết nối chờ

print(f"Server đang lắng nghe tại {host}:{port}...\n")

try:
    while True:
        # Chờ client kết nối (hàm này sẽ dừng lại cho đến khi có client gọi vào)
        client, client_addr = sock.accept()
        print(f"\n[+] Đã kết nối từ client: {client_addr}")

        try:
            # --- DELAY 1: Giả lập thời gian server chờ đọc dữ liệu SYN ---
            time.sleep(0.5)

            syn = client.recv(1024).decode()
            if not syn:
                client.close()
                continue
            print("  |-- Nhận từ client:", syn)

            # Xử lý chuỗi seq từ client gửi lên để tạo phản hồi
            m_val = int(syn.split("seq=")[1].split(" ")[0]) + 1
            n_val = random.randint(1000, 2000)

            response = f"[2] SYN/seq={n_val} ACK/seq={m_val}"

            # --- DELAY 2: Giả lập độ trễ trước khi phản hồi ---
            time.sleep(0.5)

            client.sendall(response.encode())
            print(f"  |-- Đã gửi phản hồi: {response}")

            # --- DELAY 3: Chờ nhận ACK cuối cùng từ client ---
            time.sleep(0.5)

            ack = client.recv(1024).decode()
            print("  |-- Nhận ACK từ client:", ack)
            print("[✓] Hoàn tất bắt tay với client thành công!")

        except Exception as e:
            print(f"[!] Lỗi trong quá trình giao tiếp với client: {e}")
        finally:
            # Đóng kết nối riêng với client này để giải phóng
            client.close()
            print("--- Đã đóng kết nối với client hiện tại, sẵn sàng nhận client mới ---")

except KeyboardInterrupt:
    print("\n[!] Server đã được dừng thủ công bởi người dùng.")
finally:
    sock.close()