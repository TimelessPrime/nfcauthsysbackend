from datetime import datetime
from typing import Any
import discord

from src.bots.connector import get_active_esp32_readers, get_pending_card
from src.bots.database import get_stats


def format_event_time(ts: Any) -> str:
    if not ts:
        return datetime.now().strftime("%H:%M:%S %d/%m/%Y")
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts).strftime("%H:%M:%S %d/%m/%Y")
        if isinstance(ts, str):
            return ts
    except Exception:
        pass
    return datetime.now().strftime("%H:%M:%S %d/%m/%Y")


def build_help_embed() -> discord.Embed:
    embed = discord.Embed(title="Danh sách lệnh hệ thống", color=discord.Color.blurple())
    embed.description = (
        "- `/dangky [type] [tên_hs] [lớp]`: Đăng ký thẻ (Type 1: Nhập UID / Type 2: Quẹt thẻ)\n"
        "- `/dangkythe [học sinh] [lớp]`: Gán thẻ vừa quẹt cho học sinh\n"
        "- `/phanlop [học sinh] [lớp]`: Cập nhật lớp học cho học sinh\n"
        "- `/diemdanh [học sinh]`: Tra cứu hồ sơ và lịch sử điểm danh\n"
        "- `/themoi`: Xem thẻ chưa đăng ký vừa quẹt trên đầu đọc\n"
        "- `/xoathe [uid]`: Xóa thẻ khỏi hệ thống\n"
        "- `/cauhinh [thiết bị] ...`: Cấu hình thông số đầu đọc ESP32 từ xa\n"
        "- `/khoidonglai [thiết bị]`: Khởi động lại đầu đọc từ xa qua mạng TCP\n"
        "- `/ketnoi`: Quét và kiểm tra kết nối đầu đọc ESP32 trên LAN\n"
        "- `/kenh [loai] [kenh]`: Thiết lập hoặc xem phân bổ kênh thông báo\n"
        "- `/trangthai`: Xem tình trạng hoạt động hệ thống\n"
        "- `/panel`: Bảng điều khiển giao diện nhanh"
    )
    return embed


def build_themoi_embed() -> discord.Embed:
    pending = get_pending_card()
    if not pending:
        embed = discord.Embed(title="Thẻ chưa đăng ký", color=discord.Color.blurple())
        embed.description = "- Trạng thái: Chưa có thẻ mới nào quẹt trên đầu đọc."
        return embed

    embed = discord.Embed(title="Thẻ chưa đăng ký", color=discord.Color.orange())
    time_str = format_event_time(pending.get("timestamp"))
    embed.description = (
        f"- UID: `{pending.get('uid', 'N/A')}`\n"
        f"- Đầu đọc: {pending.get('device_id', 'ESP32')}\n"
        f"- Thời gian: {time_str}\n"
        f"- Hướng dẫn: Dùng lệnh `/dangky type:2` hoặc `/dangkythe` để gán thẻ này."
    )
    return embed


def build_diemdanh_embed(student: dict[str, Any], today_scans: int, history: list[dict[str, Any]]) -> discord.Embed:
    embed = discord.Embed(title="Hồ sơ điểm danh học sinh", color=discord.Color.blue())
    lines = [
        f"- Họ và tên: **{student['full_name']}**",
        f"- Mã học sinh: {student['student_id']}",
        f"- Lớp: {student['class_name']}",
        f"- Mã thẻ UID: `{student['uid']}`",
        f"- Lượt điểm danh hôm nay: {today_scans} lượt",
    ]
    if history:
        lines.append("\n**Lịch sử quẹt thẻ gần nhất:**")
        for log in history[:5]:
            ts = log.get("timestamp", "N/A")
            dev = log.get("device_id", "ESP32")
            st = log.get("status", "SUCCESS")
            lines.append(f"- {ts} | Thiết bị: {dev} | Trạng thái: {st}")
    else:
        lines.append("\n- Lịch sử: Chưa ghi nhận lượt điểm danh nào.")
    embed.description = "\n".join(lines)
    return embed


def build_ketnoi_embed(report: dict[str, Any]) -> discord.Embed:
    connected = report.get("connected_devices", [])
    backend_ip = report.get("backend_ip", "127.0.0.1")
    tcp_port = report.get("tcp_port", 1337)

    color = discord.Color.green() if connected else discord.Color.orange()
    embed = discord.Embed(title="Trạng thái kết nối đầu đọc", color=color)
    lines = [
        f"- Cổng TCP Backend: {backend_ip}:{tcp_port}",
        f"- Đầu đọc online: {len(connected)} thiết bị",
    ]
    if connected:
        for c in connected:
            auth = "Đã xác thực HMAC" if c.get("authenticated") else "Chưa xác thực"
            lines.append(f"- {c['device_id']} ({c['ip']}) [{auth}]")
    else:
        lines.append("- Trạng thái: Chưa có đầu đọc nào kết nối qua TCP.")

    embed.description = "\n".join(lines)
    return embed


