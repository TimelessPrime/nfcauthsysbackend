from typing import Any
import discord
from discord import ui

from src.bots.config import (
    get_all_channel_ids,
    get_status_interval_minutes,
    get_status_update_mode,
)
from src.bots.connector import (
    clear_pending_card,
    get_active_esp32_readers,
    get_pending_card,
    send_config_update,
    trigger_esp32_discovery,
)
from src.bots.database import register_or_update_student, update_student_class
from src.bots.embeds import build_ketnoi_embed, build_trangthai_embed


class RegisterType1Modal(ui.Modal, title="Đăng ký học sinh - Nhập UID (Type 1)"):
    name_input = ui.TextInput(label="Họ và tên", placeholder="Ví dụ: Nguyễn Văn An", min_length=2, max_length=50)
    class_input = ui.TextInput(label="Lớp học", placeholder="Ví dụ: 12A1", min_length=1, max_length=20)
    uid_input = ui.TextInput(label="Mã UID thẻ", placeholder="Ví dụ: E2801102", min_length=4, max_length=32)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        clean_uid = self.uid_input.value.strip().upper()
        name = self.name_input.value.strip()
        cls = self.class_input.value.strip() or "Chưa phân lớp"

        if len(clean_uid) < 4:
            fail_embed = discord.Embed(title="Đăng ký không thành công", color=discord.Color.red())
            fail_embed.description = "Lí do: Mã UID không hợp lệ (tối thiểu 4 ký tự hex)."
            await interaction.response.send_message(embed=fail_embed)
            return

        saved, _ = register_or_update_student(full_name=name, uid=clean_uid, class_name=cls)
        embed = discord.Embed(title="Đăng ký thành công", color=discord.Color.green())
        embed.description = (
            f"- Họ và tên: {saved['full_name']}\n"
            f"- Lớp: {saved['class_name']}\n"
            f"- UID: `{saved['uid']}`\n"
            f"- Phương thức: Nhập trực tiếp"
        )
        await interaction.response.send_message(embed=embed)


class RegisterType2Modal(ui.Modal, title="Đăng ký học sinh - Quẹt thẻ (Type 2)"):
    name_input = ui.TextInput(label="Họ và tên", placeholder="Ví dụ: Nguyễn Văn An", min_length=2, max_length=50)
    class_input = ui.TextInput(label="Lớp học", placeholder="Ví dụ: 12A1", min_length=1, max_length=20)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        name = self.name_input.value.strip()
        cls = self.class_input.value.strip() or "Chưa phân lớp"

        pending = get_pending_card()
        if pending:
            p_uid = pending["uid"]
            dev = pending.get("device_id", "ESP32")
            clear_pending_card()
            saved, _ = register_or_update_student(full_name=name, uid=p_uid, class_name=cls)
            embed = discord.Embed(title="Đăng ký thành công", color=discord.Color.green())
            embed.description = (
                f"- Họ và tên: {saved['full_name']}\n"
                f"- Lớp: {saved['class_name']}\n"
                f"- UID: `{saved['uid']}`\n"
                f"- Đầu đọc ghi nhận: {dev}"
            )
            await interaction.response.send_message(embed=embed)
        else:
            embed, view = build_waiting_card_view(name, cls)
            await interaction.response.send_message(embed=embed, view=view)


class PhanLopModal(ui.Modal, title="Phân lớp học sinh"):
    hs_input = ui.TextInput(
        label="Tên học sinh, Mã HS hoặc UID",
        placeholder="Ví dụ: Nguyễn Văn An hoặc HS001",
        min_length=2,
        max_length=50,
    )
    class_input = ui.TextInput(label="Lớp mới", placeholder="Ví dụ: 12A1", min_length=1, max_length=20)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        updated = update_student_class(self.hs_input.value.strip(), self.class_input.value.strip())
        if updated:
            embed = discord.Embed(title="Phân lớp thành công", color=discord.Color.green())
            embed.description = (
                f"- Họ và tên: {updated['full_name']}\n"
                f"- Lớp: {updated['class_name']}\n"
                f"- UID: `{updated['uid']}`"
            )
            await interaction.response.send_message(embed=embed)
        else:
            embed = discord.Embed(title="Phân lớp không thành công", color=discord.Color.red())
            embed.description = f"Lí do: Không tìm thấy học sinh: {self.hs_input.value.strip()}"
            await interaction.response.send_message(embed=embed)


def build_waiting_card_view(ten_hs: str, lop: str) -> tuple[discord.Embed, ui.View]:
    readers = get_active_esp32_readers()
    dev_str = readers[0]["device_id"] if readers else "Chưa có thiết bị kết nối"

    embed = discord.Embed(title="Chờ quẹt thẻ", color=discord.Color.gold())
    embed.description = (
        f"- Học sinh: {ten_hs}\n"
        f"- Lớp: {lop}\n"
        f"- Thiết bị: {dev_str}\n"
        f"- Hướng dẫn: Quẹt thẻ vào đầu đọc ESP32, sau đó nhấn nút xác nhận bên dưới."
    )

    view = ui.View(timeout=120)
    btn = ui.Button(label="Xác nhận thẻ vừa quẹt", style=discord.ButtonStyle.primary)

    async def _btn_callback(interaction: discord.Interaction) -> None:
        new_pending = get_pending_card()
        if not new_pending:
            fail_embed = discord.Embed(title="Đăng ký không thành công", color=discord.Color.red())
            fail_embed.description = "Lí do: Chưa phát hiện thẻ mới trên đầu đọc. Vui lòng quẹt thẻ trước khi bấm nút."
            await interaction.response.send_message(embed=fail_embed, ephemeral=True)
            return

        p_uid = new_pending["uid"]
        dev = new_pending.get("device_id", "ESP32")
        clear_pending_card()
        saved, _ = register_or_update_student(full_name=ten_hs, uid=p_uid, class_name=lop)
        success_embed = discord.Embed(title="Đăng ký thành công", color=discord.Color.green())
        success_embed.description = (
            f"- Họ và tên: {saved['full_name']}\n"
            f"- Lớp: {saved['class_name']}\n"
            f"- UID: `{saved['uid']}`\n"
            f"- Đầu đọc ghi nhận: {dev}"
        )
        await interaction.response.edit_message(embed=success_embed, view=None)

    btn.callback = _btn_callback
    view.add_item(btn)
    return embed, view


