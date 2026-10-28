# 🎓 NFC School Auth Backend & Discord Bot

Hệ thống máy chủ trung tâm quản trị, xác thực và điểm danh học sinh thông minh qua thẻ NFC/RFID cho các trường học, kết nối thời gian thực với các thiết bị đầu đọc **ESP32** và tích hợp **Discord Bot** điều khiển từ xa.

---

## 🌟 Tính Năng Nổi Bật

- ⚡ **Giao thức Socket TCP 2 Chiều Siêu Tốc:**
  - Kết nối ổn định, duy trì liên tục giữa các đầu đọc ESP32 và Server với độ trễ phản hồi < 50ms.
  - Bắt tay xác thực bảo mật 3 bước (`handshake`) sử dụng mã hóa chữ ký số **HMAC-SHA256** chống giả mạo danh tính thiết bị và replay attack.
- 🔄 **Đồng Bộ Ngoại Tuyến (Offline Buffer Sync):**
  - Tự động nhận diện và đồng bộ hàng loạt các lượt quẹt thẻ được lưu tạm trong bộ nhớ flash của ESP32 khi mất mạng Wi-Fi ngay khi kết nối trở lại.
- 🛡️ **Hệ Thống CSDL Kép Dự Phòng Tự Động (Fail-Safe Dual Database):**
  - Sử dụng **MySQL** làm cơ sở dữ liệu chính.
  - Nếu MySQL gặp sự cố hoặc mất kết nối, hệ thống tự động chuyển mạch tức thì sang **SQLite** cục bộ để đảm bảo việc điểm danh của học sinh không bao giờ bị gián đoạn.
  - Tự động tái kết nối và phục hồi về MySQL khi dịch vụ hoạt động trở lại.
- ⚙️ **Cấu Hình Động & Khởi Động Lại Từ Xa (Remote Dynamic Config):**
  - Điều chỉnh trực tiếp thời gian giãn cách quẹt thẻ (`cooldown_ms`), độ dài còi bíp / đèn LED, đổi vị trí đặt đầu đọc hoặc cấu hình Wi-Fi từ xa qua Discord Bot hoặc API mà **không cần nạp lại firmware**.
  - ESP32 tự động lưu vào bộ nhớ **NVS** và áp dụng tức thì.
- 📡 **Giám Sát Thiết Bị Thời Gian Thực (Device Watchdog):**
  - Theo dõi nhịp tim (`heartbeat`) định kỳ của từng đầu đọc ESP32 trên toàn trường.
  - Tự động phát hiện và gửi cảnh báo mất nguồn / mất mạng lên Discord sau 15 giây không có tín hiệu.
- 🤖 **Discord Bot Quản Trị Đa Kênh Toàn Diện (Multi-Channel Bot):**
  - Phân luồng thông minh về 4 kênh riêng biệt: Trạng thái thiết bị (`status`), Thông báo điểm danh (`noti`), Đăng ký thẻ mới (`reg`), Tra cứu thông tin (`info`).
  - Hỗ trợ song song cả **13 Slash Commands (`/`)** và **Prefix Commands (`!`)**.
  - **Bảng điều khiển trực quan (`/panel`)** với hệ thống nút bấm và form pop-up (Modal) tiện lợi.

---

## 📁 Cấu Trúc Thư Mục Backend

```text
backend/
├── config/                     # Thư mục chứa cấu hình hoạt động
│   ├── config.json             # Cấu hình máy chủ TCP, HTTP API, MySQL & Fail-safe
│   └── bot_config.json         # Cấu hình Token bot Discord, phân bổ kênh
├── data/                       # Dữ liệu cục bộ (CSDL SQLite dự phòng: attendance.db)
├── log/                        # Nhật ký hoạt động chi tiết của Backend
├── client_log/                 # Nhật ký gỡ lỗi từ các đầu đọc ESP32 gửi về
├── src/                        # Mã nguồn ứng dụng
│   ├── bots/                   # Module Discord Bot
│   │   ├── config.py           # Quản lý cấu hình & kênh Discord
│   │   ├── connector.py        # Cầu nối gọi lệnh điều khiển đầu đọc từ Bot
│   │   └── reg.py              # Xử lý toàn bộ Slash commands, Prefix & UI Views
│   ├── client_logger.py        # Ghi nhận log từ client thiết bị
│   ├── config.py               # Trình tải & hợp nhất cấu hình hệ thống
│   ├── connector.py            # Quản lý kết nối TCP Socket 2 chiều & xác thực
│   ├── database.py             # Lớp trừu tượng CSDL (MySQL + SQLite Fail-Safe)
│   ├── logger.py               # Trình ghi log xoay vòng (Rotating File Handler)
│   ├── mdns_broadcaster.py     # Phát quảng bá mDNS tìm kiếm thiết bị trên LAN
│   └── security.py             # Xác thực HMAC-SHA256 & bảo mật mã hóa
├── Dockerfile                  # Tệp build container tối ưu cho Docker Desktop
├── docker-compose.yml          # Triển khai đồng thời MySQL 8.0 và Backend
├── requirements.txt            # Danh sách thư viện Python
├── main.py                     # Điểm khởi chạy máy chủ FastAPI & TCP Socket
└── README.md                   # Hướng dẫn chi tiết
```

---

## 🚀 Hướng Dẫn Cài Đặt & Triển Khai

### Cách 1: Triển Khai Nhanh Bằng Docker & Docker Desktop (Khuyên Dùng)

