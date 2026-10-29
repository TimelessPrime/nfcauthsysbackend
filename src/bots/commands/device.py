from typing import Any
import discord
from discord import app_commands
from discord.ext import commands

from src.bots.connector import (
    get_active_esp32_readers,
    send_config_update,
    send_reader_reboot,
    trigger_esp32_discovery,
)
from src.bots.embeds import build_ketnoi_embed


async def reader_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    readers = get_active_esp32_readers()
    choices = [app_commands.Choice(name="Tất cả đầu đọc (all)", value="all")]
    for r in readers:
        dev_id = r.get("device_id", "")
        ip = r.get("ip", "")
        label = f"{dev_id} ({ip})" if ip else dev_id
        if current.lower() in label.lower() or current.lower() in dev_id.lower():
            choices.append(app_commands.Choice(name=label, value=dev_id))
    return choices[:25]


def register_device_commands(bot: commands.Bot) -> None:

    @bot.tree.command(name="ketnoi", description="Yêu cầu Backend dò tìm và kết nối tới thiết bị ESP32 trên LAN")
    async def slash_ketnoi(interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        await interaction.followup.send(embed=build_ketnoi_embed(trigger_esp32_discovery()))

    @bot.tree.command(name="cauhinh", description="Cấu hình thông số cho đầu đọc ESP32 từ xa qua mạng TCP")
    @app_commands.autocomplete(thiet_bi=reader_autocomplete)
    @app_commands.describe(
        thiet_bi="ID đầu đọc cần cấu hình (hoặc 'all')",
        cooldown_ms="Thời gian giãn cách giữa 2 lần quẹt thẻ (ms)",
        coi_bao_ms="Thời gian bíp còi và sáng LED phản hồi (ms)",
        vi_tri="Vị trí đặt đầu đọc (Ví dụ: Cổng chính, Phòng 10A1)",
        wifi_ssid="Tên mạng Wi-Fi mới",
        wifi_password="Mật khẩu Wi-Fi mới",
    )
    async def slash_cauhinh(
        interaction: discord.Interaction,
        thiet_bi: str,
        cooldown_ms: int | None = None,
        coi_bao_ms: int | None = None,
        vi_tri: str | None = None,
        wifi_ssid: str | None = None,
        wifi_password: str | None = None,
    ) -> None:
        updates: dict[str, Any] = {}
        if cooldown_ms is not None:
            updates["cooldown_ms"] = cooldown_ms
        if coi_bao_ms is not None:
            updates["feedback_duration_ms"] = coi_bao_ms
        if vi_tri is not None:
            updates["location"] = vi_tri.strip()
        if wifi_ssid is not None:
            updates["wifi_ssid"] = wifi_ssid.strip()
        if wifi_password is not None:
            updates["wifi_password"] = wifi_password.strip()

        if not updates:
            await interaction.response.send_message(
                "Vui lòng nhập ít nhất một thông số cần thay đổi (cooldown_ms, coi_bao_ms, vi_tri, wifi).",
                ephemeral=True,
            )
            return

        result = send_config_update(thiet_bi, updates)
        if result.get("success"):
            embed = discord.Embed(title="Cập nhật cấu hình thành công", color=discord.Color.blue())
            lines = [
                f"- Thiết bị: **{thiet_bi}**",
                f"- Trạng thái: {result.get('message', 'Đã chuyển tiếp lệnh')}",
            ]
            if "cooldown_ms" in updates:
                lines.append(f"- Cooldown: {updates['cooldown_ms']} ms")
            if "feedback_duration_ms" in updates:
                lines.append(f"- Phản hồi còi/LED: {updates['feedback_duration_ms']} ms")
            if "location" in updates:
                lines.append(f"- Vị trí: {updates['location']}")
            if "wifi_ssid" in updates:
                lines.append(f"- Wi-Fi SSID: {updates['wifi_ssid']}")
            lines.append("- Thiết bị đã lưu vào bộ nhớ flash NVS và áp dụng tức thì.")
            embed.description = "\n".join(lines)
        else:
            embed = discord.Embed(title="Cập nhật cấu hình không thành công", color=discord.Color.red())
            embed.description = f"- Lí do: {result.get('message', 'Không thể kết nối tới đầu đọc')}"

        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="khoidonglai", description="Khởi động lại đầu đọc ESP32 từ xa qua mạng TCP")
    @app_commands.autocomplete(thiet_bi=reader_autocomplete)
    @app_commands.describe(thiet_bi="ID đầu đọc cần khởi động lại (hoặc 'all')")
    async def slash_khoidonglai(interaction: discord.Interaction, thiet_bi: str) -> None:
        result = send_reader_reboot(thiet_bi)
        if result.get("success"):
            embed = discord.Embed(title="Khởi động lại thiết bị", color=discord.Color.gold())
            embed.description = (
                f"- Thiết bị: **{thiet_bi}**\n"
                f"- Kết quả: {result.get('message', 'Thành công')}\n"
                f"- Quá trình khởi động mất khoảng 3-5 giây."
            )
        else:
            embed = discord.Embed(title="Khởi động lại không thành công", color=discord.Color.red())
            embed.description = f"- Lí do: {result.get('message', 'Không thể kết nối tới đầu đọc')}"

        await interaction.response.send_message(embed=embed)

    # Prefix commands
    @bot.command(name="ketnoi")
    async def cmd_ketnoi(ctx: commands.Context) -> None:
        await ctx.send(embed=build_ketnoi_embed(trigger_esp32_discovery()))

    @bot.command(name="khoidonglai", aliases=["reboot"])
    async def cmd_khoidonglai(ctx: commands.Context, thiet_bi: str = "all") -> None:
        result = send_reader_reboot(thiet_bi)
        if result.get("success"):
            embed = discord.Embed(title="Khởi động lại thiết bị", color=discord.Color.gold())
            embed.description = (
                f"- Thiết bị: **{thiet_bi}**\n"
                f"- Kết quả: {result.get('message', 'Thành công')}\n"
                f"- Quá trình khởi động mất khoảng 3-5 giây."
            )
        else:
            embed = discord.Embed(title="Khởi động lại không thành công", color=discord.Color.red())
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
            embed = discord.Embed(title="Hướng dẫn cấu hình đầu đọc", color=discord.Color.blurple())
            embed.description = (
                "- Cú pháp: `!cauhinh [thiết bị/all] [cooldown_ms] [còi_ms] [vị trí]`\n"
                "- Ví dụ: `!cauhinh all 2000 150 \"Cổng chính\"`\n"
                "- Dùng lệnh `/cauhinh` để có gợi ý tham số thuận tiện hơn."
            )
            await ctx.send(embed=embed)
            return

        result = send_config_update(thiet_bi, updates)
        if result.get("success"):
            embed = discord.Embed(title="Cập nhật cấu hình thành công", color=discord.Color.blue())
            lines = [f"- Thiết bị: **{thiet_bi}**", f"- Trạng thái: {result.get('message', 'Đã chuyển lệnh')}"]
            if "cooldown_ms" in updates:
                lines.append(f"- Cooldown: {updates['cooldown_ms']} ms")
            if "feedback_duration_ms" in updates:
                lines.append(f"- Phản hồi còi/LED: {updates['feedback_duration_ms']} ms")
            if "location" in updates:
                lines.append(f"- Vị trí: {updates['location']}")
            embed.description = "\n".join(lines)
        else:
            embed = discord.Embed(title="Cập nhật cấu hình không thành công", color=discord.Color.red())
            embed.description = f"- Lí do: {result.get('message', 'Không thể kết nối tới đầu đọc')}"
        await ctx.send(embed=embed)
