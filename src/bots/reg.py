import asyncio
import discord

from src.bots.bot import (
    bot,
    _event_queue,
    _bot_loop,
    _worker_task,
    _status_periodic_task,
)
from src.bots.commands.device import register_device_commands
from src.bots.commands.student import register_student_commands
from src.bots.commands.system import register_system_commands
from src.bots.config import (
    get_discord_token,
    get_guild_id,
    is_sync_slash_commands,
)
from src.bots.workers import (
    attendance_event_worker,
    status_periodic_worker,
)
from src.logger import get_logger

logger = get_logger("discord_bot")

# Register all modular commands
register_student_commands(bot)
register_device_commands(bot)
register_system_commands(bot)


@bot.event
async def on_ready() -> None:
    from src.bots import bot as bot_module

    bot_module._bot_loop = asyncio.get_running_loop()
    if bot_module._event_queue is None:
        bot_module._event_queue = asyncio.Queue(maxsize=500)

    logger.info(f"Discord Bot online as {bot.user}")

    if is_sync_slash_commands():
        try:
            # 1. Sync global commands so Discord registers commands for all current and future servers
            synced_global = await bot.tree.sync()
            logger.info(f"Đã sync toàn cầu (global) {len(synced_global)} slash commands.")

            # 2. Sync to all current guilds for instant command availability without waiting for cache propagation
            for g in bot.guilds:
                try:
                    bot.tree.copy_global_to(guild=g)
                    synced_guild = await bot.tree.sync(guild=g)
                    logger.info(f"Đã sync tức thì {len(synced_guild)} slash commands tới server '{g.name}' ({g.id})")
                except Exception as ge:
                    logger.warning(f"Lỗi khi sync commands tới server '{g.name}' ({g.id}): {ge}")

            # 3. If a specific dev guild_id was configured and bot is not in bot.guilds yet, sync it explicitly
            guild_id = get_guild_id()
            if guild_id and not any(g.id == guild_id for g in bot.guilds):
                try:
                    guild_obj = discord.Object(id=guild_id)
                    bot.tree.copy_global_to(guild=guild_obj)
                    synced_dev = await bot.tree.sync(guild=guild_obj)
                    logger.info(f"Đã sync {len(synced_dev)} slash commands tới guild dev cấu hình {guild_id}")
                except Exception as de:
                    logger.warning(f"Lỗi khi sync tới guild dev {guild_id}: {de}")
        except Exception as e:
            logger.warning(f"Lỗi khi đồng bộ slash commands: {e}")

    if bot_module._worker_task is None or bot_module._worker_task.done():
        bot_module._worker_task = bot.loop.create_task(attendance_event_worker())

    if bot_module._status_periodic_task is None or bot_module._status_periodic_task.done():
        bot_module._status_periodic_task = bot.loop.create_task(status_periodic_worker())


@bot.event
async def on_guild_join(guild: discord.Guild) -> None:
    logger.info(f"Bot vừa tham gia server mới: {guild.name} (ID: {guild.id})")
    if is_sync_slash_commands():
        try:
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            logger.info(f"Đã sync tức thì {len(synced)} slash commands cho server mới '{guild.name}' ({guild.id})")
        except Exception as e:
            logger.warning(f"Lỗi khi sync slash commands cho server mới {guild.name}: {e}")


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
