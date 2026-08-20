"""Pushes the bot's command list to Telegram on every startup."""

import logging

from pyrogram import Client
from pyrogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from streambot.config import Telegram

logger = logging.getLogger(__name__)

PUBLIC_COMMANDS = [
    BotCommand("start", "Check if the bot is alive"),
    BotCommand("files", "Get your list of generated links"),
]

OWNER_COMMANDS = PUBLIC_COMMANDS + [
    BotCommand("status", "Show bot/server stats"),
    BotCommand("ban", "Ban a user or channel by ID"),
    BotCommand("unban", "Unban a user or channel by ID"),
    BotCommand("broadcast", "Reply to a message to broadcast it to all users"),
    BotCommand("del", "Delete a stored file by its link ID"),
]


async def update_bot_commands(client: Client):
    try:
        await client.set_bot_commands(PUBLIC_COMMANDS, scope=BotCommandScopeDefault())
        logger.info(f"Updated default bot command list ({len(PUBLIC_COMMANDS)} commands).")
    except Exception as e:
        logger.warning(f"Failed to set default bot commands: {e}")

    if Telegram.OWNER_ID:
        try:
            await client.set_bot_commands(OWNER_COMMANDS, scope=BotCommandScopeChat(chat_id=Telegram.OWNER_ID))
            logger.info(f"Updated owner-scoped bot command list ({len(OWNER_COMMANDS)} commands).")
        except Exception as e:
            logger.debug(f"Could not set owner-scoped bot commands yet: {e}")
