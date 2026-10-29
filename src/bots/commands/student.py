import discord
from discord import app_commands
from discord.ext import commands

from src.bots.connector import clear_pending_card, get_pending_card
from src.bots.database import (
    delete_card,
    find_student,
    get_recent_logs,
    register_or_update_student,
    update_student_class,
)
from src.bots.embeds import (
    build_diemdanh_embed,
    build_themoi_embed,
    build_xoathe_embed,
)
from src.bots.views import (
    RegisterType1Modal,
    build_waiting_card_view,
)


def register_student_commands(bot: commands.Bot) -> None:

    @bot.tree.command(name="dangky", description="Đăng ký học sinh (Type 1: Nhập UID / Type 2: Quẹt thẻ)")
    @app_commands.describe(
        type="1: Nhập UID trên bot | 2: Quẹt thẻ trên thiết bị",
        ten_hs="Họ và tên học sinh",
        lop="Lớp học của học sinh (Ví dụ: 12A1)",
        uid="Mã UID thẻ (tùy chọn cho Type 1)",
    )
    @app_commands.choices(
        type=[
            app_commands.Choice(name="1 - Nhập UID trực tiếp", value=1),
            app_commands.Choice(name="2 - Quẹt thẻ trên đầu đọc", value=2),
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
                    fail_embed = discord.Embed(title="Đăng ký không thành công", color=discord.Color.red())
                    fail_embed.description = "Lí do: Mã UID không hợp lệ (tối thiểu 4 ký tự)."
                    await interaction.response.send_message(embed=fail_embed)
                    return
                saved, _ = register_or_update_student(full_name=name, uid=clean_uid, class_name=class_name)
                embed = discord.Embed(title="Đăng ký thành công", color=discord.Color.green())
                embed.description = (
                    f"- Họ và tên: {saved['full_name']}\n"
                    f"- Lớp: {saved['class_name']}\n"
                    f"- UID: `{saved['uid']}`\n"
                    f"- Phương thức: Trực tiếp"
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
                embed = discord.Embed(title="Đăng ký thành công", color=discord.Color.green())
                embed.description = (
                    f"- Họ và tên: {saved['full_name']}\n"
                    f"- Lớp: {saved['class_name']}\n"
                    f"- UID: `{saved['uid']}`\n"
                    f"- Thiết bị: {dev}"
                )
                await interaction.response.send_message(embed=embed)
            else:
                embed, view = build_waiting_card_view(name, class_name)
                await interaction.response.send_message(embed=embed, view=view)

    @bot.tree.command(name="dangkythe", description="Gán thẻ vừa quẹt cho học sinh (tương đương /dangky type 2)")
    @app_commands.describe(hs="Họ và tên học sinh", lop="Lớp học của học sinh (Ví dụ: 12A1)")
    async def slash_dangkythe(interaction: discord.Interaction, hs: str, lop: str = "Chưa phân lớp") -> None:
        type_choice = app_commands.Choice(name="2 - Quẹt thẻ trên đầu đọc", value=2)
        await slash_dangky(interaction, type_choice, ten_hs=hs, lop=lop)

    @bot.tree.command(name="phanlop", description="Cập nhật lớp học cho học sinh")
    @app_commands.describe(
        hs="Tên học sinh, mã học sinh hoặc UID",
        lop="Tên lớp mới (Ví dụ: 12A1)",
    )
    async def slash_phanlop(interaction: discord.Interaction, hs: str, lop: str) -> None:
        updated = update_student_class(hs, lop)
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
            embed.description = f"Lí do: Không tìm thấy học sinh: {hs}"
            await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="diemdanh", description="Tra cứu thông tin và lịch sử điểm danh của học sinh")
    @app_commands.describe(hs="Tên học sinh, mã học sinh hoặc UID cần tra cứu")
    async def slash_diemdanh(interaction: discord.Interaction, hs: str) -> None:
        student = find_student(hs)
        if not student:
            embed = discord.Embed(title="Không tìm thấy học sinh", color=discord.Color.red())
            embed.description = f"Lí do: Không tìm thấy dữ liệu học sinh: {hs}"
            await interaction.response.send_message(embed=embed)
            return

        logs = get_recent_logs(student["uid"])
        today_date = discord.utils.utcnow().strftime("%Y-%m-%d")
        today_scans = sum(1 for log in logs if log.get("timestamp", "").startswith(today_date) and log.get("status") == "SUCCESS")

        embed = build_diemdanh_embed(student, today_scans, logs)
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="themoi", description="Xem thẻ chưa đăng ký vừa quẹt trên đầu đọc")
    async def slash_themoi(interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=build_themoi_embed())

    @bot.tree.command(name="xoathe", description="Xóa đăng ký thẻ học sinh khỏi hệ thống")
    @app_commands.describe(uid="Mã UID thẻ cần xóa")
    async def slash_xoathe(interaction: discord.Interaction, uid: str) -> None:
        clean_uid = uid.strip().upper()
        success = delete_card(clean_uid)
        await interaction.response.send_message(embed=build_xoathe_embed(clean_uid, success))

    # Prefix commands
    @bot.command(name="dangky")
    async def cmd_dangky(
        ctx: commands.Context,
        type_val: int = 1,
        ten_hs: str = "",
        lop: str = "Chưa phân lớp",
        uid: str | None = None,
    ) -> None:
        if not ten_hs:
            embed = discord.Embed(title="Hướng dẫn lệnh đăng ký", color=discord.Color.blurple())
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
                embed = discord.Embed(title="Đăng ký không thành công", color=discord.Color.red())
                embed.description = "Lí do: Type 1 yêu cầu cung cấp mã UID (Ví dụ: `!dangky 1 \"Tên HS\" 12A1 UID`)"
                await ctx.send(embed=embed)
                return
            saved, _ = register_or_update_student(full_name=name, uid=uid.strip(), class_name=class_name)
            embed = discord.Embed(title="Đăng ký thành công", color=discord.Color.green())
            embed.description = (
                f"- Họ và tên: {saved['full_name']}\n"
                f"- Lớp: {saved['class_name']}\n"
                f"- UID: `{saved['uid']}`\n"
                f"- Phương thức: Trực tiếp"
            )
            await ctx.send(embed=embed)
        elif type_val == 2:
            pending = get_pending_card()
            if pending:
                p_uid = pending["uid"]
                dev = pending.get("device_id", "ESP32")
                clear_pending_card()
                saved, _ = register_or_update_student(full_name=name, uid=p_uid, class_name=class_name)
                embed = discord.Embed(title="Đăng ký thành công", color=discord.Color.green())
                embed.description = (
                    f"- Họ và tên: {saved['full_name']}\n"
                    f"- Lớp: {saved['class_name']}\n"
                    f"- UID: `{saved['uid']}`\n"
                    f"- Thiết bị: {dev}"
                )
                await ctx.send(embed=embed)
            else:
                embed, view = build_waiting_card_view(name, class_name)
                await ctx.send(embed=embed, view=view)

    @bot.command(name="phanlop")
    async def cmd_phanlop(ctx: commands.Context, hs: str = "", lop: str = "") -> None:
        if not hs or not lop:
            embed = discord.Embed(title="Hướng dẫn phân lớp", color=discord.Color.blurple())
            embed.description = "Cú pháp: `!phanlop \"<tên hs/mã hs/uid>\" <lớp mới>`"
            await ctx.send(embed=embed)
            return
        updated = update_student_class(hs.strip(), lop.strip())
        if updated:
            embed = discord.Embed(title="Phân lớp thành công", color=discord.Color.green())
            embed.description = (
                f"- Họ và tên: {updated['full_name']}\n"
                f"- Lớp: {updated['class_name']}\n"
                f"- UID: `{updated['uid']}`"
            )
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(title="Phân lớp không thành công", color=discord.Color.red())
            embed.description = f"Lí do: Không tìm thấy học sinh: {hs}"
            await ctx.send(embed=embed)

    @bot.command(name="dangkythe")
    async def cmd_dangkythe(ctx: commands.Context, hs: str = "", lop: str = "Chưa phân lớp") -> None:
        if not hs:
            embed = discord.Embed(title="Hướng dẫn gán thẻ", color=discord.Color.blurple())
            embed.description = "Cú pháp: `!dangkythe \"<tên hs>\" [lớp]`"
            await ctx.send(embed=embed)
            return
        await cmd_dangky(ctx, type_val=2, ten_hs=hs, lop=lop)

    @bot.command(name="themoi", aliases=["lastcard"])
    async def cmd_themoi(ctx: commands.Context) -> None:
        await ctx.send(embed=build_themoi_embed())

    @bot.command(name="diemdanh", aliases=["check"])
    async def cmd_diemdanh(ctx: commands.Context, *, hs: str = "") -> None:
        if not hs:
            embed = discord.Embed(title="Hướng dẫn tra cứu điểm danh", color=discord.Color.blurple())
            embed.description = "Cú pháp: `!diemdanh <tên học sinh / mã học sinh / uid>`"
            await ctx.send(embed=embed)
            return
        student = find_student(hs.strip())
        if not student:
            embed = discord.Embed(title="Không tìm thấy học sinh", color=discord.Color.red())
            embed.description = f"Lí do: Không tìm thấy dữ liệu học sinh: {hs}"
            await ctx.send(embed=embed)
            return

        logs = get_recent_logs(student["uid"])
        today_date = discord.utils.utcnow().strftime("%Y-%m-%d")
        today_scans = sum(1 for log in logs if log.get("timestamp", "").startswith(today_date) and log.get("status") == "SUCCESS")

        embed = build_diemdanh_embed(student, today_scans, logs)
        await ctx.send(embed=embed)

    @bot.command(name="xoathe", aliases=["del"])
    async def cmd_xoathe(ctx: commands.Context, uid: str) -> None:
        clean_uid = uid.strip().upper()
        success = delete_card(clean_uid)
        await ctx.send(embed=build_xoathe_embed(clean_uid, success))
