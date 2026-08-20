"""Self-ping keep-alive so free-tier hosts don't sleep this process."""

import asyncio
import logging

import aiohttp

from streambot.config import Server

logger = logging.getLogger(__name__)


async def _ping_once(session: aiohttp.ClientSession) -> bool:
    url = Server.URL.rstrip("/") + "/ping"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            await resp.read()
            return resp.status == 200
    except Exception as e:
        logger.warning(f"Keep-alive ping failed ({url}): {e}")
        return False


async def keep_alive():
    if not Server.should_auto_ping():
        logger.info("Auto-ping disabled (no public URL detected / AUTO_PING=false).")
        return

    interval = max(Server.PING_INTERVAL, 60)
    logger.info(f"Auto-ping enabled — pinging {Server.URL}ping every {interval}s")
    await asyncio.sleep(10)

    consecutive_failures = 0
    async with aiohttp.ClientSession() as session:
        while True:
            ok = await _ping_once(session)
            consecutive_failures = 0 if ok else consecutive_failures + 1
            if consecutive_failures and consecutive_failures % 5 == 0:
                logger.warning(
                    f"Keep-alive has failed {consecutive_failures} times in a row — "
                    "check that Server.URL / FQDN is reachable from the internet."
                )
            await asyncio.sleep(interval)
