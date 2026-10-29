# NFC School Auth Backend & Discord Bot

Hệ thống máy chủ trung tâm quản trị, xác thực và điểm danh học sinh qua thẻ NFC/RFID, kết nối thời gian thực với các thiết bị đầu đọc ESP32 và tích hợp Discord Bot điều khiển từ xa.

---

## Tính năng chính

- **Giao thức TCP Socket hai chiều:**
  - Kết nối liên tục giữa đầu đọc ESP32 và máy chủ với độ trễ phản hồi < 50ms.
  - Bắt tay xác thực 3 bước (`handshake`) sử dụng mã hóa chữ ký số HMAC-SHA256 chống giả mạo danh tính thiết bị và tấn công phát lại (Replay attack).
- **Đồng bộ ngoại tuyến (Offline Buffer Sync):**
  - Tự động nhận diện và đồng bộ các lượt quẹt thẻ được lưu tạm trong bộ nhớ flash của ESP32 khi mất kết nối mạng.
- **Hệ thống CSDL kép dự phòng (Fail-Safe Dual Database):**
  - Sử dụng MySQL làm cơ sở dữ liệu chính.
  - Tự động chuyển sang SQLite cục bộ nếu MySQL gặp sự cố kết nối, giúp việc điểm danh không bị gián đoạn.
  - Tự động phục hồi về MySQL khi dịch vụ hoạt động trở lại.
- **Cấu hình động và khởi động lại từ xa (Remote Dynamic Config):**
  - Điều chỉnh thời gian giãn cách quẹt thẻ (`cooldown_ms`), thời lượng còi bíp, vị trí đặt đầu đọc hoặc thông tin Wi-Fi từ xa qua Discord bot hoặc API mà không cần nạp lại firmware.
  - ESP32 tự động lưu cấu hình vào bộ nhớ NVS.
- **Giám sát thiết bị thời gian thực (Device Watchdog):**
  - Theo dõi nhịp tim (`heartbeat`) định kỳ của từng đầu đọc ESP32.
  - Tự động phát hiện và gửi cảnh báo mất nguồn hoặc ngắt mạng lên Discord sau 15 giây không có tín hiệu.
- **Discord Bot quản trị đa kênh:**
  - Phân luồng thông tin về 4 kênh riêng biệt: trạng thái thiết bị (`status`), thông báo điểm danh (`noti`), đăng ký thẻ mới (`reg`), tra cứu thông tin (`info`).
  - Hỗ trợ song song cả 13 Slash Commands (`/`) và Prefix Commands (`!`).
  - Bảng điều khiển giao diện nút bấm (`/panel`) và form nhập liệu trực quan (Modal).
  - Tự động cập nhật bảng trạng thái đầu đọc định kỳ (Live Dashboard).

---

## Cấu trúc thư mục