class QuickConfigReaderModal(ui.Modal, title="Cấu hình đầu đọc ESP32"):
    device_id_input = ui.TextInput(
        label="ID đầu đọc (hoặc 'all')",
        placeholder="Ví dụ: READER_01 hoặc all",
        min_length=1,
        max_length=50,
    )
    cooldown_input = ui.TextInput(label="Cooldown quẹt thẻ (ms)", placeholder="Mặc định: 1000", required=False, max_length=6)
    feedback_input = ui.TextInput(label="Thời lượng còi & LED (ms)", placeholder="Mặc định: 200", required=False, max_length=6)
    location_input = ui.TextInput(label="Vị trí đặt máy", placeholder="Ví dụ: Cổng chính", required=False, max_length=50)

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
            await interaction.response.send_message("Không có thông số nào được nhập để thay đổi.", ephemeral=True)
            return

        res = send_config_update(target, payload)
        if res.get("success"):
            embed = discord.Embed(title="Cập nhật cấu hình thành công", color=discord.Color.blue())
            lines = [f"- Thiết bị: **{target}**", f"- Trạng thái: {res.get('message', 'Đã chuyển lệnh')}"]
            if "cooldown_ms" in payload:
                lines.append(f"- Cooldown: {payload['cooldown_ms']} ms")
            if "feedback_duration_ms" in payload:
                lines.append(f"- Phản hồi: {payload['feedback_duration_ms']} ms")
            if "location" in payload:
                lines.append(f"- Vị trí: {payload['location']}")
            embed.description = "\n".join(lines)
            await interaction.response.send_message(embed=embed)
        else:
            embed = discord.Embed(title="Cập nhật cấu hình không thành công", color=discord.Color.red())
            embed.description = f"- Lí do: {res.get('message', 'Không thể kết nối tới đầu đọc')}"
            await interaction.response.send_message(embed=embed, ephemeral=True)


class RegistrationPanelView(ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @ui.button(label="Quẹt thẻ (Type 2)", style=discord.ButtonStyle.primary)
    async def btn_type2_reg(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await interaction.response.send_modal(RegisterType2Modal())

    @ui.button(label="Nhập UID (Type 1)", style=discord.ButtonStyle.secondary)
    async def btn_type1_reg(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await interaction.response.send_modal(RegisterType1Modal())

    @ui.button(label="Phân lớp", style=discord.ButtonStyle.primary)
    async def btn_phanlop(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await interaction.response.send_modal(PhanLopModal())

    @ui.button(label="Cấu hình đầu đọc", style=discord.ButtonStyle.secondary)
    async def btn_config(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await interaction.response.send_modal(QuickConfigReaderModal())

    @ui.button(label="Quét thiết bị", style=discord.ButtonStyle.secondary)
    async def btn_connect(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(embed=build_ketnoi_embed(trigger_esp32_discovery()), ephemeral=True)

    @ui.button(label="Trạng thái", style=discord.ButtonStyle.success)
    async def btn_stats(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await interaction.response.send_message(embed=build_trangthai_embed(), ephemeral=True)

    @ui.button(label="Kênh hệ thống", style=discord.ButtonStyle.secondary)
    async def btn_channels(self, interaction: discord.Interaction, _: ui.Button) -> None:
        from src.bots.bot import bot
        all_channels = get_all_channel_ids()

        def fmt_ch(ch_id: int | None) -> str:
            if not ch_id:
                return "*Chưa cấu hình (dùng kênh mặc định)*"
            ch = bot.get_channel(ch_id)
            return f"<#{ch_id}> (`{ch.name if ch else ch_id}`)"

        interval = get_status_interval_minutes()
        mode_str = "Live Dashboard" if get_status_update_mode() == "edit" else "Gửi tin mới"
        interval_desc = f"Mỗi {interval} phút ({mode_str})" if interval > 0 else "Đang tắt"

        embed = discord.Embed(title="Cấu hình kênh hệ thống", color=discord.Color.blurple())
        embed.description = (
            f"- Kênh trạng thái (`status`): {fmt_ch(all_channels.get('status'))}\n"
            f"- Kênh thông báo điểm danh (`noti`): {fmt_ch(all_channels.get('noti'))}\n"
            f"- Kênh đăng ký thẻ (`reg`): {fmt_ch(all_channels.get('reg'))}\n"
            f"- Kênh thông tin chung (`info`): {fmt_ch(all_channels.get('info'))}\n"
            f"- Tự động cập nhật trạng thái: {interval_desc}"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
