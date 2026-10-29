import asyncio
from typing import Any
import discord

from src.bots.bot import (
    bot,
    _event_queue,
    _bot_loop,
    _recent_unknown_cards,
    _recent_notified_students,
)
from src.bots.config import (
    get_info_channel_id,
    get_noti_channel_id,
    get_reg_channel_id,
    get_status_channel_id,
    get_status_interval_minutes,
    get_status_message_id,
    get_status_update_mode,
    is_notifications_enabled,
    set_status_message_id,
)
from src.bots.connector import register_attendance_hook
from src.bots.embeds import build_esp32_status_embed, format_event_time
from src.logger import get_logger

logger = get_logger("discord_workers")


def safe_enqueue(event: dict[str, Any]) -> None:
    from src.bots import bot as bot_module
    if bot_module._event_queue is not None:
        try:
            bot_module._event_queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("Event queue full (500 items), dropping event")


def on_scan_event(event: dict[str, Any]) -> None:
    from src.bots import bot as bot_module
    if not is_notifications_enabled():
        return
    if bot_module._bot_loop and bot_module._event_queue and bot_module._bot_loop.is_running():
        bot_module._bot_loop.call_soon_threadsafe(safe_enqueue, event)


register_attendance_hook(on_scan_event)


async def send_with_ratelimit(
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
        return asyncio.get_running_loop().time()
    except discord.HTTPException as e:
        logger.error(f"HTTP error sending embed: {e}")
        return asyncio.get_running_loop().time()


async def resolve_channel(channel_id: int | None) -> discord.TextChannel | None:
    if not channel_id:
        return None
    ch = bot.get_channel(channel_id)
    if not ch:
        try:
            ch = await bot.fetch_channel(channel_id)
        except Exception:
            return None
    return ch


async def attendance_event_worker() -> None:
    if not is_notifications_enabled():
        return

    from src.bots import bot as bot_module
    last_send_time = 0.0

    while True:
        try:
            if not bot_module._event_queue:
                await asyncio.sleep(1)
                continue

            noti_channel = await resolve_channel(get_noti_channel_id())
            status_channel = (await resolve_channel(get_status_channel_id())) or noti_channel
            reg_channel = (await resolve_channel(get_reg_channel_id())) or noti_channel

            if not noti_channel and not status_channel and not reg_channel:
                await asyncio.sleep(2)
                continue

            first_event = await bot_module._event_queue.get()
            batch = [first_event]

            while len(batch) < 20:
                try:
                    ev = bot_module._event_queue.get_nowait()
                    batch.append(ev)
                except asyncio.QueueEmpty:
                    break

            # 1. Device watchdog events
            device_events = [e for e in batch if e.get("event") == "DEVICE_WATCHDOG"]
            for dev_ev in device_events:
                dev_status = dev_ev.get("status")
                dev_id = dev_ev.get("device_id", "ESP32")
                ip = dev_ev.get("ip", "N/A")

                if dev_status == "DEVICE_OFFLINE":
                    last_seen = format_event_time(dev_ev.get("last_seen"))
                    lines = [
                        f"- Thiết bị: **{dev_id}**",
                        f"- Địa chỉ IP: {ip}",
                        f"- Tín hiệu cuối: {last_seen}",
                        "- Tình trạng: Mất nguồn hoặc ngắt kết nối mạng",
                    ]
                    embed = discord.Embed(title="Cảnh báo: Đầu đọc mất tín hiệu", color=discord.Color.red())
                    embed.description = "\n".join(lines)
                    last_send_time = await send_with_ratelimit(status_channel, embed, last_send_time)

                elif dev_status == "DEVICE_ONLINE":
                    lines = [
                        f"- Thiết bị: **{dev_id}**",
                        f"- Địa chỉ IP: {ip}",
                        f"- Thời gian kết nối lại: {format_event_time(dev_ev.get('timestamp'))}",
                    ]
                    rssi = dev_ev.get("rssi")
                    if rssi is not None and rssi != 0 and rssi != -100:
                        lines.append(f"- Sóng Wi-Fi: {rssi} dBm")
                    embed = discord.Embed(title="Đầu đọc đã hoạt động trở lại", color=discord.Color.green())
                    embed.description = "\n".join(lines)
                    last_send_time = await send_with_ratelimit(status_channel, embed, last_send_time)

            # 2. Command ACK events (config_ack / reboot_ack)
            cmd_ack_events = [e for e in batch if e.get("action") in ("config_ack", "reboot_ack")]
            for ack in cmd_ack_events:
                dev_id = ack.get("device_id", "ESP32")
                action = ack.get("action")

                if action == "config_ack":
                    lines = [
                        f"- Thiết bị: **{dev_id}**",
                        f"- Trạng thái: {ack.get('message', 'Thành công')}",
                        f"- Thời gian: {format_event_time(ack.get('timestamp'))}",
                    ]
                    details = ack.get("details", {})
                    if "cooldown_ms" in details:
                        lines.append(f"- Cooldown: {details['cooldown_ms']} ms")
                    if "feedback_duration_ms" in details:
                        lines.append(f"- Phản hồi: {details['feedback_duration_ms']} ms")
                    if "location" in details:
                        lines.append(f"- Vị trí: {details['location']}")

                    embed = discord.Embed(title="Đầu đọc đã áp dụng cấu hình", color=discord.Color.blue())
                    embed.description = "\n".join(lines)
                    last_send_time = await send_with_ratelimit(status_channel, embed, last_send_time)

                elif action == "reboot_ack":
                    lines = [
                        f"- Thiết bị: **{dev_id}**",
                        "- Quá trình: Thiết bị đang khởi động lại hệ thống",
                        f"- Thời gian: {format_event_time(ack.get('timestamp'))}",
                    ]
                    embed = discord.Embed(title="Đầu đọc đang khởi động lại", color=discord.Color.gold())
                    embed.description = "\n".join(lines)
                    last_send_time = await send_with_ratelimit(status_channel, embed, last_send_time)

            # 3. Attendance events
            success_events = [e for e in batch if e.get("status") == "SUCCESS" and e.get("student")]
            unknown_events = [e for e in batch if e.get("status") == "UNKNOWN_CARD" and e.get("uid")]

            realtime_events = []
            offline_events = []
            seen_realtime_students = set()
            seen_offline_uids = set()

            now_ts = asyncio.get_running_loop().time()

            for ev in success_events:
                is_offline = ev.get("offline", False)
                student = ev.get("student", {})
                stu_id = student.get("student_id") or ev.get("uid")

                if is_offline:
                    uid = ev.get("uid")
                    if uid in seen_offline_uids:
                        continue
                    seen_offline_uids.add(uid)
                    offline_events.append(ev)
                else:
                    if stu_id in seen_realtime_students:
                        continue
                    if now_ts - bot_module._recent_notified_students.get(stu_id, 0.0) < 5.0:
                        continue
                    bot_module._recent_notified_students[stu_id] = now_ts
                    seen_realtime_students.add(stu_id)
                    realtime_events.append(ev)

            if len(bot_module._recent_notified_students) > 200:
                bot_module._recent_notified_students = {k: v for k, v in bot_module._recent_notified_students.items() if now_ts - v < 30.0}

            if realtime_events:
                if len(realtime_events) == 1:
                    ev = realtime_events[0]
                    student = ev.get("student", {})
                    name = student.get("full_name", "N/A")
                    cls = student.get("class_name") or "Chưa phân lớp"
                    uid = ev.get("uid", "N/A")
                    time_str = format_event_time(ev.get("timestamp"))

                    embed = discord.Embed(title="Điểm danh thành công", color=discord.Color.green())
                    embed.description = (
                        f"- Họ và tên: {name}\n"
                        f"- Lớp: {cls}\n"
                        f"- Thời gian: {time_str}\n"
                        f"- UID: `{uid}`"
                    )
                    last_send_time = await send_with_ratelimit(noti_channel, embed, last_send_time)
                else:
                    embed = discord.Embed(
                        title=f"Điểm danh thành công ({len(realtime_events)} học sinh)",
                        color=discord.Color.green(),
                    )
                    lines = []
                    for ev in realtime_events[:15]:
                        student = ev.get("student", {})
                        name = student.get("full_name", "N/A")
                        cls = student.get("class_name") or "Chưa phân lớp"
                        uid = ev.get("uid", "N/A")
                        time_str = format_event_time(ev.get("timestamp"))
                        lines.append(f"- **{name}** ({cls}) - {time_str} (UID: `{uid}`)")
                    if len(realtime_events) > 15:
                        lines.append(f"... và {len(realtime_events) - 15} học sinh khác")
                    embed.description = "\n".join(lines)
                    last_send_time = await send_with_ratelimit(noti_channel, embed, last_send_time)

            if offline_events:
                if len(offline_events) == 1:
                    ev = offline_events[0]
                    student = ev.get("student", {})
                    name = student.get("full_name", "N/A")
                    cls = student.get("class_name") or "Chưa phân lớp"
                    uid = ev.get("uid", "N/A")
                    time_str = format_event_time(ev.get("timestamp"))

                    embed = discord.Embed(title="Đồng bộ điểm danh ngoại tuyến", color=discord.Color.teal())
                    embed.description = (
                        f"- Họ và tên: {name}\n"
                        f"- Lớp: {cls}\n"
                        f"- Thời gian: {time_str}\n"
                        f"- UID: `{uid}`"
                    )
                    last_send_time = await send_with_ratelimit(noti_channel, embed, last_send_time)
                else:
                    embed = discord.Embed(
                        title=f"Đồng bộ điểm danh ngoại tuyến ({len(offline_events)} học sinh)",
                        color=discord.Color.teal(),
                    )
                    lines = []
                    for ev in offline_events[:15]:
                        student = ev.get("student", {})
                        name = student.get("full_name", "N/A")
                        cls = student.get("class_name") or "Chưa phân lớp"
                        uid = ev.get("uid", "N/A")
                        time_str = format_event_time(ev.get("timestamp"))
                        lines.append(f"- **{name}** ({cls}) - {time_str} (UID: `{uid}`)")
                    if len(offline_events) > 15:
                        lines.append(f"... và {len(offline_events) - 15} học sinh khác")
                    embed.description = "\n".join(lines)
                    last_send_time = await send_with_ratelimit(noti_channel, embed, last_send_time)

            # 4. Unknown cards
            if unknown_events:
                now_loop = asyncio.get_running_loop().time()
                filtered_unknowns = []
                for ev in unknown_events:
                    uid = ev.get("uid")
                    if not uid:
                        continue
                    if now_loop - bot_module._recent_unknown_cards.get(uid, 0.0) < 10.0:
                        continue
                    bot_module._recent_unknown_cards[uid] = now_loop
                    filtered_unknowns.append(ev)

                if len(bot_module._recent_unknown_cards) > 100:
                    bot_module._recent_unknown_cards = {k: v for k, v in bot_module._recent_unknown_cards.items() if now_loop - v < 60.0}

                if len(filtered_unknowns) == 1:
                    ev = filtered_unknowns[0]
                    uid = ev.get("uid", "N/A")
                    embed = discord.Embed(title="Điểm danh không thành công", color=discord.Color.red())
                    embed.description = f"Lí do: Thẻ chưa đăng ký (UID: `{uid}`)"
                    last_send_time = await send_with_ratelimit(reg_channel, embed, last_send_time)
                elif len(filtered_unknowns) > 1:
                    embed = discord.Embed(title="Điểm danh không thành công", color=discord.Color.red())
                    uids = ", ".join([f"`{e.get('uid')}`" for e in filtered_unknowns[:10]])
                    embed.description = f"Lí do: {len(filtered_unknowns)} thẻ chưa đăng ký ({uids})"
                    last_send_time = await send_with_ratelimit(reg_channel, embed, last_send_time)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Error broadcasting event: {e}")
            await asyncio.sleep(1)


async def status_periodic_worker() -> None:
    await bot.wait_until_ready()
    await asyncio.sleep(5)

    while not bot.is_closed():
        try:
            interval_min = get_status_interval_minutes()
            if interval_min <= 0:
                await asyncio.sleep(15)
                continue

            status_channel = (await resolve_channel(get_status_channel_id())) or (await resolve_channel(get_noti_channel_id()))
            if status_channel:
                mode = get_status_update_mode()
                mode_desc = "Live Dashboard" if mode == "edit" else "Gửi định kỳ"
                embed = build_esp32_status_embed(interval_min, mode_desc)
                msg_id = get_status_message_id()

                if mode == "edit" and msg_id:
                    try:
                        msg = await status_channel.fetch_message(msg_id)
                        await msg.edit(embed=embed)
                    except discord.NotFound:
                        new_msg = await status_channel.send(embed=embed)
                        set_status_message_id(new_msg.id)
                    except Exception as e:
                        logger.warning(f"Could not edit live status message: {e}")
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