```text
backend/
├── config/                     # Thư mục chứa cấu hình hoạt động
│   ├── config.json             # Cấu hình máy chủ TCP, HTTP API, MySQL & Fail-safe
│   └── bot_config.json         # Cấu hình Discord Bot và kênh thông báo
├── data/                       # CSDL SQLite dự phòng (attendance.db)
├── log/                        # Nhật ký hoạt động backend
├── client_log/                 # Nhật ký từ các đầu đọc ESP32 gửi về
├── src/                        # Mã nguồn ứng dụng
│   ├── bots/                   # Module Discord Bot
│   │   ├── commands/           # Các nhóm lệnh bot
│   │   │   ├── student.py      # Lệnh quản lý học sinh và thẻ
│   │   │   ├── device.py       # Lệnh cấu hình và khởi động lại đầu đọc
│   │   │   └── system.py       # Lệnh cấu hình kênh và bảng điều khiển
│   │   ├── bot.py              # Khởi tạo bot instance và hàng đợi
│   │   ├── config.py           # Quản lý cấu hình bot và kênh
│   │   ├── connector.py        # Cầu nối gọi lệnh điều khiển đầu đọc
│   │   ├── database.py         # Truy vấn CSDL cho bot
│   │   ├── embeds.py           # Định dạng giao diện tin nhắn embed
│   │   ├── views.py            # Giao diện tương tác UI (Modal, Button)
│   │   ├── workers.py          # Luồng xử lý sự kiện ngầm và watchdog
│   │   └── reg.py              # Điểm nạp lệnh và khởi động bot
│   ├── client_logger.py        # Xử lý log từ đầu đọc
│   ├── config.py               # Quản lý cấu hình chung backend
│   ├── connector.py            # TCP Socket server hai chiều và xác thực
│   ├── database.py             # Lớp CSDL (MySQL + SQLite Fail-Safe)
│   ├── logger.py               # Quản lý log xoay vòng
│   ├── mdns_broadcaster.py     # Phát quảng bá mDNS trên mạng nội bộ
│   └── security.py             # Xác thực HMAC-SHA256
├── Dockerfile                  # Tệp build container tối ưu cho Docker Desktop
├── docker-compose.yml          # Triển khai đồng thời MySQL 8.0 và Backend
├── requirements.txt            # Danh sách thư viện Python
├── main.py                     # Điểm khởi chạy máy chủ FastAPI & TCP Socket
└── README.md
```

---

## Cài đặt và triển khai

### Cách 1: Triển khai bằng Docker & Docker Desktop (Khuyên dùng)

Hệ thống được đóng gói trên nền tảng Python 3.12-slim và MySQL 8.0, cấu hình múi giờ Việt Nam (`Asia/Ho_Chi_Minh`):

1. Khởi động ứng dụng Docker Desktop trên máy tính.
2. Di chuyển vào thư mục `backend`:
   ```bash
   cd backend
   ```
3. Tạo file cấu hình môi trường `.env` từ mẫu:
   ```bash
   cp .env.example .env
   ```
4. Khởi chạy toàn bộ hệ thống:
   ```bash
   docker compose up -d --build
   ```
5. Kiểm tra trạng thái và theo dõi log:
   ```bash
   docker compose ps
   docker compose logs -f nfc-backend
   ```
6. Dừng hệ thống an toàn (dữ liệu MySQL & SQLite được lưu trong volume):
   ```bash
   docker compose down
   ```

---

### Cách 2: Chạy trực tiếp (Local Python Virtual Environment)

Yêu cầu: Python 3.10+ và MySQL Server đang chạy (hoặc dùng SQLite tự động).

1. Tạo và kích hoạt môi trường ảo Python:
   ```bash
   cd backend
   python3 -m venv .venv
   source .venv/bin/activate    # Linux/macOS
   # .venv\Scripts\activate     # Windows
   ```
