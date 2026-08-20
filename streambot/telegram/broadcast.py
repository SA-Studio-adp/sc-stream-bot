import asyncio
import logging
import traceback

from pyrogram.errors import FloodWait, InputUserDeactivated, PeerIdInvalid, UserIsBlocked

logger = logging.getLogger(__name__)


async def send_broadcast(user_id: int, message):
    try:
        await message.copy(chat_id=user_id)
        return 200, None
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await send_broadcast(user_id, message)
    except InputUserDeactivated:
        return 400, f"{user_id} : deactivated\n"
    except UserIsBlocked:
        return 400, f"{user_id} : blocked the bot\n"
    except PeerIdInvalid:
        return 400, f"{user_id} : user id invalid\n"
    except Exception:
        return 500, f"{user_id} : {traceback.format_exc()}\n"
