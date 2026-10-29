import asyncio
import discord
from discord.ext import commands
from src.bots.config import get_bot_prefix

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix=get_bot_prefix(),
    intents=intents,
    help_command=None,
)

_event_queue: asyncio.Queue[dict] | None = None
_bot_loop: asyncio.AbstractEventLoop | None = None
_worker_task: asyncio.Task[None] | None = None
_status_periodic_task: asyncio.Task[None] | None = None
_recent_unknown_cards: dict[str, float] = {}
_recent_notified_students: dict[str, float] = {}
