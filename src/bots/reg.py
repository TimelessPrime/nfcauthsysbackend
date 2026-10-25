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
    is_notifications_enabled,
    is_sync_slash_commands,
)
from src.bots.connector import (
    get_active_esp32_readers,
    get_pending_card,
    register_attendance_hook,
    trigger_esp32_discovery,
)
from src.bots.database import (
    delete_card,
    find_student,
    get_or_create_blank_student,
    get_recent_logs,
    get_stats,
    register_student_card,
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
_recent_unknown_cards: dict[str, float] = {}


class ManualRegisterModal(ui.Modal, title="Đăng ký Thẻ NFC Học Sinh"):
    uid_input = ui.TextInput(label="Mã UID Thẻ (Hex)", placeholder="Ví dụ: E2801102", min_length=4, max_length=32)
    student_id_input = ui.TextInput(label="Mã Học Sinh", placeholder="Ví dụ: HS0123", min_length=2, max_length=20)
    name_input = ui.TextInput(label="Họ và Tên", placeholder="Ví dụ: Nguyễn Văn An", min_length=2, max_length=50)
    class_input = ui.TextInput(label="Lớp", placeholder="Ví dụ: 12A1", min_length=1, max_length=20)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        saved = register_student_card(
            self.uid_input.value.strip(),
            self.student_id_input.value.strip(),
            self.name_input.value.strip(),
            self.class_input.value.strip(),
        )
        embed = discord.Embed(
            color=discord.Color.green(),
            description=f"✅ Đã đăng ký thẻ `{saved['uid']}` cho **{saved['full_name']}** ({saved['class_name']}) • `{saved['student_id']}`",
            timestamp=datetime.now(),
        )
        await interaction.response.send_message(embed=embed)


class TapToBindModal(ui.Modal, title="Gán thẻ vừa quẹt"):
    student_id_input = ui.TextInput(label="Mã học sinh", placeholder="Ví dụ: HS0123", min_length=2, max_length=20)
    name_input = ui.TextInput(label="Họ và tên", placeholder="Ví dụ: Trần Thị Bình", min_length=2, max_length=50)
    class_input = ui.TextInput(label="Lớp", placeholder="Ví dụ: 11B2", min_length=1, max_length=20)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        pending = get_pending_card()
        if not pending:
            await interaction.response.send_message("Chưa có thẻ nào vừa quẹt tại đầu đọc.", ephemeral=True)
            return

        saved = register_student_card(
            pending["uid"],
            self.student_id_input.value.strip(),
            self.name_input.value.strip(),
            self.class_input.value.strip(),
        )
        embed = discord.Embed(
            color=discord.Color.green(),
            description=f"✅ Đã gán thẻ `{saved['uid']}` cho **{saved['full_name']}** ({saved['class_name']}) • `{saved['student_id']}`\n📍 {pending.get('device_id', 'ESP32')}",
            timestamp=datetime.now(),
        )
        await interaction.response.send_message(embed=embed)


class RegistrationPanelView(ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @ui.button(label="Gán thẻ vừa quẹt", style=discord.ButtonStyle.primary, emoji="⚡")
    async def btn_tap_bind(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await interaction.response.send_modal(TapToBindModal())

    @ui.button(label="Đăng ký thủ công", style=discord.ButtonStyle.secondary, emoji="📝")
    async def btn_manual_reg(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await interaction.response.send_modal(ManualRegisterModal())

    @ui.button(label="Quét thiết bị", style=discord.ButtonStyle.primary, emoji="📡")
    async def btn_connect(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(embed=_build_ketnoi_embed(trigger_esp32_discovery()), ephemeral=True)

    @ui.button(label="Thống kê", style=discord.ButtonStyle.success, emoji="📊")
    async def btn_stats(self, interaction: discord.Interaction, _: ui.Button) -> None:
        await interaction.response.send_message(embed=_build_trangthai_embed(), ephemeral=True)


def _build_ketnoi_embed(report: dict[str, Any]) -> discord.Embed:
    connected = report.get("connected_devices", [])
    discovered = report.get("discovered_lan_devices", [])
    backend_ip = report.get("backend_ip", "127.0.0.1")
    tcp_port = report.get("tcp_port", 1337)

    color = discord.Color.green() if connected else discord.Color.orange()
    embed = discord.Embed(title="Kết nối đầu đọc", color=color, timestamp=datetime.now())

    lines = [f"**Cổng TCP:** `{backend_ip}:{tcp_port}`"]
    if connected:
        lines.append("\n**Đầu đọc online:**")
        for c in connected:
            auth = "✓" if c.get("authenticated") else "⏳"
            lines.append(f"• `{c['device_id']}` ({c['ip']}) [{auth}]")
    else:
        lines.append("\n*Chưa có đầu đọc nào kết nối TCP.*")

    if discovered:
        lines.append("\n**Dò thấy trên LAN:**")
        for d in discovered:
            lines.append(f"• `{d['device_id']}` ({d['ip']})")

    embed.description = "\n".join(lines)
    return embed


def _build_dangkythe_embed(hs_query: str) -> tuple[discord.Embed, ui.View | None]:
    pending = get_pending_card()

    if pending:
        uid = pending["uid"]
        student, is_newly_created = get_or_create_blank_student(query=hs_query, uid=uid)
        dev = pending.get("device_id", "ESP32")
        name = student.get("full_name") or "Chưa cập nhật"
        cls = f" ({student.get('class_name')})" if student.get("class_name") else ""
        embed = discord.Embed(
            color=discord.Color.green(),
            description=f"✅ Đã gán thẻ `{uid}` cho **{name}**{cls} • `{student.get('student_id', hs_query)}`\n📍 {dev}",
            timestamp=datetime.now(),
        )
        return embed, None

    student, is_newly_created = get_or_create_blank_student(query=hs_query, uid=None)
    if is_newly_created:
        embed = discord.Embed(
            color=discord.Color.gold(),
            description=f"📋 Tạo hồ sơ mới: **{student['student_id']}**\nQuẹt thẻ lên đầu đọc rồi bấm nút bên dưới.",
            timestamp=datetime.now(),
        )
        view = ui.View(timeout=120)
        btn = ui.Button(label="Gán thẻ vừa quẹt", style=discord.ButtonStyle.primary, emoji="⚡")

        async def _btn_callback(interaction: discord.Interaction) -> None:
            new_pending = get_pending_card()
            if not new_pending:
                await interaction.response.send_message("Chưa phát hiện thẻ trên đầu đọc.", ephemeral=True)
                return
            updated, _ = get_or_create_blank_student(query=student["student_id"], uid=new_pending["uid"])
            await interaction.response.send_message(
                embed=discord.Embed(
                    color=discord.Color.green(),
                    description=f"✅ Đã gán thẻ `{new_pending['uid']}` cho **{updated['student_id']}**",
                )
            )

        btn.callback = _btn_callback
        view.add_item(btn)
        return embed, view

    name = student.get("full_name") or "Chưa cập nhật"
    cls = f" ({student.get('class_name')})" if student.get("class_name") else ""
    embed = discord.Embed(
        color=discord.Color.blue(),
        description=f"👤 **{name}**{cls} • `{student.get('student_id')}`\nUID hiện tại: `{student.get('uid') or 'Chưa có'}`\n*Quẹt thẻ mới lên đầu đọc để thay đổi.*",
        timestamp=datetime.now(),
    )
    return embed, None


def _build_help_embed() -> discord.Embed:
    embed = discord.Embed(title="Danh sách lệnh", color=discord.Color.blurple())
    embed.description = (
        "• `/dangkythe <mã-hs>` — Gán thẻ vừa quẹt cho học sinh\n"
        "• `/themoi` — Xem thẻ chưa đăng ký vừa quẹt\n"
        "• `/diemdanh [mã-hs]` — Tra cứu học sinh / nhật ký gần nhất\n"
        "• `/trangthai` — Xem thông số hệ thống và đầu đọc\n"
        "• `/ketnoi` — Quét tìm đầu đọc ESP32 trên LAN\n"
        "• `/xoathe <uid>` — Xóa thẻ khỏi hệ thống\n"
        "• `/panel` — Mở bảng nút thao tác nhanh"
    )
    return embed


def _build_themoi_embed() -> discord.Embed | None:
    pending = get_pending_card()
    if not pending:
        return None
    embed = discord.Embed(
        color=discord.Color.orange(),
        description=f"⚠️ **Thẻ chưa đăng ký:** `{pending.get('uid')}`\n📍 {pending.get('device_id')} • 🕒 {str(pending.get('timestamp'))[-8:]}\nDùng `/dangkythe <mã-hs>` để gán.",
        timestamp=datetime.now(),
    )
    return embed


def _build_diemdanh_embed(hs: str | None) -> discord.Embed:
    if hs:
        student = find_student(hs)
        if not student:
            return discord.Embed(description=f"❌ Không tìm thấy học sinh: `{hs}`", color=discord.Color.red())
        cls = f" ({student.get('class_name')})" if student.get("class_name") else ""
        embed = discord.Embed(color=discord.Color.blue(), timestamp=datetime.now())
        embed.description = (
            f"👤 **{student.get('full_name', 'N/A')}**{cls}\n"
            f"Mã HS: `{student.get('student_id', 'N/A')}` • UID: `{student.get('uid', 'Chưa có')}`"
        )
        return embed

    logs = get_recent_logs(limit=8)
    embed = discord.Embed(title="Điểm danh gần đây", color=discord.Color.blurple(), timestamp=datetime.now())
    if not logs:
        embed.description = "*Chưa có lượt điểm danh nào.*"
    else:
        lines = [
            f"• **{log.get('full_name') or log.get('uid')}** ({log.get('class_name', '')}) — `{str(log.get('timestamp', ''))[-8:]}`"
            for log in logs
        ]
        embed.description = "\n".join(lines)
    return embed


def _build_trangthai_embed() -> discord.Embed:
    metrics = get_stats()
    readers = get_active_esp32_readers()
    embed = discord.Embed(title="Trạng thái hệ thống", color=discord.Color.blurple(), timestamp=datetime.now())
    lines = [
        f"• **Điểm danh hôm nay:** {metrics['today_scans']} lượt",
        f"• **Tổng học sinh:** {metrics['total_students']}",
        f"• **Cơ sở dữ liệu:** `{metrics['active_database']}`",
        f"• **Đầu đọc online:** {len(readers)}",
    ]
    if metrics.get("failsafe_active"):
        lines.append("⚠️ *Đang sử dụng CSDL dự phòng (Fail-Safe)*")
    embed.description = "\n".join(lines)
    return embed


@bot.event
async def on_ready() -> None:
    global _bot_loop, _event_queue, _worker_task
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


@bot.tree.command(name="dangkythe", description="Tìm học sinh trong CSDL (tạo hồ sơ trống nếu chưa có) và gán thẻ NFC vừa quẹt")
@app_commands.describe(hs="Mã học sinh hoặc Tên học sinh cần đăng ký")
async def slash_dangkythe(interaction: discord.Interaction, hs: str) -> None:
    embed, view = _build_dangkythe_embed(hs)
    await interaction.response.send_message(embed=embed, view=view) if view else await interaction.response.send_message(embed=embed)


@bot.tree.command(name="ketnoi", description="Yêu cầu Backend chủ động dò tìm và kết nối tới thiết bị ESP32 trên LAN")
async def slash_ketnoi(interaction: discord.Interaction) -> None:
    await interaction.response.defer(thinking=True)
    await interaction.followup.send(embed=_build_ketnoi_embed(trigger_esp32_discovery()))


@bot.tree.command(name="help", description="Xem danh sách lệnh và hướng dẫn sử dụng bot NFC")
async def slash_help(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(embed=_build_help_embed())


@bot.tree.command(name="themoi", description="Xem thẻ chưa đăng ký vừa quẹt gần nhất tại đầu đọc ESP32")
async def slash_themoi(interaction: discord.Interaction) -> None:
    embed = _build_themoi_embed()
    if embed:
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message("Hiện không có thẻ chưa đăng ký nào trong bộ nhớ tạm.")


@bot.tree.command(name="diemdanh", description="Tra cứu thông tin và lịch sử điểm danh của học sinh")
@app_commands.describe(hs="Mã học sinh hoặc UID cần tra cứu (để trống để xem toàn trường)")
async def slash_diemdanh(interaction: discord.Interaction, hs: str | None = None) -> None:
    await interaction.response.send_message(embed=_build_diemdanh_embed(hs))


@bot.tree.command(name="trangthai", description="Xem tình trạng hệ thống toàn diện (Backend, CSDL, Fail-Safe, ESP32)")
async def slash_trangthai(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(embed=_build_trangthai_embed())


@bot.tree.command(name="xoathe", description="Xóa đăng ký thẻ học sinh khỏi hệ thống")
@app_commands.describe(uid="Mã UID của thẻ cần xóa")
async def slash_xoathe(interaction: discord.Interaction, uid: str) -> None:
    await interaction.response.send_message(f"Đã xóa thành công thẻ có UID: `{uid}`" if delete_card(uid) else f"Không tìm thấy thẻ có UID: `{uid}` để xóa.")


@bot.tree.command(name="panel", description="Mở bảng điều khiển tương tác trực quan")
async def slash_panel(interaction: discord.Interaction) -> None:
    embed = discord.Embed(
        title="Bảng điều khiển NFC",
        description="Chọn thao tác bên dưới:",
        color=discord.Color.blurple(),
    )
    await interaction.response.send_message(embed=embed, view=RegistrationPanelView())


@bot.command(name="help")
async def cmd_help(ctx: commands.Context) -> None:
    await ctx.send(embed=_build_help_embed())


@bot.command(name="dangkythe")
async def cmd_dangkythe(ctx: commands.Context, *, hs: str) -> None:
    embed, view = _build_dangkythe_embed(hs)
    await ctx.send(embed=embed, view=view) if view else await ctx.send(embed=embed)


@bot.command(name="ketnoi")
async def cmd_ketnoi(ctx: commands.Context) -> None:
    msg = await ctx.send("Đang kiểm tra kết nối thiết bị...")
    await msg.edit(content=None, embed=_build_ketnoi_embed(trigger_esp32_discovery()))


@bot.command(name="themoi", aliases=["lastcard"])
async def cmd_themoi(ctx: commands.Context) -> None:
    embed = _build_themoi_embed()
    if embed:
        await ctx.send(embed=embed)
    else:
        await ctx.send("Chưa có thẻ mới nào quẹt trên đầu đọc.")


@bot.command(name="diemdanh", aliases=["check"])
async def cmd_diemdanh(ctx: commands.Context, hs: str | None = None) -> None:
    await ctx.send(embed=_build_diemdanh_embed(hs))


@bot.command(name="trangthai", aliases=["stats"])
async def cmd_trangthai(ctx: commands.Context) -> None:
    await ctx.send(embed=_build_trangthai_embed())


@bot.command(name="xoathe", aliases=["del"])
async def cmd_xoathe(ctx: commands.Context, uid: str) -> None:
    await ctx.send(f"Đã xóa thẻ `{uid}`." if delete_card(uid) else f"Không tìm thấy thẻ `{uid}`.")


@bot.command(name="panel")
async def cmd_panel(ctx: commands.Context) -> None:
    embed = discord.Embed(
        title="Bảng điều khiển NFC",
        description="Chọn thao tác bên dưới:",
        color=discord.Color.blurple(),
    )
    await ctx.send(embed=embed, view=RegistrationPanelView())


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


async def _attendance_event_worker() -> None:
    channel_id = get_notification_channel_id()
    if not channel_id or not is_notifications_enabled():
        return

    channel = bot.get_channel(channel_id)
    if not channel:
        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception as e:
            logger.warning(f"Could not find notification channel {channel_id}: {e}")
            return

    global _recent_unknown_cards
    last_send_time = 0.0

    while True:
        try:
            if not _event_queue:
                await asyncio.sleep(1)
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

            success_events = [e for e in batch if e.get("status") == "SUCCESS" and e.get("student")]
            unknown_events = [e for e in batch if e.get("status") == "UNKNOWN_CARD" and e.get("uid")]

            realtime_events = [e for e in success_events if not e.get("is_offline")]
            offline_events = [e for e in success_events if e.get("is_offline")]

            if realtime_events:
                if len(realtime_events) == 1:
                    ev = realtime_events[0]
                    student = ev.get("student", {})
                    name = student.get("full_name", "N/A")
                    uid = ev.get("uid", "N/A")
                    time_str = _format_event_time(ev.get("timestamp"))

                    embed = discord.Embed(title="Điểm Danh Thành Công", color=discord.Color.green())
                    embed.description = (
                        f"- Tên học sinh: {name}\n"
                        f"- Thời Gian: {time_str}\n"
                        f"- UID: {uid}"
                    )
                    last_send_time = await _send_with_ratelimit(channel, embed, last_send_time)
                else:
                    embed = discord.Embed(
                        title=f"Điểm Danh Thành Công ({len(realtime_events)} học sinh)",
                        color=discord.Color.green(),
                    )
                    lines = []
                    for ev in realtime_events[:15]:
                        student = ev.get("student", {})
                        name = student.get("full_name", "N/A")
                        uid = ev.get("uid", "N/A")
                        time_str = _format_event_time(ev.get("timestamp"))
                        lines.append(f"• **{name}** - {time_str} (UID: `{uid}`)")
                    if len(realtime_events) > 15:
                        lines.append(f"... và {len(realtime_events) - 15} học sinh khác")
                    embed.description = "\n".join(lines)
                    last_send_time = await _send_with_ratelimit(channel, embed, last_send_time)

            if offline_events:
                if len(offline_events) == 1:
                    ev = offline_events[0]
                    student = ev.get("student", {})
                    name = student.get("full_name", "N/A")
                    uid = ev.get("uid", "N/A")
                    time_str = _format_event_time(ev.get("timestamp"))

                    embed = discord.Embed(title="Điểm Danh Thành Công", color=discord.Color.teal())
                    embed.description = (
                        f"- Tên học sinh: {name}\n"
                        f"- Thời Gian: {time_str}\n"
                        f"- UID: {uid}"
                    )
                    last_send_time = await _send_with_ratelimit(channel, embed, last_send_time)
                else:
                    embed = discord.Embed(
                        title=f"Điểm Danh Thành Công ({len(offline_events)} học sinh ngoại tuyến)",
                        color=discord.Color.teal(),
                    )
                    lines = []
                    for ev in offline_events[:15]:
                        student = ev.get("student", {})
                        name = student.get("full_name", "N/A")
                        uid = ev.get("uid", "N/A")
                        time_str = _format_event_time(ev.get("timestamp"))
                        lines.append(f"• **{name}** - {time_str} (UID: `{uid}`)")
                    if len(offline_events) > 15:
                        lines.append(f"... và {len(offline_events) - 15} học sinh khác")
                    embed.description = "\n".join(lines)
                    last_send_time = await _send_with_ratelimit(channel, embed, last_send_time)

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
                    last_send_time = await _send_with_ratelimit(channel, embed, last_send_time)
                elif len(filtered_unknowns) > 1:
                    embed = discord.Embed(title="Điểm Danh Thất Bại", color=discord.Color.red())
                    uids = ", ".join([f"`{e.get('uid')}`" for e in filtered_unknowns[:10]])
                    embed.description = f"Lí Do: {len(filtered_unknowns)} thẻ chưa đăng ký ({uids})"
                    last_send_time = await _send_with_ratelimit(channel, embed, last_send_time)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Error broadcasting event: {e}")
            await asyncio.sleep(1)


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
