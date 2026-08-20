"""
Pyrogram client construction.

Deliberately does NOT use Pyrogram's `plugins={"root": ...}` auto-loading.
That mechanism silently imports handler files at Client-construction time
and binds decorators to whatever event loop exists *then* — which is
exactly what caused the "bot builds fine, connects fine, but never
responds to any message" bug in the previous version, once uvloop swapped
the event loop in afterward. Handlers here are registered explicitly, in
`register_handlers()`, called after the event loop is fully set up — so
there's no import-time magic and no ordering trap.
"""

import asyncio
import logging

from pyrogram import Client

from streambot.config import Telegram, Performance

logger = logging.getLogger(__name__)


def create_bot() -> Client:
    return Client(
        name=Telegram.SESSION_NAME,
        api_id=Telegram.API_ID,
        api_hash=Telegram.API_HASH,
        workdir=".",
        bot_token=Telegram.BOT_TOKEN,
        sleep_threshold=Telegram.SLEEP_THRESHOLD,
        workers=Telegram.WORKERS,
        no_updates=Telegram.SECONDARY,  # secondary instances don't need updates at all
        max_concurrent_transmissions=Performance.MAX_CONCURRENT_TRANSMISSIONS,
    )


async def start_extra_clients(bot: Client, multi_clients: dict, work_loads: dict):
    """Start any MULTI_TOKEN* clients for load-balanced streaming, and
    always register the primary bot itself as client 0 — a client missing
    from this dict silently breaks streaming for it, which is exactly what
    happened in an earlier version of this bot."""
    from os import environ

    multi_clients[0] = bot
    work_loads[0] = 0

    all_tokens = dict(
        (i + 1, t)
        for i, (_, t) in enumerate(
            filter(lambda kv: kv[0].startswith("MULTI_TOKEN"), sorted(environ.items()))
        )
    )
    if not all_tokens:
        logger.info("No MULTI_TOKEN* found, running single-client.")
        return

    async def start_one(client_id: int, token: str, retries: int = 2):
        for attempt in range(1, retries + 1):
            try:
                is_session_string = len(token) >= 100
                client = await Client(
                    name=str(client_id),
                    api_id=Telegram.API_ID,
                    api_hash=Telegram.API_HASH,
                    bot_token=None if is_session_string else token,
                    session_string=token if is_session_string else None,
                    sleep_threshold=Telegram.SLEEP_THRESHOLD,
                    no_updates=True,
                    in_memory=True,
                    max_concurrent_transmissions=Performance.MAX_CONCURRENT_TRANSMISSIONS,
                ).start()
                client.id = (await client.get_me()).id
                logger.info(f"Started extra client {client_id}.")
                return client_id, client
            except Exception:
                logger.error(f"Failed to start client {client_id} (attempt {attempt}/{retries})", exc_info=True)
                if attempt < retries:
                    await asyncio.sleep(3 * attempt)
        logger.error(f"Giving up on client {client_id} after {retries} attempts.")
        return None

    results = await asyncio.gather(*[start_one(i, t) for i, t in all_tokens.items()])
    started = [r for r in results if r is not None]
    if len(results) - len(started):
        logger.warning(f"{len(results) - len(started)} extra client(s) failed to start and were skipped.")

    multi_clients.update(dict(started))
    if len(multi_clients) > 1:
        Telegram.MULTI_CLIENT = True
        logger.info(f"Multi-client mode enabled ({len(multi_clients)} clients).")