def build_trangthai_embed() -> discord.Embed:
    metrics = get_stats()
    readers = get_active_esp32_readers()
    embed = discord.Embed(title="Trạng thái hệ thống", color=discord.Color.blurple())
    lines = [
        f"- Điểm danh hôm nay: {metrics['today_scans']} lượt",
        f"- Tổng học sinh: {metrics['total_students']}",
        f"- Cơ sở dữ liệu: {metrics['active_database']}",
        f"- Đầu đọc online: {len(readers)} thiết bị",
    ]
    if readers:
        for r in readers:
            dev_name = r.get("device_id", "ESP32")
            ip = r.get("ip", "N/A")
            uptime = r.get("uptime_s")
            rssi = r.get("rssi")
            free_heap = r.get("free_heap")

            sub = [f"IP: {ip}"]
            if uptime is not None:
                h = uptime // 3600
                m = (uptime % 3600) // 60
                s = uptime % 60
                sub.append(f"Uptime: {h}h {m}m {s}s" if h > 0 else f"Uptime: {m}m {s}s")
            if rssi is not None and rssi not in (0, -100):
                sub.append(f"Wi-Fi: {rssi} dBm")
            if free_heap:
                sub.append(f"RAM: {free_heap // 1024} KB")
            lines.append(f"  • **{dev_name}**: {', '.join(sub)}")

    if metrics.get("failsafe_active"):
        lines.append("- Cảnh báo: Đang sử dụng CSDL dự phòng (Fail-Safe SQLite)")
    embed.description = "\n".join(lines)
    return embed


def build_esp32_status_embed(interval_min: int = 5, mode_text: str = "Live Dashboard") -> discord.Embed:
    readers = get_active_esp32_readers()
    metrics = get_stats()
    now_str = datetime.now().strftime("%H:%M:%S %d/%m/%Y")

    color = discord.Color.green() if readers else discord.Color.orange()
    embed = discord.Embed(title="Trạng thái đầu đọc ESP32", color=color)

    desc_lines = [
        f"- Chu kỳ cập nhật: Mỗi {interval_min} phút ({mode_text})",
        f"- Đầu đọc online: {len(readers)} thiết bị",
        f"- Điểm danh hôm nay: {metrics.get('today_scans', 0)} lượt",
        f"- Tổng học sinh: {metrics.get('total_students', 0)}",
        f"- Cơ sở dữ liệu: {metrics.get('active_database', 'MySQL')}"
        + (" (Đang dùng CSDL dự phòng)" if metrics.get("failsafe_active") else ""),
    ]
    embed.description = "\n".join(desc_lines)

    if readers:
        for idx, r in enumerate(readers, 1):
            dev_id = r.get("device_id", f"ESP32_{idx}")
            ip = r.get("ip", "N/A")
            auth = "Đã xác thực HMAC" if r.get("authenticated") else "Chưa xác thực"
            uptime = r.get("uptime_s")
            rssi = r.get("rssi")
            heap = r.get("free_heap")
            pending = r.get("pending_offline", 0)

            dev_lines = [
                f"- Địa chỉ IP: {ip} ({auth})",
            ]
            if uptime is not None:
                h = uptime // 3600
                m = (uptime % 3600) // 60
                s = uptime % 60
                uptime_str = f"{h}h {m}m {s}s" if h > 0 else f"{m}m {s}s"
                dev_lines.append(f"- Thời gian hoạt động (Uptime): {uptime_str}")

            if rssi is not None and rssi not in (0, -100):
                quality = "Tốt" if rssi > -70 else "Yếu"
                dev_lines.append(f"- Tín hiệu Wi-Fi: {rssi} dBm ({quality})")

            if heap:
                dev_lines.append(f"- Bộ nhớ RAM khả dụng: {heap // 1024} KB")

            if pending > 0:
                dev_lines.append(f"- Bản ghi ngoại tuyến chờ đẩy: {pending}")

            embed.add_field(
                name=f"Thiết bị #{idx}: {dev_id}",
                value="\n".join(dev_lines),
                inline=False,
            )
    else:
        embed.add_field(
            name="Thông báo kết nối",
            value="Chưa có đầu đọc nào kết nối tới máy chủ TCP.\nKiểm tra nguồn điện và mạng Wi-Fi của thiết bị.",
            inline=False,
        )

    embed.set_footer(text=f"Cập nhật lúc: {now_str} | Lần tới: sau {interval_min} phút")
    return embed


def build_xoathe_embed(uid: str, success: bool) -> discord.Embed:
    clean_uid = uid.strip().upper()
    if success:
        embed = discord.Embed(title="Xóa thẻ thành công", color=discord.Color.green())
        embed.description = f"- Mã UID: `{clean_uid}`\n- Trạng thái: Đã xóa khỏi cơ sở dữ liệu"
    else:
        embed = discord.Embed(title="Xóa thẻ không thành công", color=discord.Color.red())
        embed.description = f"- Mã UID: `{clean_uid}`\n- Lí do: Không tìm thấy thẻ trong cơ sở dữ liệu"
    return embed
