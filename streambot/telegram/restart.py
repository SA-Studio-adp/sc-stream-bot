"""
Owner-only /restart support: clear caches, stop cleanly, then replace this process in place.

Why exec instead of exiting: the container keeps running (no dependence on the host's
restart policy, no waiting for the entrypoint's `pip install`), the environment is kept,
and the listening socket is closed by the OS (Python sockets are not inherited across exec).
Anything held only in memory (Telegram file-id cache, stream sessions, track lists, running
ffmpeg jobs) is gone afterwards; MongoDB data, the Telegram session file and your files stay.
"""

import asyncio
import gc
import json
import logging
import os
import sys
import time
from pathlib import Path

from streambot.config import Media

logger = logging.getLogger(__name__)

STATE_FILE = Path(os.environ.get("RESTART_STATE_FILE", "/tmp/streambot-restart.json"))
STATE_MAX_AGE = 600          # ignore a leftover state file older than this (seconds)
STOP_TIMEOUT = 8             # per client, so a hung connection cannot block the restart

_restarting = False
_task = None                 # keep a reference so the task is not garbage-collected


def is_restarting() -> bool:
    return _restarting


def clear_caches() -> dict:
    """Forget cached track lists / subtitles and stop ffmpeg jobs; then free Python memory."""
    stats = {"jobs_killed": 0, "track_lists": 0, "subtitle_files": 0, "bytes_freed": 0}
    if Media.ENABLED:
        try:
            from streambot.web import media_tools
            stats = media_tools.clear_all()
        except Exception as e:  # never let a cache problem block a restart
            logger.warning(f"clear_all failed: {e}")
    gc.collect()
    return stats


def describe(stats: dict) -> str:
    kb = stats.get("bytes_freed", 0) / 1024
    return (
        f"• track lists cleared: `{stats.get('track_lists', 0)}`\n"
        f"• subtitle files removed: `{stats.get('subtitle_files', 0)}` ({kb:.0f} KB)\n"
        f"• ffmpeg jobs stopped: `{stats.get('jobs_killed', 0)}`"
    )


def save_state(chat_id: int, message_id: int, summary: str) -> None:
    try:
        STATE_FILE.write_text(json.dumps({
            "chat_id": chat_id, "message_id": message_id, "summary": summary, "ts": time.time(),
        }))
    except OSError as e:
        logger.warning(f"Could not save restart state: {e}")


async def _stop_clients(clients) -> None:
    for c in clients:
        try:
            await asyncio.wait_for(c.stop(), STOP_TIMEOUT)
        except Exception as e:
            logger.warning(f"Client stop failed/timed out during restart: {e}")


async def restart_process(clients, delay: float = 1.0, exec_fn=os.execv) -> None:
    """Give the 'Restarting…' message time to be sent, stop the clients, then re-exec."""
    await asyncio.sleep(delay)
    await _stop_clients(clients)
    logger.warning("Restarting process now.")
    try:
        exec_fn(sys.executable, [sys.executable, "-m", "streambot"])
    except Exception as e:
        # exec failed after the clients were stopped: exit non-zero so the host restarts us
        logger.error(f"exec failed ({e}); exiting so the platform restarts the service")
        os._exit(1)


def schedule_restart(clients, delay: float = 1.0, exec_fn=os.execv) -> None:
    global _restarting, _task
    _restarting = True
    unique = list({id(c): c for c in clients}.values())
    _task = asyncio.get_running_loop().create_task(restart_process(unique, delay, exec_fn))


async def announce_if_restarted(bot) -> None:
    """Called once at startup: turn the 'Restarting…' message into 'Back online'."""
    try:
        data = json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return
    try:
        STATE_FILE.unlink()
    except OSError:
        pass
    took = time.time() - float(data.get("ts", 0))
    if took > STATE_MAX_AGE or took < 0:
        return
    from pyrogram.enums.parse_mode import ParseMode
    text = f"✅ **Back online** after `{took:.0f}s`\n\n**Cleared before restart:**\n{data.get('summary', '')}"
    try:
        await bot.edit_message_text(data["chat_id"], data["message_id"], text, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        try:
            await bot.send_message(data["chat_id"], text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.warning(f"Could not announce restart: {e}")
