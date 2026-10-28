import asyncio
from datetime import datetime
from typing import Any

import discord
from discord import app_commands, ui
from discord.ext import commands

from src.bots.config import (
    get_bot_prefix,
    get_discord_token,
    get_guild_id,
    get_notification_channel_id,
    get_noti_channel_id,
    get_status_channel_id,
    get_reg_channel_id,
    get_info_channel_id,
    get_all_channel_ids,
    set_channel_id,
    get_status_interval_minutes,
    set_status_interval_minutes,
    get_status_update_mode,
    get_status_message_id,
    set_status_message_id,
    is_notifications_enabled,
    is_sync_slash_commands,
)
from src.bots.connector import (
    clear_pending_card,
    get_active_esp32_readers,
    get_pending_card,
    register_attendance_hook,
    send_config_update,
    send_reader_reboot,
    trigger_esp32_discovery,
)
from src.bots.database import (
    delete_card,
    find_student,
    get_recent_logs,
    get_stats,
    register_or_update_student,
    update_student_class,
)
from src.logger import get_logger

logger = get_logger("discord_bot")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix=get_bot_prefix(),
    intents=intents,
    help_command=None,
)

_event_queue: asyncio.Queue[dict[str, Any]] | None = None
_bot_loop: asyncio.AbstractEventLoop | None = None
_worker_task: asyncio.Task[None] | None = None
_status_periodic_task: asyncio.Task[None] | None = None
_recent_unknown_cards: dict[str, float] = {}
_recent_notified_students: dict[str, float] = {}



class RegisterType1Modal(ui.Modal, title="Đăng Ký - Nhập UID (Type 1)"):
    name_input = ui.TextInput(label="Tên học sinh", placeholder="Ví dụ: Nguyễn Văn An", min_length=2, max_length=50)
    class_input = ui.TextInput(label="Lớp", placeholder="Ví dụ: 12A1", min_length=1, max_length=20)
    uid_input = ui.TextInput(label="Mã UID Thẻ (Hex)", placeholder="Ví dụ: E2801102", min_length=4, max_length=32)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        clean_uid = self.uid_input.value.strip().upper()
        name = self.name_input.value.strip()
        cls = self.class_input.value.strip() or "Chưa phân lớp"

        if len(clean_uid) < 4:
            fail_embed = discord.Embed(title="Đăng Ký Thất Bại", color=discord.Color.red())
            fail_embed.description = "Lí Do: Mã UID không hợp lệ (cần ít nhất 4 ký tự)"
            await interaction.response.send_message(embed=fail_embed)
            return

        saved, _ = register_or_update_student(full_name=name, uid=clean_uid, class_name=cls)
        embed = discord.Embed(title="Đăng Ký Thành Công", color=discord.Color.green())
        embed.description = (
            f"- Tên học sinh: {saved['full_name']}\n"
            f"- Lớp: {saved['class_name']}\n"
            f"- UID: {saved['uid']}\n"
            f"- Phương thức: Trực tiếp (Bot)"
        )
        await interaction.response.send_message(embed=embed)


class RegisterType2Modal(ui.Modal, title="Đăng Ký - Quẹt Thẻ (Type 2)"):
    name_input = ui.TextInput(label="Tên học sinh", placeholder="Ví dụ: Nguyễn Văn An", min_length=2, max_length=50)
    class_input = ui.TextInput(label="Lớp", placeholder="Ví dụ: 12A1", min_length=1, max_length=20)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        name = self.name_input.value.strip()
        cls = self.class_input.value.strip() or "Chưa phân lớp"

        pending = get_pending_card()
        if pending:
            p_uid = pending["uid"]
            dev = pending.get("device_id", "ESP32")
            clear_pending_card()
            saved, _ = register_or_update_student(full_name=name, uid=p_uid, class_name=cls)
            embed = discord.Embed(title="Đăng Ký Thành Công", color=discord.Color.green())
            embed.description = (
                f"- Tên học sinh: {saved['full_name']}\n"
                f"- Lớp: {saved['class_name']}\n"
                f"- UID: {saved['uid']}\n"
                f"- Thiết bị: {dev}"
            )
            await interaction.response.send_message(embed=embed)
        else:
            embed, view = _build_waiting_card_view(name, cls)
            await interaction.response.send_message(embed=embed, view=view)


class PhanLopModal(ui.Modal, title="Phân Lớp Học Sinh"):
    hs_input = ui.TextInput(label="Tên học sinh, Mã HS hoặc UID", placeholder="Ví dụ: Nguyễn Văn An hoặc HS001", min_length=2, max_length=50)
    class_input = ui.TextInput(label="Lớp mới", placeholder="Ví dụ: 12A1", min_length=1, max_length=20)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        updated = update_student_class(self.hs_input.value.strip(), self.class_input.value.strip())
        if updated:
            embed = discord.Embed(title="Phân Lớp Thành Công", color=discord.Color.green())
            embed.description = (
                f"- Tên học sinh: {updated['full_name']}\n"
                f"- Lớp: {updated['class_name']}\n"
                f"- UID: {updated['uid']}"
            )
            await interaction.response.send_message(embed=embed)
        else:
            embed = discord.Embed(title="Phân Lớp Thất Bại", color=discord.Color.red())
            embed.description = f"Lí Do: Không tìm thấy học sinh với thông tin: {self.hs_input.value.strip()}"
            await interaction.response.send_message(embed=embed)


def _build_waiting_card_view(ten_hs: str, lop: str) -> tuple[discord.Embed, ui.View]:
    readers = get_active_esp32_readers()
    dev_str = readers[0]["device_id"] if readers else "Chưa có thiết bị online"

    embed = discord.Embed(title="Chờ Quẹt Thẻ", color=discord.Color.gold())
    embed.description = (
        f"- Tên học sinh: {ten_hs}\n"
        f"- Lớp: {lop}\n"
        f"- Đầu đọc: {dev_str}\n"
        f"- Hướng dẫn: Quẹt thẻ vào đầu đọc ESP32 rồi bấm nút xác nhận bên dưới"
    )

    view = ui.View(timeout=120)
    btn = ui.Button(label="Xác nhận thẻ vừa quẹt", style=discord.ButtonStyle.primary, emoji="⚡")

    async def _btn_callback(interaction: discord.Interaction) -> None:
        new_pending = get_pending_card()
        if not new_pending:
            fail_embed = discord.Embed(title="Đăng Ký Thất Bại", color=discord.Color.red())
            fail_embed.description = "Lí Do: Chưa phát hiện thẻ mới trên đầu đọc. Vui lòng quẹt thẻ trước khi bấm nút."
            await interaction.response.send_message(embed=fail_embed, ephemeral=True)
            return

        p_uid = new_pending["uid"]
        dev = new_pending.get("device_id", "ESP32")
        clear_pending_card()
        saved, _ = register_or_update_student(full_name=ten_hs, uid=p_uid, class_name=lop)
        success_embed = discord.Embed(title="Đăng Ký Thành Công", color=discord.Color.green())
        success_embed.description = (
            f"- Tên học sinh: {saved['full_name']}\n"
            f"- Lớp: {saved['class_name']}\n"
            f"- UID: {saved['uid']}\n"
            f"- Thiết bị: {dev}"
        )
        await interaction.response.edit_message(embed=success_embed, view=None)

    btn.callback = _btn_callback
    view.add_item(btn)
    return embed, view


class QuickConfigReaderModal(ui.Modal, title="Cấu Hình Đầu Đọc ESP32"):
    device_id_input = ui.TextInput(label="ID Đầu Đọc (hoặc 'all')", placeholder="Ví dụ: READER_01 hoặc all", min_length=1, max_length=50)
    cooldown_input = ui.TextInput(label="Cooldown Quẹt Thẻ (ms)", placeholder="Mặc định: 1000", required=False, max_length=6)
    feedback_input = ui.TextInput(label="Thời lượng Còi & LED (ms)", placeholder="Mặc định: 200", required=False, max_length=6)
    location_input = ui.TextInput(label="Vị Trí Đặt Máy", placeholder="Ví dụ: Phòng 10A1", required=False, max_length=50)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        target = self.device_id_input.value.strip()
        payload: dict[str, Any] = {}
        if self.cooldown_input.value.strip():
            try:
                payload["cooldown_ms"] = int(self.cooldown_input.value.strip())
            except ValueError:
                pass
        if self.feedback_input.value.strip():
            try:
                payload["feedback_duration_ms"] = int(self.feedback_input.value.strip())
            except ValueError:
                pass
        if self.location_input.value.strip():
            payload["location"] = self.location_input.value.strip()

        if not payload:
            await interaction.response.send_message("⚠️ Không có thông số nào được nhập để thay đổi.", ephemeral=True)
            return

        res = send_config_update(target, payload)
        if res.get("success"):
            embed = discord.Embed(title="⚙️ Đã Gửi Cấu Hình Xuống Đầu Đọc", color=discord.Color.blue())
            embed.description = f"- Thiết bị: **{target}**\n- Kết quả: {res.get('message')}"
        else:
            embed = discord.Embed(title="❌ Lỗi Cấu Hình", color=discord.Color.red())
            embed.description = f"- Lí do: {res.get('message')}"
        await interaction.response.send_message(embed=embed, ephemeral=True)


