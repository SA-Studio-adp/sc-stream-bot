"""
Entrypoint. Order here is deliberate and matters:

1. uvloop is installed before ANYTHING else touches asyncio or constructs
   a Pyrogram Client — Pyrogram binds internal async primitives (its
   update-dispatch queue, locks) to whatever loop exists at construction
   time. Installing uvloop afterward would leave those primitives attached
   to a loop that's never actually run, which silently breaks incoming
   message handling (the exact bug that hit the previous version).
2. Config is validated before anything connects to anything, so a bad
   deployment fails in the first second with a readable message instead
   of a deep traceback.
3. Handlers are registered explicitly (register_handlers), not through
   Pyrogram's plugins= auto-discovery — see telegram/handlers.py.
"""

import asyncio
import logging
import sys
import traceback

try:
    import uvloop
    uvloop.install()
    _using_uvloop = True
except ImportError:
    _using_uvloop = False

from aiohttp import web
from pyrogram import idle

from streambot.config import Server, Telegram, validate_and_bind
from streambot.database import get_database, init_database
from streambot.logging_setup import configure_logging
from streambot.telegram.bot_commands import update_bot_commands
from streambot.telegram.client import create_bot, start_extra_clients
from streambot.telegram.handlers import register_handlers
from streambot.telegram.keep_alive import keep_alive
from streambot.web.app import build_web_app

configure_logging()
logger = logging.getLogger(__name__)

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

multi_clients: dict = {}
work_loads: dict = {}


async def start_services():
    validate_and_bind()

    print("-------------------- Initializing Telegram Bot --------------------")
    print(f"Event loop: {'uvloop (fast)' if _using_uvloop else 'asyncio default'}")

    print("Checking database connectivity...")
    init_database(Telegram.DATABASE_URL, Telegram.SESSION_NAME)
    if await get_database().ping():
        print("Database reachable.")
    else:
        print(
            "!! WARNING: Could not reach MongoDB with the configured DATABASE_URL. "
            "Every command that touches the database will hang or fail until this "
            "is fixed. Common cause: your Atlas cluster's Network Access list doesn't "
            "include this host's IP — add 0.0.0.0/0 there, or double check DATABASE_URL."
        )
    print("------------------------------ DONE ------------------------------\n")

    bot = create_bot()
    await bot.start()
    bot_info = await bot.get_me()
    bot.id = bot_info.id
    bot.username = bot_info.username
    bot.fname = bot_info.first_name

    register_handlers(bot, multi_clients, work_loads)

    print("------------------- Updating Bot Commands -------------------")
    await update_bot_commands(bot)
    print("------------------------------ DONE ------------------------------\n")

    print("---------------------- Initializing Clients ----------------------")
    await start_extra_clients(bot, multi_clients, work_loads)
    print("------------------------------ DONE ------------------------------\n")

    print("--------------------- Initializing Web Server ---------------------")
    web_app = build_web_app(bot, multi_clients, work_loads)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, Server.BIND_ADDRESS, Server.PORT)
    await site.start()
    print("------------------------------ DONE ------------------------------\n")

    print("--------------------- Starting Keep-Alive Task ---------------------")
    asyncio.create_task(keep_alive())
    print("------------------------------ DONE ------------------------------\n")

    print("------------------------- Service Started -------------------------")
    print(f"                        bot =>> {bot_info.first_name}")
    if bot_info.dc_id:
        print(f"                        DC ID =>> {bot_info.dc_id}")
    print(f" URL =>> {Server.URL}")
    print("---------------------------------------------------------------------")

    return bot, runner


async def cleanup(bot, runner):
    try:
        await runner.cleanup()
    except Exception as e:
        logger.debug(f"Error during web server cleanup: {e}")
    try:
        await bot.stop()
    except Exception as e:
        logger.debug(f"Error during bot stop: {e}")


if __name__ == "__main__":
    bot_ref = runner_ref = None
    try:
        bot_ref, runner_ref = loop.run_until_complete(start_services())
        loop.run_until_complete(idle())
    except KeyboardInterrupt:
        pass
    except Exception:
        logging.error(traceback.format_exc())
    finally:
        if bot_ref and runner_ref:
            try:
                loop.run_until_complete(cleanup(bot_ref, runner_ref))
            except Exception as e:
                logger.debug(f"Error during cleanup: {e}")
        loop.stop()
        print("------------------------ Stopped Services ------------------------")