Hệ thống đã được đóng gói tối ưu trên nền tảng **Python 3.12-slim** và **MySQL 8.0**, tự động thiết lập múi giờ Việt Nam (`Asia/Ho_Chi_Minh`):

1. **Khởi động ứng dụng Docker Desktop** trên máy tính.
2. Di chuyển vào thư mục `backend`:
   ```bash
   cd backend
   ```
3. Tạo file cấu hình môi trường `.env` từ mẫu:
   ```bash
   cp .env.example .env
   ```
4. Khởi chạy toàn bộ hệ thống bằng 1 lệnh:
   ```bash
   docker compose up -d --build
   ```
5. Kiểm tra trạng thái và theo dõi log hoạt động:
   ```bash
   docker compose ps
   docker compose logs -f nfc-backend
   ```
6. Dừng hệ thống an toàn (dữ liệu MySQL & SQLite được lưu trữ bền vững trong volume):
   ```bash
   docker compose down
   ```

---

### Cách 2: Chạy Cục Bộ (Local Python Virtual Environment)

**Yêu cầu môi trường:** Python 3.10+ và MySQL Server đang chạy (hoặc dùng SQLite tự động).

1. Tạo và kích hoạt môi trường ảo Python:
   ```bash
   cd backend
   python3 -m venv .venv
   source .venv/bin/activate    # Trên Linux/macOS
   # .venv\Scripts\activate     # Trên Windows
   ```
2. Cài đặt các thư viện cần thiết:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```
3. Khởi chạy máy chủ:
   ```bash
   python main.py
   ```

---

## ⚙️ Cấu Hình Hệ Thống

### 1. File Cấu Hình Chính `config/config.json`
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

### 2. File Cấu Hình Discord Bot `config/bot_config.json`
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
    "admin_roles": ["Admin", "Teacher"],
    "enable_notifications": true
  }
}
```

---

## 🤖 Danh Sách Lệnh Discord Bot

Hệ thống hỗ trợ song song cả **Slash Command (`/`)** và **Prefix Command (`!`)**:

### 1. Quản Lý Thẻ & Học Sinh
- `/dangky [type] [tên_hs] [lớp] [uid]` hoặc `!dangky`: Đăng ký học sinh mới (Type 1: Nhập UID thẳng; Type 2: Đợi quẹt thẻ trên thiết bị).
- `/dangkythe [học sinh] [lớp]` hoặc `!dangkythe`: Gán thẻ chưa đăng ký vừa quẹt gần nhất cho học sinh.
- `/phanlop [học sinh] [lớp_mới]` hoặc `!phanlop`: Cập nhật lớp học cho học sinh (tìm theo Tên, Mã HS hoặc UID).
- `/themoi` hoặc `!themoi` (alias: `!lastcard`): Hiển thị thông tin thẻ lạ vừa quẹt trên đầu đọc.
- `/xoathe [uid]` hoặc `!xoathe`: Xóa đăng ký thẻ học sinh khỏi hệ thống.

### 2. Tra Cứu Điểm Danh
- `/diemdanh [học sinh]` hoặc `!diemdanh` (alias: `!check`): Tra cứu hồ sơ, trạng thái điểm danh hôm nay và 5 lần điểm danh gần nhất.

### 3. Điều Khiển Đầu Đọc ESP32 Từ Xa
- `/cauhinh [thiết bị] [cooldown] [còi_báo] [vị trí] [wifi]` hoặc `!cauhinh`: Cấu hình động thông số cho đầu đọc ESP32 từ xa qua mạng TCP.
- `/khoidonglai [thiết bị]` hoặc `!khoidonglai` (alias: `!reboot`): Khởi động lại (Reboot) đầu đọc ESP32 từ xa.
- `/ketnoi` hoặc `!ketnoi`: Quét mạng LAN và dò tìm kết nối của các đầu đọc.

### 4. Quản Trị Hệ Thống & Kênh
- `/kenh [loai] [kenh]` hoặc `!kenh`: Thiết lập hoặc tra cứu phân luồng 4 kênh Discord (`status`, `noti`, `reg`, `info` hoặc `xem`).
- `/trangthai` hoặc `!trangthai` (alias: `!stats`): Báo cáo trạng thái toàn diện hệ thống (Backend, CSDL, Fail-Safe, số lượng học sinh, danh sách đầu đọc online).
- `/panel` hoặc `!panel`: Mở bảng điều khiển giao diện nút bấm và form modal tiện lợi.
- `/help` hoặc `!help`: Xem hướng dẫn sử dụng chi tiết.

---

## 🔌 Cổng Giao Tiếp (Network Ports)

| Cổng | Giao thức | Dịch vụ | Chức năng |
| :--- | :--- | :--- | :--- |
| **5000** | HTTP / REST | FastAPI Server | API Quản trị, Webhook, xem thống kê & Healthcheck |
| **1337** | TCP Socket | TCP Connector | Kết nối 2 chiều liên tục với các đầu đọc ESP32 |
| **3306** | TCP | MySQL Server | CSDL lưu trữ hồ sơ học sinh và lịch sử điểm danh |
| **5353** | UDP Multicast | mDNS Broadcaster | Quảng bá nhận diện máy chủ `nfc-backend.local` trên mạng LAN |

---

## 📄 Bản Quyền
Dự án được xây dựng và phát triển phục vụ cuộc thi Khoa Học Kỹ Thuật (KHKT) dành cho học sinh, nghiên cứu và ứng dụng quản lý học đường thông minh.