2. Cài đặt các thư viện:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```
3. Khởi chạy máy chủ:
   ```bash
   python main.py
   ```

---

## Cấu hình hệ thống

### 1. File cấu hình chính `config/config.json`
```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 5000,
    "debug": true
  },
  "tcp_server": {
    "enabled": true,
    "host": "0.0.0.0",
    "port": 1337
  },
  "security": {
    "auth_token": "systemauth",
    "require_auth": true
  },
  "database": {
    "type": "mysql",
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "2000",
    "name": "nfc_attendance",
    "sqlite_path": "data/attendance.db",
    "failsafe": {
      "enabled": true,
      "host": "127.0.0.1",
      "port": 3306,
      "user": "root",
      "password": "2000"
    }
  }
}
```

### 2. File cấu hình Discord Bot `config/bot_config.json`
```json
{
  "bot": {
    "token": "YOUR_DISCORD_BOT_TOKEN",
    "prefix": "!",
    "guild_id": "YOUR_DISCORD_GUILD_ID",
    "channel_status": "ID_KENH_TRANG_THAI",
    "channel_noti": "ID_KENH_DIEM_DANH",
    "channel_reg": "ID_KENH_DANG_KY_THE",
    "channel_info": "ID_KENH_THONG_TIN",
    "status_interval_minutes": 5,
    "status_update_mode": "edit",
    "admin_roles": ["Admin", "Teacher"],
    "enable_notifications": true
  }
}
```

---

## Danh sách lệnh Discord Bot

Hệ thống hỗ trợ song song cả Slash Command (`/`) và Prefix Command (`!`):

### 1. Quản lý thẻ và học sinh
- `/dangky [type] [tên_hs] [lớp] [uid]` hoặc `!dangky`: Đăng ký học sinh mới (Type 1: Nhập UID; Type 2: Đợi quẹt thẻ trên thiết bị).
- `/dangkythe [học sinh] [lớp]` hoặc `!dangkythe`: Gán thẻ chưa đăng ký vừa quẹt gần nhất cho học sinh.
- `/phanlop [học sinh] [lớp_mới]` hoặc `!phanlop`: Cập nhật lớp học cho học sinh (tìm theo Tên, Mã HS hoặc UID).
- `/themoi` hoặc `!themoi` (alias: `!lastcard`): Hiển thị thông tin thẻ lạ vừa quẹt trên đầu đọc.
- `/xoathe [uid]` hoặc `!xoathe`: Xóa đăng ký thẻ học sinh khỏi hệ thống.

### 2. Tra cứu điểm danh
- `/diemdanh [học sinh]` hoặc `!diemdanh` (alias: `!check`): Tra cứu hồ sơ, trạng thái điểm danh hôm nay và 5 lần điểm danh gần nhất.

### 3. Điều khiển đầu đọc ESP32 từ xa
- `/cauhinh [thiết bị] [cooldown] [còi_báo] [vị trí] [wifi]` hoặc `!cauhinh`: Cấu hình thông số đầu đọc ESP32 từ xa qua mạng TCP.
- `/khoidonglai [thiết bị]` hoặc `!khoidonglai` (alias: `!reboot`): Khởi động lại đầu đọc ESP32 từ xa.
- `/ketnoi` hoặc `!ketnoi`: Quét mạng LAN và dò tìm kết nối của các đầu đọc.

### 4. Quản trị hệ thống và kênh
- `/kenh [loai] [kenh]` hoặc `!kenh`: Thiết lập hoặc tra cứu phân luồng 4 kênh Discord (`status`, `noti`, `reg`, `info` hoặc `xem`), kèm chu kỳ cập nhật tự động.
- `/trangthai` hoặc `!trangthai` (alias: `!stats`): Báo cáo trạng thái toàn diện hệ thống (Backend, CSDL, Fail-Safe, số lượng học sinh, danh sách đầu đọc online).
- `/panel` hoặc `!panel`: Mở bảng điều khiển giao diện nút bấm và form modal tiện lợi.
- `/help` hoặc `!help`: Xem hướng dẫn sử dụng chi tiết.

---

## Cổng kết nối (Network Ports)

| Cổng | Giao thức | Dịch vụ | Chức năng |
| :--- | :--- | :--- | :--- |
| **5000** | HTTP / REST | FastAPI Server | API Quản trị, Webhook, xem thống kê & Healthcheck |
| **1337** | TCP Socket | TCP Connector | Kết nối 2 chiều liên tục với các đầu đọc ESP32 |
| **3306** | TCP | MySQL Server | CSDL lưu trữ hồ sơ học sinh và lịch sử điểm danh |
| **5353** | UDP Multicast | mDNS Broadcaster | Quảng bá nhận diện máy chủ `nfc-backend.local` trên mạng LAN |

---

## Bản quyền
Dự án được xây dựng và phát triển phục vụ cuộc thi Khoa Học Kỹ Thuật (KHKT) dành cho học sinh, nghiên cứu và ứng dụng quản lý học đường thông minh.