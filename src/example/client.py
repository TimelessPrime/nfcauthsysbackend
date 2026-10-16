import socket
import random
import os
import time  # 1. Import thư viện time để làm delay

os.system("cls")
print("//~~ Client Side ~~//")

host, port = ("192.168.1.212", 1337)

# Nếu bạn muốn chạy liên tục dạng vòng lặp, hãy thêm thời gian nghỉ (delay) 
# để server và client kịp xử lý từng vòng, tránh bị dồn dập lỗi kết nối.
while True:
    try:
        # Tạo socket mới cho mỗi lần kết nối
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        print(f"\nĐang kết nối tới server {host}:{port}...")
        sock.connect((host, port))

        # --- DELAY 1: Chờ 1 chút trước khi gửi gói SYN đầu tiên ---
        time.sleep(1.0)

        # Tạo số ngẫu nhiên cho seq và gửi gói [1] SYN
        m = str(random.randint(1000, 2000)) 
        sock.sendall(b"[1] SYN/seq=" + m.encode())
        print(f"Đã gửi: [1] SYN/seq={m}")

        # Nhận gói phản hồi SYN-ACK từ Server
        synack = sock.recv(1024).decode()
        print("Nhận từ Server:", synack)

        # Xử lý chuỗi để lấy số seq trả về từ server, cộng thêm 1 làm ACK
        n = synack.split("seq=")[1].split(" ")[0] 
        n = str(int(n) + 1) 

        # --- DELAY 2: Giả lập thời gian suy nghĩ/xử lý của client trước khi gửi ACK ---
        time.sleep(0.5)

        # Gửi gói [3] ACK cuối cùng
        sock.sendall(b"[3] ACK/seq=" + n.encode())
        print(f"Đã gửi: [3] ACK/seq={n}")

        # Đóng socket của phiên làm việc hiện tại
        sock.close()
        print("Hoàn tất chu kỳ bắt tay. Đang chờ chu kỳ tiếp theo...")

        # --- DELAY 3: Nghỉ 3 giây trước khi thực hiện lần kết nối tiếp theo trong vòng lặp ---
        time.sleep(3)

    except ConnectionRefusedError:
        print("Không thể kết nối đến server! Server có thể chưa bật. Thử lại sau 2 giây...")
        time.sleep(2)
    except KeyboardInterrupt:
        print("\nĐã dừng client thủ công bởi người dùng.")
        break