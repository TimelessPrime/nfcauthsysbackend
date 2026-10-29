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

    if bot_module._worker_task is None or bot_module._worker_task.done():
        bot_module._worker_task = bot.loop.create_task(attendance_event_worker())

    if bot_module._status_periodic_task is None or bot_module._status_periodic_task.done():
        bot_module._status_periodic_task = bot.loop.create_task(status_periodic_worker())


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
