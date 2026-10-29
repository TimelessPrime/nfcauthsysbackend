import discord
from discord import app_commands
from discord.ext import commands

from src.bots.config import (
    get_admin_roles,
    get_all_channel_ids,
    get_status_interval_minutes,
    get_status_update_mode,
    set_channel_id,
    set_status_interval_minutes,
)
from src.bots.embeds import (
    build_help_embed,
    build_trangthai_embed,
)
from src.bots.views import RegistrationPanelView


def register_system_commands(bot: commands.Bot) -> None:

    @bot.tree.command(name="help", description="Xem danh sách lệnh và hướng dẫn sử dụng")
    async def slash_help(interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=build_help_embed())

    @bot.tree.command(name="trangthai", description="Xem tình trạng hệ thống toàn diện")
    async def slash_trangthai(interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=build_trangthai_embed())

    @bot.tree.command(name="panel", description="Mở bảng điều khiển tương tác trực quan")
    async def slash_panel(interaction: discord.Interaction) -> None:
        embed = discord.Embed(title="Bảng điều khiển hệ thống", color=discord.Color.blurple())
        embed.description = "Chọn chức năng bên dưới để thao tác nhanh."
        await interaction.response.send_message(embed=embed, view=RegistrationPanelView())

    @bot.tree.command(name="kenh", description="Thiết lập kênh Discord chuyên biệt hoặc chu kỳ cập nhật trạng thái")
    @app_commands.describe(
        loai="Loại kênh cần thiết lập (status, noti, reg, info hoặc xem)",
        kenh="Kênh Discord muốn gán làm nơi nhận tin",
        chu_ky_phut="Chu kỳ tự động cập nhật trạng thái ESP32 theo phút (0 để tắt)",
    )
    @app_commands.choices(loai=[
        app_commands.Choice(name="Kênh trạng thái thiết bị (status)", value="status"),
        app_commands.Choice(name="Kênh thông báo điểm danh (noti)", value="noti"),
        app_commands.Choice(name="Kênh đăng ký thẻ học sinh (reg)", value="reg"),
        app_commands.Choice(name="Kênh thông tin và tra cứu (info)", value="info"),
        app_commands.Choice(name="Xem danh sách cấu hình hiện tại (xem)", value="xem"),
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
            if any(r in get_admin_roles() for r in user_roles):
                is_admin = True

        if chu_ky_phut is not None and kenh is None and loai != "xem":
            if not is_admin:
                await interaction.response.send_message("Bạn không có quyền quản trị để thay đổi cấu hình chu kỳ.", ephemeral=True)
                return
            set_status_interval_minutes(chu_ky_phut)
            embed = discord.Embed(title="Cập nhật chu kỳ thành công", color=discord.Color.green())
            embed.description = (
                f"- Chu kỳ tự động cập nhật trạng thái ESP32: **Mỗi {chu_ky_phut} phút**\n"
                f"- Đã lưu vào file cấu hình `bot_config.json`."
                if chu_ky_phut > 0 else
                "- Chu kỳ tự động cập nhật trạng thái ESP32: **Đã tắt**\n- Đã lưu vào file cấu hình `bot_config.json`."
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
            mode_str = "Live Dashboard" if get_status_update_mode() == "edit" else "Gửi định kỳ"
            interval_desc = f"Mỗi {interval} phút ({mode_str})" if interval > 0 else "Đang tắt"

            embed = discord.Embed(title="Cấu hình kênh hệ thống", color=discord.Color.blurple())
            embed.description = (
                f"- Kênh trạng thái thiết bị (`status`): {fmt_ch(all_channels.get('status'))}\n"
                f"- Kênh thông báo điểm danh (`noti`): {fmt_ch(all_channels.get('noti'))}\n"
                f"- Kênh đăng ký thẻ (`reg`): {fmt_ch(all_channels.get('reg'))}\n"
                f"- Kênh thông tin chung (`info`): {fmt_ch(all_channels.get('info'))}\n"
                f"- Tự động cập nhật trạng thái: {interval_desc}\n\n"
                f"Thay đổi kênh: `/kenh loai:[loai] kenh:[#kenh]`\n"
                f"Thay đổi chu kỳ: `/kenh loai:status chu_ky_phut:[phút]`"
            )
            await interaction.response.send_message(embed=embed)
            return

        if not is_admin:
            await interaction.response.send_message("Bạn không có quyền quản trị để thay đổi cấu hình kênh.", ephemeral=True)
            return

        success = False
        if kenh is not None:
            success = set_channel_id(loai, kenh.id)
        if chu_ky_phut is not None:
            set_status_interval_minutes(chu_ky_phut)
            success = True

        if success:
            type_names = {
                "status": "Kênh trạng thái thiết bị",
                "noti": "Kênh thông báo điểm danh",
                "reg": "Kênh đăng ký thẻ học sinh",
                "info": "Kênh thông tin và tra cứu",
            }
            name_vi = type_names.get(loai, loai.upper())
            embed = discord.Embed(title="Thiết lập thành công", color=discord.Color.green())
            lines = [f"- Loại kênh: **{name_vi}**"]
            if kenh:
                lines.append(f"- Kênh được gán: <#{kenh.id}> (`{kenh.name}`)")
            if chu_ky_phut is not None:
                lines.append(f"- Chu kỳ cập nhật trạng thái: Mỗi {chu_ky_phut} phút" if chu_ky_phut > 0 else "- Chu kỳ cập nhật trạng thái: Đã tắt")
            lines.append("- Đã lưu vào file cấu hình `bot_config.json`.")
            embed.description = "\n".join(lines)
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message(f"Không thể lưu cấu hình cho loại kênh `{loai}`.", ephemeral=True)

    # Prefix commands
    @bot.command(name="help")
    async def cmd_help(ctx: commands.Context) -> None:
        await ctx.send(embed=build_help_embed())

    @bot.command(name="trangthai", aliases=["stats"])
    async def cmd_trangthai(ctx: commands.Context) -> None:
        await ctx.send(embed=build_trangthai_embed())

    @bot.command(name="panel")
    async def cmd_panel(ctx: commands.Context) -> None:
        embed = discord.Embed(title="Bảng điều khiển hệ thống", color=discord.Color.blurple())
        embed.description = "Chọn chức năng bên dưới để thao tác nhanh."
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
            if any(r in get_admin_roles() for r in user_roles):
                is_admin = True

        if norm_loai in ("chu_ky", "interval") or (chu_ky_phut is not None and kenh is None and norm_loai in ("xem", "list")):
            if not is_admin:
                await ctx.send("Bạn không có quyền quản trị để thay đổi cấu hình chu kỳ.")
                return
            set_status_interval_minutes(chu_ky_phut)
            embed = discord.Embed(title="Cập nhật chu kỳ thành công", color=discord.Color.green())
            embed.description = (
                f"- Chu kỳ tự động cập nhật trạng thái ESP32: **Mỗi {chu_ky_phut} phút**\n"
                f"- Đã lưu vào file cấu hình `bot_config.json`."
                if chu_ky_phut > 0 else
                "- Chu kỳ tự động cập nhật trạng thái ESP32: **Đã tắt**\n- Đã lưu vào file cấu hình `bot_config.json`."
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
            mode_str = "Live Dashboard" if get_status_update_mode() == "edit" else "Gửi định kỳ"
            interval_desc = f"Mỗi {interval} phút ({mode_str})" if interval > 0 else "Đang tắt"

            embed = discord.Embed(title="Cấu hình kênh hệ thống", color=discord.Color.blurple())
            embed.description = (
                f"- Kênh trạng thái thiết bị (`status`): {fmt_ch(all_channels.get('status'))}\n"
                f"- Kênh thông báo điểm danh (`noti`): {fmt_ch(all_channels.get('noti'))}\n"
                f"- Kênh đăng ký thẻ (`reg`): {fmt_ch(all_channels.get('reg'))}\n"
                f"- Kênh thông tin chung (`info`): {fmt_ch(all_channels.get('info'))}\n"
                f"- Tự động cập nhật trạng thái: {interval_desc}\n\n"
                f"Thay đổi kênh: `!kenh <status|noti|reg|info> #ten-kenh`\n"
                f"Thay đổi chu kỳ: `!kenh chu_ky [số_phút]`"
            )
            await ctx.send(embed=embed)
            return

        if not is_admin:
            await ctx.send("Bạn không có quyền quản trị để thay đổi cấu hình kênh.")
            return

        success = False
        if kenh is not None:
            success = set_channel_id(norm_loai, kenh.id)
        if chu_ky_phut is not None:
            set_status_interval_minutes(chu_ky_phut)
            success = True

        if success:
            type_names = {
                "status": "Kênh trạng thái thiết bị",
                "noti": "Kênh thông báo điểm danh",
                "reg": "Kênh đăng ký thẻ học sinh",
                "info": "Kênh thông tin và tra cứu",
            }
            name_vi = type_names.get(norm_loai, norm_loai.upper())
            embed = discord.Embed(title="Thiết lập thành công", color=discord.Color.green())
            lines = [f"- Loại kênh: **{name_vi}**"]
            if kenh:
                lines.append(f"- Kênh được gán: <#{kenh.id}> (`{kenh.name}`)")
            if chu_ky_phut is not None:
                lines.append(f"- Chu kỳ cập nhật trạng thái: Mỗi {chu_ky_phut} phút" if chu_ky_phut > 0 else "- Chu kỳ cập nhật trạng thái: Đã tắt")
            lines.append("- Đã lưu vào file cấu hình `bot_config.json`.")
            embed.description = "\n".join(lines)
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"Không thể lưu cấu hình cho loại kênh `{loai}`. Các loại hợp lệ: status, noti, reg, info.")