class RegistrationPanelView(ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @ui.button(label="Quẹt thẻ (Type 2)", style=discord.ButtonStyle.primary, emoji="⚡")
    async def btn_type2_reg(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await interaction.response.send_modal(RegisterType2Modal())

    @ui.button(label="Nhập UID (Type 1)", style=discord.ButtonStyle.secondary, emoji="📝")
    async def btn_type1_reg(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await interaction.response.send_modal(RegisterType1Modal())

    @ui.button(label="Phân lớp", style=discord.ButtonStyle.primary, emoji="🏫")
    async def btn_phanlop(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await interaction.response.send_modal(PhanLopModal())

    @ui.button(label="Cấu hình đầu đọc", style=discord.ButtonStyle.secondary, emoji="⚙️")
    async def btn_config(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await interaction.response.send_modal(QuickConfigReaderModal())

    @ui.button(label="Quét thiết bị", style=discord.ButtonStyle.secondary, emoji="📡")
    async def btn_connect(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(embed=_build_ketnoi_embed(trigger_esp32_discovery()), ephemeral=True)

    @ui.button(label="Trạng thái", style=discord.ButtonStyle.success, emoji="📊")
    async def btn_stats(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await interaction.response.send_message(embed=_build_trangthai_embed(), ephemeral=True)

    @ui.button(label="Kênh hệ thống", style=discord.ButtonStyle.secondary, emoji="📋")
    async def btn_channels(self, interaction: discord.Interaction, _: ui.Button) -> None:
        all_channels = get_all_channel_ids()
        def fmt_ch(ch_id: int | None) -> str:
            if not ch_id:
                return "*Chưa cấu hình (dùng kênh mặc định)*"
            ch = bot.get_channel(ch_id)
            return f"<#{ch_id}> (`{ch.name if ch else ch_id}`)"

        interval = get_status_interval_minutes()
        mode_str = "Live Dashboard (Sửa tin nhắn)" if get_status_update_mode() == "edit" else "Định kỳ (Gửi tin mới)"
        interval_desc = f"Mỗi `{interval}` phút ({mode_str})" if interval > 0 else "Đang tắt"

        embed = discord.Embed(title="📋 Cấu Hình Kênh Discord Hệ Thống", color=discord.Color.blurple())
        embed.description = (
            f"- 📡 **Kênh Trạng Thái Thiết Bị (`status`)**: {fmt_ch(all_channels.get('status'))}\n"
            f"- 🔔 **Kênh Thông Báo Điểm Danh (`noti`)**: {fmt_ch(all_channels.get('noti'))}\n"
            f"- 📝 **Kênh Đăng Ký Thẻ (`reg`)**: {fmt_ch(all_channels.get('reg'))}\n"
            f"- ℹ️ **Kênh Thông Tin Chung (`info`)**: {fmt_ch(all_channels.get('info'))}\n"
            f"- ⏱️ **Tự Động Cập Nhật Trạng Thái**: {interval_desc}\n\n"
            f"💡 *Để gán kênh mới, dùng lệnh:* `/kenh [loai] [#kenh]`\n"
            f"💡 *Để đổi chu kỳ cập nhật, dùng:* `/kenh loai:status chu_ky_phut:[phút]`"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)



def _build_ketnoi_embed(report: dict[str, Any]) -> discord.Embed:
    connected = report.get("connected_devices", [])
    backend_ip = report.get("backend_ip", "127.0.0.1")
    tcp_port = report.get("tcp_port", 1337)

    color = discord.Color.green() if connected else discord.Color.orange()
    embed = discord.Embed(title="Kết Nối Đầu Đọc", color=color)

    lines = [
        f"- Cổng TCP Backend: {backend_ip}:{tcp_port}",
        f"- Đầu đọc online: {len(connected)} thiết bị",
    ]
    if connected:
        for c in connected:
            auth = "Đã xác thực" if c.get("authenticated") else "Chưa xác thực"
            lines.append(f"- Thiết bị: {c['device_id']} ({c['ip']}) [{auth}]")
    else:
        lines.append("- Trạng thái: Chưa có đầu đọc nào kết nối TCP")

    embed.description = "\n".join(lines)
    return embed


def _build_help_embed() -> discord.Embed:
    embed = discord.Embed(title="Danh Sách Lệnh", color=discord.Color.blurple())
    embed.description = (
        "- `/dangky [type] [tên hs] [lớp]`: Đăng ký thẻ (Type 1: Nhập UID thẳng / Type 2: Quẹt thẻ)\n"
        "- `/phanlop [học sinh] [lớp]`: Phân lớp hoặc cập nhật lớp học cho học sinh\n"
        "- `/diemdanh [hs]`: Tra cứu học sinh hoặc xem lịch sử điểm danh\n"
        "- `/cauhinh`: Cấu hình động từ xa cho đầu đọc (Cooldown, Còi, Vị trí, Wi-Fi)\n"
        "- `/khoidonglai [thiết bị]`: Khởi động lại (Reboot) đầu đọc ESP32 từ xa\n"
        "- `/kenh [loai] [kenh]`: Thiết lập hoặc tra cứu các kênh Discord (status, noti, reg, info)\n"
        "- `/themoi`: Xem thẻ chưa đăng ký vừa quẹt trên đầu đọc\n"
        "- `/trangthai`: Xem tình trạng hệ thống và đầu đọc\n"
        "- `/ketnoi`: Quét và kiểm tra kết nối đầu đọc ESP32\n"
        "- `/xoathe [uid]`: Xóa thẻ học sinh khỏi hệ thống\n"
        "- `/panel`: Bảng điều khiển tương tác nhanh"
    )
    return embed



def _build_themoi_embed() -> discord.Embed:
    pending = get_pending_card()
    if not pending:
        embed = discord.Embed(title="Thẻ Chưa Đăng Ký", color=discord.Color.blurple())
        embed.description = "- Trạng thái: Chưa có thẻ mới nào quẹt trên đầu đọc"
        return embed

    embed = discord.Embed(title="Thẻ Chưa Đăng Ký", color=discord.Color.orange())
    time_str = _format_event_time(pending.get("timestamp"))
    embed.description = (
        f"- UID: {pending.get('uid', 'N/A')}\n"
        f"- Đầu đọc: {pending.get('device_id', 'ESP32')}\n"
        f"- Thời gian: {time_str}\n"
        f"- Hướng dẫn: Dùng `/dangky` (Type 2) để gán thẻ này cho học sinh"
    )
    return embed


def _build_diemdanh_embed(hs: str | None) -> discord.Embed:
    if hs:
        student = find_student(hs)
        if not student:
            embed = discord.Embed(title="Tra Cứu Thất Bại", color=discord.Color.red())
            embed.description = f"Lí Do: Không tìm thấy học sinh với từ khóa: {hs}"
            return embed

        embed = discord.Embed(title="Thông Tin Học Sinh", color=discord.Color.blue())
        embed.description = (
            f"- Tên học sinh: {student.get('full_name', 'N/A')}\n"
            f"- Lớp: {student.get('class_name', 'Chưa phân lớp')}\n"
            f"- UID: {student.get('uid', 'Chưa có')}\n"
            f"- Trạng thái: Đã đăng ký"
        )
        return embed

    logs = get_recent_logs(limit=8)
    embed = discord.Embed(title="Lịch Sử Điểm Danh", color=discord.Color.blurple())
    if not logs:
        embed.description = "- Trạng thái: Chưa có lượt điểm danh nào được ghi nhận"
    else:
        lines = []
        for log in logs:
            name = log.get("full_name") or log.get("uid")
            cls = f" ({log.get('class_name')})" if log.get("class_name") else ""
            time_str = _format_event_time(log.get("timestamp"))
            lines.append(f"- {name}{cls} - {time_str} (UID: `{log.get('uid')}`)")
        embed.description = "\n".join(lines)
    return embed


def _build_trangthai_embed() -> discord.Embed:
    metrics = get_stats()
    readers = get_active_esp32_readers()
    embed = discord.Embed(title="Trạng Thái Hệ Thống", color=discord.Color.blurple())
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
            if rssi is not None and rssi != 0 and rssi != -100:
                sub.append(f"Wi-Fi: {rssi} dBm")
            if free_heap:
                sub.append(f"RAM: {free_heap // 1024} KB")
            lines.append(f"  • **{dev_name}**: {', '.join(sub)}")

    if metrics.get("failsafe_active"):
        lines.append("- Cảnh báo: Đang sử dụng CSDL dự phòng (Fail-Safe)")
    embed.description = "\n".join(lines)
    return embed


def _build_esp32_status_embed(interval_min: int = 5) -> discord.Embed:
    readers = get_active_esp32_readers()
    metrics = get_stats()
    now_str = datetime.now().strftime("%H:%M:%S %d/%m/%Y")

    if readers:
        embed = discord.Embed(
            title="📡 Bảng Trạng Thái Đầu Đọc ESP32 (Live Dashboard)",
            color=discord.Color.green(),
        )
    else:
        embed = discord.Embed(
            title="📡 Bảng Trạng Thái Đầu Đọc ESP32 (Live Dashboard)",
            color=discord.Color.orange(),
        )

    mode_text = "Live Dashboard (Sửa tin nhắn)" if get_status_update_mode() == "edit" else "Định kỳ (Gửi tin mới)"
    desc_lines = [
        f"⏱️ **Chu kỳ cập nhật:** Mỗi `{interval_min}` phút ({mode_text})",
        f"🟢 **Đầu đọc đang online:** `{len(readers)}` thiết bị",
        f"📊 **Điểm danh hôm nay:** `{metrics.get('today_scans', 0)}` lượt",
        f"👥 **Tổng số học sinh:** `{metrics.get('total_students', 0)}`",
        f"🗄️ **Cơ sở dữ liệu:** `{metrics.get('active_database', 'MySQL')}`"
        + (" *(⚠️ Đang dùng Fail-Safe SQLite)*" if metrics.get("failsafe_active") else ""),
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
                f"• **IP kết nối:** `{ip}` ({auth})",
            ]
            if uptime is not None:
                h = uptime // 3600
                m = (uptime % 3600) // 60
                s = uptime % 60
                uptime_str = f"{h}h {m}m {s}s" if h > 0 else f"{m}m {s}s"
                dev_lines.append(f"• **Thời gian hoạt động (Uptime):** `{uptime_str}`")

            if rssi is not None and rssi not in (0, -100):
                quality = "Rất tốt" if rssi > -60 else ("Tốt" if rssi > -70 else "Yếu")
                dev_lines.append(f"• **Tín hiệu Wi-Fi:** `{rssi} dBm` ({quality})")

            if heap:
                dev_lines.append(f"• **Bộ nhớ RAM khả dụng:** `{heap // 1024} KB` free heap")

            if pending > 0:
                dev_lines.append(f"• **Bản ghi offline chờ đẩy:** `{pending}` bản ghi")

            embed.add_field(
                name=f"📟 Thiết Bị #{idx}: {dev_id}",
                value="\n".join(dev_lines),
                inline=False,
            )
    else:
        embed.add_field(
            name="⚠️ Không Có Thiết Bị Kết Nối",
            value="Hiện tại chưa có đầu đọc ESP32 nào kết nối tới máy chủ.\nKiểm tra nguồn điện và kết nối Wi-Fi của đầu đọc.",
            inline=False,
        )

    embed.set_footer(
        text=f"Cập nhật lúc: {now_str} • Cập nhật kế tiếp sau {interval_min} phút"
    )
    return embed


def _build_xoathe_embed(uid: str) -> discord.Embed:
    clean_uid = uid.strip().upper()
    success = delete_card(clean_uid)
    if success:
        embed = discord.Embed(title="Xóa Thẻ Thành Công", color=discord.Color.green())
        embed.description = (
            f"- UID: {clean_uid}\n"
            f"- Trạng thái: Đã xóa khỏi hệ thống"
        )
    else:
        embed = discord.Embed(title="Xóa Thẻ Thất Bại", color=discord.Color.red())
        embed.description = f"Lí Do: Không tìm thấy thẻ có UID {clean_uid} trong cơ sở dữ liệu"
    return embed


@bot.event
async def on_ready() -> None:
    global _bot_loop, _event_queue, _worker_task, _status_periodic_task
    _bot_loop = asyncio.get_running_loop()
    if _event_queue is None:
        _event_queue = asyncio.Queue(maxsize=500)

    logger.info(f"Discord Bot online as {bot.user}")

    if is_sync_slash_commands():
        try:
            guild_id = get_guild_id()
            if guild_id:
                guild_obj = discord.Object(id=guild_id)
                bot.tree.copy_global_to(guild=guild_obj)
                synced = await bot.tree.sync(guild=guild_obj)
                logger.info(f"Synced {len(synced)} slash commands to guild {guild_id}")
            else:
                synced = await bot.tree.sync()
                logger.info(f"Synced {len(synced)} global slash commands")
        except Exception as e:
            logger.warning(f"Error syncing slash commands: {e}")

    if _worker_task is None or _worker_task.done():
        _worker_task = bot.loop.create_task(_attendance_event_worker())

    if _status_periodic_task is None or _status_periodic_task.done():
        _status_periodic_task = bot.loop.create_task(_status_periodic_worker())



@bot.tree.command(name="dangky", description="Đăng ký thẻ học sinh (Type 1: Nhập UID thẳng / Type 2: Quẹt thẻ trên thiết bị)")
@app_commands.describe(
    type="1: Nhập UID thẳng trên bot | 2: Quẹt thẻ trên thiết bị",
    ten_hs="Họ và tên học sinh",
    lop="Lớp học của học sinh (Ví dụ: 12A1)",
    uid="Mã UID thẻ (tùy chọn nhập nhanh cho Type 1)",
)
@app_commands.choices(
    type=[
        app_commands.Choice(name="1 - Nhập UID thẳng trên bot", value=1),
        app_commands.Choice(name="2 - Quẹt thẻ trên thiết bị kết nối", value=2),
    ]
)
async def slash_dangky(
    interaction: discord.Interaction,
    type: app_commands.Choice[int],
    ten_hs: str,
    lop: str = "Chưa phân lớp",
    uid: str | None = None,
) -> None:
    class_name = lop.strip() if lop else "Chưa phân lớp"
    name = ten_hs.strip()

    if type.value == 1:
        if uid:
            clean_uid = uid.strip().upper()
            if len(clean_uid) < 4:
                fail_embed = discord.Embed(title="Đăng Ký Thất Bại", color=discord.Color.red())
                fail_embed.description = "Lí Do: Mã UID không hợp lệ (cần ít nhất 4 ký tự)"
                await interaction.response.send_message(embed=fail_embed)
                return
            saved, _ = register_or_update_student(full_name=name, uid=clean_uid, class_name=class_name)
            embed = discord.Embed(title="Đăng Ký Thành Công", color=discord.Color.green())
            embed.description = (
                f"- Tên học sinh: {saved['full_name']}\n"
                f"- Lớp: {saved['class_name']}\n"
                f"- UID: {saved['uid']}\n"
                f"- Phương thức: Trực tiếp (Bot)"
            )
            await interaction.response.send_message(embed=embed)
        else:
            modal = RegisterType1Modal()
            modal.name_input.default = name
            modal.class_input.default = class_name
            await interaction.response.send_modal(modal)

    elif type.value == 2:
        pending = get_pending_card()
        if pending:
            p_uid = pending["uid"]
            dev = pending.get("device_id", "ESP32")
            clear_pending_card()
            saved, _ = register_or_update_student(full_name=name, uid=p_uid, class_name=class_name)
            embed = discord.Embed(title="Đăng Ký Thành Công", color=discord.Color.green())
            embed.description = (
                f"- Tên học sinh: {saved['full_name']}\n"
                f"- Lớp: {saved['class_name']}\n"
                f"- UID: {saved['uid']}\n"
                f"- Thiết bị: {dev}"
            )
            await interaction.response.send_message(embed=embed)
        else:
            embed, view = _build_waiting_card_view(name, class_name)
            await interaction.response.send_message(embed=embed, view=view)


@bot.tree.command(name="phanlop", description="Phân lớp / cập nhật lớp học cho học sinh")
@app_commands.describe(
    hs="Tên học sinh, mã học sinh hoặc UID cần phân lớp",
    lop="Tên lớp mới (Ví dụ: 12A1)",
)
async def slash_phanlop(interaction: discord.Interaction, hs: str, lop: str) -> None:
    updated = update_student_class(hs, lop)
    if updated:
        embed = discord.Embed(title="Phân Lớp Thành Công", color=discord.Color.green())
        embed.description = (
            f"- Tên học sinh: {updated['full_name']}\n"
            f"- Lớp: {updated['class_name']}\n"
            f"- UID: {updated['uid']}"
        )
        await interaction.response.send_message(embed=embed)
    else:
        embed = discord.Embed(title="Phân Lớp Thất Bại", color=discord.Color.red())
        embed.description = f"Lí Do: Không tìm thấy học sinh với thông tin: {hs}"
        await interaction.response.send_message(embed=embed)


@bot.tree.command(name="dangkythe", description="Gán thẻ vừa quẹt cho học sinh (Tương đương /dangky type 2)")
@app_commands.describe(hs="Tên hoặc mã học sinh", lop="Lớp học của học sinh (Ví dụ: 12A1)")
async def slash_dangkythe(interaction: discord.Interaction, hs: str, lop: str = "Chưa phân lớp") -> None:
    type_choice = app_commands.Choice(name="2 - Quẹt thẻ trên thiết bị kết nối", value=2)
    await slash_dangky(interaction, type_choice, ten_hs=hs, lop=lop)


@bot.tree.command(name="ketnoi", description="Yêu cầu Backend chủ động dò tìm và kết nối tới thiết bị ESP32 trên LAN")
async def slash_ketnoi(interaction: discord.Interaction) -> None:
    await interaction.response.defer(thinking=True)
    await interaction.followup.send(embed=_build_ketnoi_embed(trigger_esp32_discovery()))


@bot.tree.command(name="help", description="Xem danh sách lệnh và hướng dẫn sử dụng bot NFC")
async def slash_help(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(embed=_build_help_embed())


@bot.tree.command(name="themoi", description="Xem thẻ chưa đăng ký vừa quẹt gần nhất tại đầu đọc ESP32")
async def slash_themoi(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(embed=_build_themoi_embed())


@bot.tree.command(name="diemdanh", description="Tra cứu thông tin và lịch sử điểm danh của học sinh")
@app_commands.describe(hs="Mã học sinh hoặc tên cần tra cứu (để trống để xem danh sách gần nhất)")
async def slash_diemdanh(interaction: discord.Interaction, hs: str | None = None) -> None:
    await interaction.response.send_message(embed=_build_diemdanh_embed(hs))


@bot.tree.command(name="trangthai", description="Xem tình trạng hệ thống toàn diện (Backend, CSDL, Fail-Safe, ESP32)")
async def slash_trangthai(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(embed=_build_trangthai_embed())


@bot.tree.command(name="xoathe", description="Xóa đăng ký thẻ học sinh khỏi hệ thống")
@app_commands.describe(uid="Mã UID của thẻ cần xóa")
async def slash_xoathe(interaction: discord.Interaction, uid: str) -> None:
    await interaction.response.send_message(embed=_build_xoathe_embed(uid))


@bot.tree.command(name="panel", description="Mở bảng điều khiển tương tác trực quan")
async def slash_panel(interaction: discord.Interaction) -> None:
    embed = discord.Embed(title="Bảng Điều Khiển NFC", color=discord.Color.blurple())
    embed.description = "- Hướng dẫn: Chọn thao tác bên dưới để thực hiện nhanh"
    await interaction.response.send_message(embed=embed, view=RegistrationPanelView())


async def reader_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> list[app_commands.Choice[str]]:
    readers = get_active_esp32_readers()
    choices = [app_commands.Choice(name="Tất cả đầu đọc (all)", value="all")]
    for r in readers:
        dev_id = str(r.get("device_id", "ESP32"))
        ip = str(r.get("ip", ""))
        label = f"{dev_id} ({ip})"
        if current.lower() in label.lower() or current.lower() in dev_id.lower():
            choices.append(app_commands.Choice(name=label, value=dev_id))
    return choices[:25]


@bot.tree.command(name="cauhinh", description="Cấu hình động thông số cho đầu đọc ESP32 từ xa qua mạng TCP")
@app_commands.autocomplete(thiet_bi=reader_autocomplete)
@app_commands.describe(
    thiet_bi="ID đầu đọc (hoặc 'all' cho tất cả thiết bị đang kết nối)",
    cooldown_ms="Thời gian chờ giữa 2 lần quẹt thẻ (ms, ví dụ: 1500)",
    feedback_duration_ms="Thời lượng kêu còi & nháy LED phản hồi (ms, ví dụ: 300)",
    vi_tri="Vị trí đặt thiết bị (ví dụ: Phòng 10A1, Cổng chính)",
    khoi_dong_lai="Khởi động lại đầu đọc để áp dụng toàn diện (True/False)",
    wifi_ssid="Tên mạng Wi-Fi mới (nếu muốn chuyển mạng từ xa)",
    wifi_password="Mật khẩu Wi-Fi mới",
    server_host="Địa chỉ IP máy chủ backend mới",
    tcp_port="Cổng TCP máy chủ mới"
)
async def slash_cauhinh(
    interaction: discord.Interaction,
    thiet_bi: str,
    cooldown_ms: int | None = None,
    feedback_duration_ms: int | None = None,
    vi_tri: str | None = None,
    khoi_dong_lai: bool = False,
    wifi_ssid: str | None = None,
    wifi_password: str | None = None,
    server_host: str | None = None,
    tcp_port: int | None = None,
) -> None:
    cfg_payload: dict[str, Any] = {}
    details: list[str] = [f"- Thiết bị mục tiêu: **{thiet_bi}**"]

    if cooldown_ms is not None:
        if cooldown_ms < 200 or cooldown_ms > 60000:
            await interaction.response.send_message("❌ `cooldown_ms` không hợp lệ (hỗ trợ từ 200ms đến 60000ms).", ephemeral=True)
            return
        cfg_payload["cooldown_ms"] = cooldown_ms
        details.append(f"- Cooldown quét thẻ: `{cooldown_ms}` ms")

    if feedback_duration_ms is not None:
        if feedback_duration_ms < 50 or feedback_duration_ms > 5000:
            await interaction.response.send_message("❌ `feedback_duration_ms` không hợp lệ (hỗ trợ từ 50ms đến 5000ms).", ephemeral=True)
            return
        cfg_payload["feedback_duration_ms"] = feedback_duration_ms
        details.append(f"- Thời lượng phản hồi LED/Còi: `{feedback_duration_ms}` ms")

    if vi_tri is not None and vi_tri.strip():
        cfg_payload["location"] = vi_tri.strip()
        details.append(f"- Vị trí đặt máy: `{vi_tri.strip()}`")

    if wifi_ssid is not None and wifi_ssid.strip():
        cfg_payload["wifi_ssid"] = wifi_ssid.strip()
        cfg_payload["wifi_password"] = wifi_password or ""
        details.append(f"- Wi-Fi SSID mới: `{wifi_ssid.strip()}`")

    if server_host is not None and server_host.strip():
        cfg_payload["server_host"] = server_host.strip()
        details.append(f"- Server Host mới: `{server_host.strip()}`")

    if tcp_port is not None:
        cfg_payload["tcp_port"] = tcp_port
        details.append(f"- TCP Port mới: `{tcp_port}`")

    if khoi_dong_lai:
        cfg_payload["reboot"] = True
        details.append("- Khởi động lại sau cấu hình: `Có (Tự reboot sau 1s)`")

    if not cfg_payload:
        await interaction.response.send_message("⚠️ Bạn chưa chỉ định bất kỳ thông số nào để thay đổi.", ephemeral=True)
        return

    result = send_config_update(thiet_bi, cfg_payload)
    if result.get("success"):
        embed = discord.Embed(title="🚀 Đã Gửi Cấu Hình Xuống Đầu Đọc", color=discord.Color.blue())
        embed.description = "\n".join(details) + f"\n- Kết quả: {result.get('message', 'Thành công')}"
        embed.set_footer(text="Cấu hình được lưu tự động vào Flash NVS của ESP32")
    else:
        embed = discord.Embed(title="❌ Gửi Cấu Hình Thất Bại", color=discord.Color.red())
        embed.description = f"- Lí do: {result.get('message', 'Không thể kết nối tới đầu đọc')}"

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="khoidonglai", description="Khởi động lại (Reboot) đầu đọc ESP32 từ xa qua mạng TCP")
@app_commands.autocomplete(thiet_bi=reader_autocomplete)
@app_commands.describe(thiet_bi="ID đầu đọc cần khởi động lại (hoặc 'all')")
async def slash_khoidonglai(interaction: discord.Interaction, thiet_bi: str) -> None:
    result = send_reader_reboot(thiet_bi)
    if result.get("success"):
        embed = discord.Embed(title="🔄 Lệnh Khởi Động Lại Đã Được Gửi", color=discord.Color.gold())
        embed.description = (
            f"- Thiết bị: **{thiet_bi}**\n"
            f"- Kết quả: {result.get('message', 'Thành công')}\n"
            f"- Lưu ý: Đầu đọc sẽ mất kết nối trong khoảng 3-5 giây để nạp lại hệ thống."
        )
    else:
        embed = discord.Embed(title="❌ Khởi Động Lại Thất Bại", color=discord.Color.red())
        embed.description = f"- Lí do: {result.get('message', 'Không thể kết nối tới đầu đọc')}"

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="kenh", description="Thiết lập các kênh Discord chuyên biệt hoặc chu kỳ tự động cập nhật trạng thái")
@app_commands.describe(
    loai="Loại kênh cần thiết lập (status, noti, reg, info hoặc xem)",
    kenh="Kênh Discord muốn gán làm nơi nhận tin",
    chu_ky_phut="Chu kỳ tự động cập nhật bảng trạng thái ESP32 tính theo phút (0 để tắt)"
)
@app_commands.choices(loai=[
    app_commands.Choice(name="📡 Kênh Trạng Thái Thiết Bị & Watchdog (status)", value="status"),
    app_commands.Choice(name="🔔 Kênh Thông Báo Điểm Danh (noti)", value="noti"),
    app_commands.Choice(name="📝 Kênh Đăng Ký Thẻ Học Sinh (reg)", value="reg"),
    app_commands.Choice(name="ℹ️ Kênh Thông Tin & Tra Cứu (info)", value="info"),
    app_commands.Choice(name="📋 Xem Danh Sách Kênh Đang Cấu Hình (xem)", value="xem"),
])
async def slash_kenh(
    interaction: discord.Interaction,
    loai: str,
    kenh: discord.TextChannel | None = None,
    chu_ky_phut: int | None = None,
) -> None:
    all_channels = get_all_channel_ids()

    is_admin = False
    if interaction.user.guild_permissions.administrator:
        is_admin = True
    else:
        user_roles = [r.name for r in getattr(interaction.user, "roles", [])]
        from src.bots.config import get_admin_roles
        if any(r in get_admin_roles() for r in user_roles):
            is_admin = True

    if chu_ky_phut is not None and kenh is None and loai != "xem":
        if not is_admin:
            await interaction.response.send_message("❌ Bạn không có quyền quản trị để thay đổi cấu hình chu kỳ.", ephemeral=True)
            return
        set_status_interval_minutes(chu_ky_phut)
        embed = discord.Embed(title="⏱️ Cập Nhật Chu Kỳ Thành Công", color=discord.Color.green())
        embed.description = (
            f"- Chu kỳ tự động cập nhật trạng thái ESP32: **Mỗi {chu_ky_phut} phút**\n"
            f"- Bảng tin Live Dashboard sẽ tự động cập nhật vào kênh trạng thái đã thiết lập.\n"
            f"- Trạng thái: Đã lưu vĩnh viễn vào file cấu hình `bot_config.json`"
            if chu_ky_phut > 0 else
            "- Chu kỳ tự động cập nhật trạng thái ESP32: **Đã tắt**\n- Trạng thái: Đã lưu vĩnh viễn vào file cấu hình `bot_config.json`"
        )
        await interaction.response.send_message(embed=embed)
        return

    if loai == "xem" or (kenh is None and chu_ky_phut is None):
        def fmt_ch(ch_id: int | None) -> str:
            if not ch_id:
                return "*Chưa cấu hình (dùng kênh mặc định)*"
            ch = bot.get_channel(ch_id)
            return f"<#{ch_id}> (`{ch.name if ch else ch_id}`)"

        interval = get_status_interval_minutes()
        mode_str = "Live Dashboard (Sửa tin nhắn)" if get_status_update_mode() == "edit" else "Định kỳ (Gửi tin mới)"
        interval_desc = f"Mỗi `{interval}` phút ({mode_str})" if interval > 0 else "Đang tắt"

        embed = discord.Embed(title="📋 Cấu Hình Kênh Discord Hệ Thống", color=discord.Color.blurple())
        embed.description = (
            f"- 📡 **Kênh Trạng Thái Thiết Bị (`status`)**: {fmt_ch(all_channels.get('status'))}\n"
            f"- 🔔 **Kênh Thông Báo Điểm Danh (`noti`)**: {fmt_ch(all_channels.get('noti'))}\n"
            f"- 📝 **Kênh Đăng Ký Thẻ (`reg`)**: {fmt_ch(all_channels.get('reg'))}\n"
            f"- ℹ️ **Kênh Thông Tin Chung (`info`)**: {fmt_ch(all_channels.get('info'))}\n"
            f"- ⏱️ **Tự Động Cập Nhật Trạng Thái**: {interval_desc}\n\n"
            f"💡 *Để gán kênh, dùng:* `/kenh loai:[loai] kenh:[#kenh]`\n"
            f"💡 *Để đổi chu kỳ cập nhật, dùng:* `/kenh loai:status chu_ky_phut:[phút]`"
        )
        await interaction.response.send_message(embed=embed)
        return

    if not is_admin:
        await interaction.response.send_message("❌ Bạn không có quyền quản trị để thay đổi cấu hình kênh.", ephemeral=True)
        return

    success = False
    if kenh is not None:
        success = set_channel_id(loai, kenh.id)
    if chu_ky_phut is not None:
        set_status_interval_minutes(chu_ky_phut)
        success = True

    if success:
        type_names = {
            "status": "📡 Kênh Trạng Thái Thiết Bị & Watchdog",
            "noti": "🔔 Kênh Thông Báo Điểm Danh",
            "reg": "📝 Kênh Đăng Ký Thẻ Học Sinh",
            "info": "ℹ️ Kênh Thông Tin & Tra Cứu",
        }
        name_vi = type_names.get(loai, loai.upper())
        embed = discord.Embed(title="✅ Thiết Lập Thành Công", color=discord.Color.green())
        lines = [f"- Loại kênh: **{name_vi}**"]
        if kenh:
            lines.append(f"- Kênh được gán: <#{kenh.id}> (`{kenh.name}`)")
        if chu_ky_phut is not None:
            lines.append(f"- Chu kỳ cập nhật trạng thái: Mỗi {chu_ky_phut} phút" if chu_ky_phut > 0 else "- Chu kỳ cập nhật trạng thái: Đã tắt")
        lines.append("- Trạng thái: Đã lưu vĩnh viễn vào file cấu hình `bot_config.json`")
        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message(f"❌ Không thể lưu cấu hình cho loại kênh `{loai}`.", ephemeral=True)


@bot.command(name="help")
async def cmd_help(ctx: commands.Context) -> None:
    await ctx.send(embed=_build_help_embed())


@bot.command(name="dangky")
async def cmd_dangky(
    ctx: commands.Context,
    type_val: int = 1,
    ten_hs: str = "",
    lop: str = "Chưa phân lớp",
    uid: str | None = None,
) -> None:
    if not ten_hs:
        embed = discord.Embed(title="Hướng Dẫn Lệnh", color=discord.Color.blurple())
        embed.description = (
            "- Cú pháp: `!dangky <type> \"<tên hs>\" [lớp] [uid]`\n"
            "- Type 1: `!dangky 1 \"Nguyễn Văn An\" 12A1 E2801102`\n"
            "- Type 2: `!dangky 2 \"Nguyễn Văn An\" 12A1` (Quẹt thẻ trên đầu đọc)"
        )
        await ctx.send(embed=embed)
        return

    class_name = lop.strip() if lop else "Chưa phân lớp"
    name = ten_hs.strip()

    if type_val == 1:
        if not uid:
            embed = discord.Embed(title="Đăng Ký Thất Bại", color=discord.Color.red())
            embed.description = "Lí Do: Type 1 yêu cầu cung cấp mã UID (Ví dụ: `!dangky 1 \"Tên HS\" 12A1 UID`)"
            await ctx.send(embed=embed)
            return
        saved, _ = register_or_update_student(full_name=name, uid=uid.strip(), class_name=class_name)
        embed = discord.Embed(title="Đăng Ký Thành Công", color=discord.Color.green())
        embed.description = (
            f"- Tên học sinh: {saved['full_name']}\n"
            f"- Lớp: {saved['class_name']}\n"
            f"- UID: {saved['uid']}\n"
            f"- Phương thức: Trực tiếp (Bot)"
        )
        await ctx.send(embed=embed)
    elif type_val == 2:
        pending = get_pending_card()
        if pending:
            p_uid = pending["uid"]
            dev = pending.get("device_id", "ESP32")
            clear_pending_card()
            saved, _ = register_or_update_student(full_name=name, uid=p_uid, class_name=class_name)
            embed = discord.Embed(title="Đăng Ký Thành Công", color=discord.Color.green())
            embed.description = (
                f"- Tên học sinh: {saved['full_name']}\n"
                f"- Lớp: {saved['class_name']}\n"
                f"- UID: {saved['uid']}\n"
                f"- Thiết bị: {dev}"
            )
            await ctx.send(embed=embed)
        else:
            embed, view = _build_waiting_card_view(name, class_name)
            await ctx.send(embed=embed, view=view)


@bot.command(name="phanlop")
async def cmd_phanlop(ctx: commands.Context, hs: str, *, lop: str) -> None:
    updated = update_student_class(hs, lop)
    if updated:
        embed = discord.Embed(title="Phân Lớp Thành Công", color=discord.Color.green())
        embed.description = (
            f"- Tên học sinh: {updated['full_name']}\n"
            f"- Lớp: {updated['class_name']}\n"
            f"- UID: {updated['uid']}"
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(title="Phân Lớp Thất Bại", color=discord.Color.red())
        embed.description = f"Lí Do: Không tìm thấy học sinh với thông tin: {hs}"
        await ctx.send(embed=embed)


@bot.command(name="dangkythe")
async def cmd_dangkythe(ctx: commands.Context, hs: str, lop: str = "Chưa phân lớp") -> None:
    await cmd_dangky(ctx, type_val=2, ten_hs=hs, lop=lop)



@bot.command(name="ketnoi")
async def cmd_ketnoi(ctx: commands.Context) -> None:
    msg = await ctx.send("Đang kiểm tra kết nối thiết bị...")
    await msg.edit(content=None, embed=_build_ketnoi_embed(trigger_esp32_discovery()))


@bot.command(name="themoi", aliases=["lastcard"])
async def cmd_themoi(ctx: commands.Context) -> None:
    await ctx.send(embed=_build_themoi_embed())


@bot.command(name="diemdanh", aliases=["check"])
async def cmd_diemdanh(ctx: commands.Context, *, hs: str | None = None) -> None:
    await ctx.send(embed=_build_diemdanh_embed(hs))


@bot.command(name="trangthai", aliases=["stats"])
async def cmd_trangthai(ctx: commands.Context) -> None:
    await ctx.send(embed=_build_trangthai_embed())


@bot.command(name="xoathe", aliases=["del"])
async def cmd_xoathe(ctx: commands.Context, uid: str) -> None:
    await ctx.send(embed=_build_xoathe_embed(uid))


@bot.command(name="panel")
async def cmd_panel(ctx: commands.Context) -> None:
    embed = discord.Embed(title="Bảng Điều Khiển NFC", color=discord.Color.blurple())
    embed.description = "- Hướng dẫn: Chọn thao tác bên dưới để thực hiện nhanh"
    await ctx.send(embed=embed, view=RegistrationPanelView())


@bot.command(name="kenh", aliases=["channels", "channel"])
async def cmd_kenh(
    ctx: commands.Context,
    loai: str = "xem",
    kenh: discord.TextChannel | None = None,
    chu_ky_phut: int | None = None,
) -> None:
    norm_loai = loai.strip().lower()
    all_channels = get_all_channel_ids()

    if norm_loai.isdigit():
        chu_ky_phut = int(norm_loai)
        norm_loai = "chu_ky"

    is_admin = False
    if ctx.author.guild_permissions.administrator:
        is_admin = True
    else:
        user_roles = [r.name for r in getattr(ctx.author, "roles", [])]
        from src.bots.config import get_admin_roles
        if any(r in get_admin_roles() for r in user_roles):
            is_admin = True

    if norm_loai in ("chu_ky", "interval") or (chu_ky_phut is not None and kenh is None and norm_loai in ("xem", "list")):
        if not is_admin:
            await ctx.send("❌ Bạn không có quyền quản trị để thay đổi cấu hình chu kỳ.")
            return
        set_status_interval_minutes(chu_ky_phut)
        embed = discord.Embed(title="⏱️ Cập Nhật Chu Kỳ Thành Công", color=discord.Color.green())
        embed.description = (
            f"- Chu kỳ tự động cập nhật trạng thái ESP32: **Mỗi {chu_ky_phut} phút**\n"
            f"- Bảng tin Live Dashboard sẽ tự động cập nhật vào kênh trạng thái đã thiết lập.\n"
            f"- Trạng thái: Đã lưu vĩnh viễn vào file cấu hình `bot_config.json`"
            if chu_ky_phut > 0 else
            "- Chu kỳ tự động cập nhật trạng thái ESP32: **Đã tắt**\n- Trạng thái: Đã lưu vĩnh viễn vào file cấu hình `bot_config.json`"
        )
        await ctx.send(embed=embed)
        return

    if norm_loai in ("xem", "list", "show") or (kenh is None and chu_ky_phut is None):
        def fmt_ch(ch_id: int | None) -> str:
            if not ch_id:
                return "*Chưa cấu hình (dùng kênh mặc định)*"
            ch = bot.get_channel(ch_id)
            return f"<#{ch_id}> (`{ch.name if ch else ch_id}`)"

        interval = get_status_interval_minutes()
        mode_str = "Live Dashboard (Sửa tin nhắn)" if get_status_update_mode() == "edit" else "Định kỳ (Gửi tin mới)"
        interval_desc = f"Mỗi `{interval}` phút ({mode_str})" if interval > 0 else "Đang tắt"

        embed = discord.Embed(title="📋 Cấu Hình Kênh Discord Hệ Thống", color=discord.Color.blurple())
        embed.description = (
            f"- 📡 **Kênh Trạng Thái Thiết Bị (`status`)**: {fmt_ch(all_channels.get('status'))}\n"
            f"- 🔔 **Kênh Thông Báo Điểm Danh (`noti`)**: {fmt_ch(all_channels.get('noti'))}\n"
            f"- 📝 **Kênh Đăng Ký Thẻ (`reg`)**: {fmt_ch(all_channels.get('reg'))}\n"
            f"- ℹ️ **Kênh Thông Tin Chung (`info`)**: {fmt_ch(all_channels.get('info'))}\n"
            f"- ⏱️ **Tự Động Cập Nhật Trạng Thái**: {interval_desc}\n\n"
            f"💡 *Để thay đổi kênh, dùng:* `!kenh <status|noti|reg|info> #ten-kenh` hoặc `/kenh`\n"
            f"💡 *Để đổi chu kỳ cập nhật, dùng:* `!kenh chu_ky [số_phút]`"
        )
        await ctx.send(embed=embed)
        return

    if not is_admin:
        await ctx.send("❌ Bạn không có quyền quản trị để thay đổi cấu hình kênh.")
        return

    success = False
    if kenh is not None:
        success = set_channel_id(norm_loai, kenh.id)
    if chu_ky_phut is not None:
        set_status_interval_minutes(chu_ky_phut)
        success = True

    if success:
        type_names = {
            "status": "📡 Kênh Trạng Thái Thiết Bị & Watchdog",
            "noti": "🔔 Kênh Thông Báo Điểm Danh",
            "reg": "📝 Kênh Đăng Ký Thẻ Học Sinh",
            "info": "ℹ️ Kênh Thông Tin & Tra Cứu",
        }
        name_vi = type_names.get(norm_loai, norm_loai.upper())
        embed = discord.Embed(title="✅ Thiết Lập Kênh Thành Công", color=discord.Color.green())
        lines = [f"- Loại kênh: **{name_vi}**"]
        if kenh:
            lines.append(f"- Kênh được gán: <#{kenh.id}> (`{kenh.name}`)")
        if chu_ky_phut is not None:
            lines.append(f"- Chu kỳ cập nhật trạng thái: Mỗi {chu_ky_phut} phút" if chu_ky_phut > 0 else "- Chu kỳ cập nhật trạng thái: Đã tắt")
        lines.append("- Trạng thái: Đã lưu vĩnh viễn vào file cấu hình `bot_config.json`")
        embed.description = "\n".join(lines)
        await ctx.send(embed=embed)
    else:
        await ctx.send(f"❌ Không thể lưu cấu hình cho loại kênh `{loai}`. Loại hợp lệ: `status`, `noti`, `reg`, `info`.")


@bot.command(name="khoidonglai", aliases=["reboot"])
async def cmd_khoidonglai(ctx: commands.Context, thiet_bi: str = "all") -> None:
    result = send_reader_reboot(thiet_bi)
    if result.get("success"):
        embed = discord.Embed(title="🔄 Lệnh Khởi Động Lại Đã Được Gửi", color=discord.Color.gold())
        embed.description = (
            f"- Thiết bị: **{thiet_bi}**\n"
            f"- Kết quả: {result.get('message', 'Thành công')}\n"
            f"- Lưu ý: Đầu đọc sẽ mất kết nối trong khoảng 3-5 giây để nạp lại hệ thống."
        )
    else:
        embed = discord.Embed(title="❌ Khởi Động Lại Thất Bại", color=discord.Color.red())
        embed.description = f"- Lí do: {result.get('message', 'Không thể kết nối tới đầu đọc')}"
    await ctx.send(embed=embed)


@bot.command(name="cauhinh", aliases=["config"])
async def cmd_cauhinh(
    ctx: commands.Context,
    thiet_bi: str = "all",
    cooldown_ms: int | None = None,
    coi_bao_ms: int | None = None,
    vi_tri: str | None = None,
) -> None:
    updates: dict[str, Any] = {}
    if cooldown_ms is not None:
        updates["cooldown_ms"] = cooldown_ms
    if coi_bao_ms is not None:
        updates["feedback_duration_ms"] = coi_bao_ms
    if vi_tri is not None:
        updates["location"] = vi_tri.strip()

    if not updates:
        embed = discord.Embed(title="⚙️ Hướng Dẫn Cấu Hình Đầu Đọc", color=discord.Color.blurple())
        embed.description = (
            "- Cú pháp: `!cauhinh [thiết bị / all] [cooldown_ms] [còi_báo_ms] [vị trí]`\n"
            "- Ví dụ: `!cauhinh all 2000 150 \"Cong Chinh\"`\n"
            "💡 *Mẹo: Dùng Slash Command* `/cauhinh` *để có giao diện gợi ý tham số trực quan hơn!*"
        )
        await ctx.send(embed=embed)
        return

    result = send_config_update(thiet_bi, updates)
    if result.get("success"):
        embed = discord.Embed(title="⚙️ Lệnh Cấu Hình Đã Được Gửi", color=discord.Color.blue())
        lines = [f"- Thiết bị nhận lệnh: **{thiet_bi}**", f"- Trạng thái: {result.get('message', 'Đã chuyển tiếp lệnh')}"]
        if "cooldown_ms" in updates:
            lines.append(f"- Thời gian giãn cách quẹt thẻ: {updates['cooldown_ms']} ms")
        if "feedback_duration_ms" in updates:
            lines.append(f"- Thời gian bíp còi / LED: {updates['feedback_duration_ms']} ms")
        if "location" in updates:
            lines.append(f"- Vị trí đặt đầu đọc: {updates['location']}")
        lines.append("- Đầu đọc sẽ tự động lưu vào bộ nhớ NVS và áp dụng ngay lập tức.")
        embed.description = "\n".join(lines)
    else:
        embed = discord.Embed(title="❌ Cấu Hình Thất Bại", color=discord.Color.red())
        embed.description = f"- Lí do: {result.get('message', 'Không thể kết nối tới đầu đọc')}"
    await ctx.send(embed=embed)





def _safe_enqueue(event: dict[str, Any]) -> None:
    if _event_queue is not None:
        try:
            _event_queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("Discord event queue is full (500 items), dropping event")


def _on_scan_event(event: dict[str, Any]) -> None:
    global _bot_loop, _event_queue
    if not is_notifications_enabled():
        return
    if _bot_loop and _event_queue and _bot_loop.is_running():
        _bot_loop.call_soon_threadsafe(_safe_enqueue, event)


register_attendance_hook(_on_scan_event)


async def _send_with_ratelimit(
    channel: Any,
    embed: discord.Embed,
    last_send_time: float,
    min_interval: float = 1.0,
) -> float:
    if not channel:
        return last_send_time
    now = asyncio.get_running_loop().time()
    wait_time = (last_send_time + min_interval) - now
    if wait_time > 0:
        await asyncio.sleep(wait_time)

    try:
        await channel.send(embed=embed)
    except discord.HTTPException as e:
        if e.status == 429:
            retry_after = getattr(e, "retry_after", 2.5)
            logger.warning(f"Discord rate limit 429 hit! Waiting {retry_after:.2f}s to retry...")
            await asyncio.sleep(retry_after + 0.2)
            try:
                await channel.send(embed=embed)
            except Exception as err:
                logger.error(f"Failed to send embed after 429 retry: {err}")
        else:
            logger.warning(f"Discord HTTP exception {e.status}: {e}")
    except Exception as e:
        logger.warning(f"Error sending embed: {e}")

    return asyncio.get_running_loop().time()


def _format_event_time(ts: Any) -> str:
    if not ts:
        return datetime.now().strftime("%H:%M:%S %d/%m/%Y")
    try:
        if isinstance(ts, str):
            clean_ts = ts.split(".")[0].replace("Z", "")
            if "T" in clean_ts:
                dt = datetime.fromisoformat(ts)
                return dt.strftime("%H:%M:%S %d/%m/%Y")
            return ts
    except Exception:
        pass
    return datetime.now().strftime("%H:%M:%S %d/%m/%Y")


async def _resolve_channel(channel_id: int | None) -> discord.TextChannel | None:
    if not channel_id:
        return None
    ch = bot.get_channel(channel_id)
    if not ch:
        try:
            ch = await bot.fetch_channel(channel_id)
        except Exception:
            return None
    return ch


async def _attendance_event_worker() -> None:
    if not is_notifications_enabled():
        return

    global _recent_unknown_cards, _recent_notified_students
    last_send_time = 0.0

    while True:
        try:
            if not _event_queue:
                await asyncio.sleep(1)
                continue

            noti_channel = await _resolve_channel(get_noti_channel_id())
            status_channel = (await _resolve_channel(get_status_channel_id())) or noti_channel
            reg_channel = (await _resolve_channel(get_reg_channel_id())) or noti_channel

            if not noti_channel and not status_channel and not reg_channel:
                await asyncio.sleep(2)
                continue

            first_event = await _event_queue.get()
            batch = [first_event]

            deadline = asyncio.get_running_loop().time() + 1.0
            while len(batch) < 10:
                timeout = deadline - asyncio.get_running_loop().time()
                if timeout <= 0:
                    break
                try:
                    next_event = await asyncio.wait_for(_event_queue.get(), timeout=timeout)
                    batch.append(next_event)
                except asyncio.TimeoutError:
                    break

            # Xử lý sự kiện trạng thái thiết bị (Online / Offline cảnh báo tắt máy)
            device_events = [e for e in batch if e.get("event_type") == "DEVICE_STATUS"]
            for dev_ev in device_events:
                dev_status = dev_ev.get("status")
                device_id = dev_ev.get("device_id", "ESP32")
                ip = dev_ev.get("ip", "N/A")
                time_str = _format_event_time(dev_ev.get("timestamp"))

                if dev_status == "DEVICE_OFFLINE":
                    reason = dev_ev.get("reason", "Mất kết nối máy chủ")
                    uptime = dev_ev.get("uptime_s")
                    lines = [
                        f"- Thiết Bị: {device_id}",
                        f"- Địa Chỉ IP: {ip}",
                        f"- Tình Trạng: Mất kết nối / Nghi vấn bị rút điện hoặc tắt máy",
                        f"- Lí Do: {reason}",
                        f"- Thời Gian: {time_str}",
                    ]
                    if uptime is not None:
                        h = uptime // 3600
                        m = (uptime % 3600) // 60
                        s = uptime % 60
                        uptime_str = f"{h}h {m}m {s}s" if h > 0 else f"{m}m {s}s"
                        lines.append(f"- Uptime trước khi tắt: {uptime_str}")

                    embed = discord.Embed(title="⚠️ Cảnh Báo: Đầu Đọc Mất Tín Hiệu", color=discord.Color.red())
                    embed.description = "\n".join(lines)
                    last_send_time = await _send_with_ratelimit(status_channel, embed, last_send_time)

                elif dev_status == "DEVICE_ONLINE":
                    lines = [
                        f"- Thiết Bị: {device_id}",
                        f"- Địa Chỉ IP: {ip}",
                        f"- Trạng Thái: Trực tuyến (Sẵn sàng nhận thẻ)",
                        f"- Thời Gian: {time_str}",
                    ]
                    rssi = dev_ev.get("rssi")
                    if rssi is not None and rssi != 0 and rssi != -100:
                        lines.append(f"- Sóng Wi-Fi: {rssi} dBm")
                    embed = discord.Embed(title="✅ Đầu Đọc Đã Hoạt Động Trở Lại", color=discord.Color.green())
                    embed.description = "\n".join(lines)
                    last_send_time = await _send_with_ratelimit(status_channel, embed, last_send_time)

            # Xử lý phản hồi lệnh từ đầu đọc (Config ACK / Reboot ACK)
            cmd_ack_events = [e for e in batch if e.get("action") in ("config_ack", "reboot_ack")]
            for ack_ev in cmd_ack_events:
                action = ack_ev.get("action")
                dev_id = ack_ev.get("device_id", "ESP32")
                data = ack_ev.get("data", {})
                time_str = _format_event_time(ack_ev.get("timestamp"))

                if action == "config_ack":
                    lines = [
                        f"- Đầu đọc: **{dev_id}**",
                        "- Trạng thái: ✅ Cấu hình đã được lưu vĩnh viễn vào Flash NVS",
                    ]
                    if "cooldown_ms" in data:
                        lines.append(f"- Cooldown quét thẻ: `{data['cooldown_ms']}` ms")
                    if "feedback_duration_ms" in data:
                        lines.append(f"- Thời lượng phản hồi: `{data['feedback_duration_ms']}` ms")
                    if data.get("location"):
                        lines.append(f"- Vị trí: `{data['location']}`")
                    lines.append(f"- Thời gian: {time_str}")

                    embed = discord.Embed(title="⚙️ Đầu Đọc Đã Lưu & Áp Dụng Cấu Hình", color=discord.Color.blue())
                    embed.description = "\n".join(lines)
                    last_send_time = await _send_with_ratelimit(status_channel, embed, last_send_time)

                elif action == "reboot_ack":
                    lines = [
                        f"- Đầu đọc: **{dev_id}**",
                        "- Trạng thái: 🔄 Đang thực hiện chu trình khởi động lại hệ thống...",
                        f"- Thời gian: {time_str}",
                    ]
                    embed = discord.Embed(title="🔄 Đầu Đọc Đang Khởi Động Lại", color=discord.Color.gold())
                    embed.description = "\n".join(lines)
                    last_send_time = await _send_with_ratelimit(status_channel, embed, last_send_time)

            success_events = [e for e in batch if e.get("status") == "SUCCESS" and e.get("student")]
            unknown_events = [e for e in batch if e.get("status") == "UNKNOWN_CARD" and e.get("uid")]

            realtime_raw = [e for e in success_events if not e.get("is_offline")]
            offline_raw = [e for e in success_events if e.get("is_offline")]

            now_loop = asyncio.get_running_loop().time()

            realtime_events = []
            seen_realtime_uids = set()
            for ev in realtime_raw:
                uid = ev.get("uid")
                if not uid or uid in seen_realtime_uids:
                    continue
                seen_realtime_uids.add(uid)

                last_time = _recent_notified_students.get(uid, 0.0)
                if now_loop - last_time < 15.0:
                    continue

                _recent_notified_students[uid] = now_loop
                realtime_events.append(ev)

            if len(_recent_notified_students) > 500:
                _recent_notified_students = {k: v for k, v in _recent_notified_students.items() if now_loop - v < 60.0}

            offline_events = []
            seen_offline_uids = set()
            for ev in offline_raw:
                uid = ev.get("uid")
                if not uid or uid in seen_offline_uids:
                    continue
                seen_offline_uids.add(uid)
                offline_events.append(ev)

            if realtime_events:

                if len(realtime_events) == 1:
                    ev = realtime_events[0]
                    student = ev.get("student", {})
                    name = student.get("full_name", "N/A")
                    cls = student.get("class_name") or "Chưa phân lớp"
                    uid = ev.get("uid", "N/A")
                    time_str = _format_event_time(ev.get("timestamp"))

                    embed = discord.Embed(title="Điểm Danh Thành Công", color=discord.Color.green())
                    embed.description = (
                        f"- Tên học sinh: {name}\n"
                        f"- Lớp: {cls}\n"
                        f"- Thời Gian: {time_str}\n"
                        f"- UID: {uid}"
                    )
                    last_send_time = await _send_with_ratelimit(noti_channel, embed, last_send_time)
                else:
                    embed = discord.Embed(
                        title=f"Điểm Danh Thành Công ({len(realtime_events)} học sinh)",
                        color=discord.Color.green(),
                    )
                    lines = []
                    for ev in realtime_events[:15]:
                        student = ev.get("student", {})
                        name = student.get("full_name", "N/A")
                        cls = student.get("class_name") or "Chưa phân lớp"
                        uid = ev.get("uid", "N/A")
                        time_str = _format_event_time(ev.get("timestamp"))
                        lines.append(f"• **{name}** ({cls}) - {time_str} (UID: `{uid}`)")
                    if len(realtime_events) > 15:
                        lines.append(f"... và {len(realtime_events) - 15} học sinh khác")
                    embed.description = "\n".join(lines)
                    last_send_time = await _send_with_ratelimit(noti_channel, embed, last_send_time)

            if offline_events:
                if len(offline_events) == 1:
                    ev = offline_events[0]
                    student = ev.get("student", {})
                    name = student.get("full_name", "N/A")
                    cls = student.get("class_name") or "Chưa phân lớp"
                    uid = ev.get("uid", "N/A")
                    time_str = _format_event_time(ev.get("timestamp"))

                    embed = discord.Embed(title="Điểm Danh Thành Công", color=discord.Color.teal())
                    embed.description = (
                        f"- Tên học sinh: {name}\n"
                        f"- Lớp: {cls}\n"
                        f"- Thời Gian: {time_str}\n"
                        f"- UID: {uid}"
                    )
                    last_send_time = await _send_with_ratelimit(noti_channel, embed, last_send_time)
                else:
                    embed = discord.Embed(
                        title=f"Điểm Danh Thành Công ({len(offline_events)} học sinh ngoại tuyến)",
                        color=discord.Color.teal(),
                    )
                    lines = []
                    for ev in offline_events[:15]:
                        student = ev.get("student", {})
                        name = student.get("full_name", "N/A")
                        cls = student.get("class_name") or "Chưa phân lớp"
                        uid = ev.get("uid", "N/A")
                        time_str = _format_event_time(ev.get("timestamp"))
                        lines.append(f"• **{name}** ({cls}) - {time_str} (UID: `{uid}`)")
                    if len(offline_events) > 15:
                        lines.append(f"... và {len(offline_events) - 15} học sinh khác")
                    embed.description = "\n".join(lines)
                    last_send_time = await _send_with_ratelimit(noti_channel, embed, last_send_time)

            if unknown_events:
                now_loop = asyncio.get_running_loop().time()
                filtered_unknowns = []
                for ev in unknown_events:
                    uid = ev.get("uid")
                    if not uid:
                        continue
                    if now_loop - _recent_unknown_cards.get(uid, 0.0) < 10.0:
                        continue
                    _recent_unknown_cards[uid] = now_loop
                    filtered_unknowns.append(ev)

                if len(_recent_unknown_cards) > 100:
                    _recent_unknown_cards = {k: v for k, v in _recent_unknown_cards.items() if now_loop - v < 60.0}

                if len(filtered_unknowns) == 1:
                    ev = filtered_unknowns[0]
                    uid = ev.get("uid", "N/A")
                    embed = discord.Embed(title="Điểm Danh Thất Bại", color=discord.Color.red())
                    embed.description = f"Lí Do: Thẻ chưa đăng ký (UID: `{uid}`)"
                    last_send_time = await _send_with_ratelimit(reg_channel, embed, last_send_time)
                elif len(filtered_unknowns) > 1:
                    embed = discord.Embed(title="Điểm Danh Thất Bại", color=discord.Color.red())
                    uids = ", ".join([f"`{e.get('uid')}`" for e in filtered_unknowns[:10]])
                    embed.description = f"Lí Do: {len(filtered_unknowns)} thẻ chưa đăng ký ({uids})"
                    last_send_time = await _send_with_ratelimit(reg_channel, embed, last_send_time)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Error broadcasting event: {e}")
            await asyncio.sleep(1)


async def _status_periodic_worker() -> None:
    await bot.wait_until_ready()
    # Chờ 5 giây sau khi bot kết nối để các đầu đọc ESP32 hoàn tất kết nối socket
    await asyncio.sleep(5)

    while not bot.is_closed():
        try:
            interval_min = get_status_interval_minutes()
            if interval_min <= 0:
                await asyncio.sleep(15)
                continue

            status_channel = (await _resolve_channel(get_status_channel_id())) or (await _resolve_channel(get_noti_channel_id()))
            if status_channel:
                embed = _build_esp32_status_embed(interval_min)
                mode = get_status_update_mode()
                msg_id = get_status_message_id()

                if mode == "edit" and msg_id:
                    try:
                        msg = await status_channel.fetch_message(msg_id)
                        await msg.edit(embed=embed)
                    except discord.NotFound:
                        new_msg = await status_channel.send(embed=embed)
                        set_status_message_id(new_msg.id)
                    except Exception as e:
                        logger.warning(f"Could not edit periodic status message: {e}")
                        new_msg = await status_channel.send(embed=embed)
                        set_status_message_id(new_msg.id)
                elif mode == "edit" and not msg_id:
                    new_msg = await status_channel.send(embed=embed)
                    set_status_message_id(new_msg.id)
                else:
                    await status_channel.send(embed=embed)

            total_sleep = interval_min * 60
            elapsed = 0
            while elapsed < total_sleep:
                if bot.is_closed():
                    break
                await asyncio.sleep(5)
                elapsed += 5
                new_interval = get_status_interval_minutes()
                if new_interval != interval_min:
                    break
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in status periodic worker: {e}", exc_info=True)
            await asyncio.sleep(15)


async def start_discord_bot() -> None:
    token = get_discord_token()
    if not token:
        logger.warning("No token provided in bot_config.json or DISCORD_BOT_TOKEN. Bot will not start.")
        return

    try:
        await bot.start(token)
    except Exception as e:
        logger.error(f"Failed to run Discord bot: {e}")


def main() -> None:
    token = get_discord_token()
    if not token:
        print("ERROR: Discord bot token is missing in bot_config.json.")
        return
    bot.run(token)


if __name__ == "__main__":
    main()
