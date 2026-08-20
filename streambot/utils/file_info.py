"""
Everything to do with extracting metadata from a Telegram Message/media,
and re-posting media to the log channel so every Pyrogram client (in
multi-client mode) has its own valid file_id for streaming.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from pyrogram import Client
from pyrogram.enums import ChatType
from pyrogram.enums.parse_mode import ParseMode
from pyrogram.file_id import FileId
from pyrogram.types import Message

from streambot.config import Telegram
from streambot.database import get_database

logger = logging.getLogger(__name__)

MEDIA_ATTRS = (
    "audio", "document", "photo", "sticker",
    "animation", "video", "voice", "video_note",
)


def get_media_from_message(message: Message) -> Any:
    for attr in MEDIA_ATTRS:
        media = getattr(message, attr, None)
        if media:
            return media
    return None


def get_media_file_size(message: Message):
    media = get_media_from_message(message)
    return getattr(media, "file_size", None)


def get_name(media_msg: Message | FileId) -> str:
    """Derive a display filename. Defensive against being handed neither
    a real Message nor a real FileId (can happen when there's no live
    chat message behind a request, e.g. a direct download link) — in that
    case falls straight through to a generated placeholder name instead
    of crashing."""
    file_name = ""
    if isinstance(media_msg, Message):
        media = get_media_from_message(media_msg)
        file_name = getattr(media, "file_name", "") or ""
    elif isinstance(media_msg, FileId):
        file_name = getattr(media_msg, "file_name", "") or ""

    if file_name:
        return file_name

    if isinstance(media_msg, Message) and media_msg.media:
        media_type = media_msg.media.value
    elif isinstance(media_msg, FileId) and media_msg.file_type:
        media_type = media_msg.file_type.name.lower()
    else:
        media_type = "file"

    ext_map = {
        "photo": "jpg", "audio": "mp3", "voice": "ogg",
        "video": "mp4", "animation": "mp4", "video_note": "mp4",
        "sticker": "webp",
    }
    ext = ext_map.get(media_type)
    ext = f".{ext}" if ext else ""
    date = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return f"{media_type}-{date}{ext}"


def get_file_info(message: Message) -> dict:
    media = get_media_from_message(message)
    user_idx = (
        message.from_user.id if message.chat.type == ChatType.PRIVATE else message.chat.id
    )
    return {
        "user_id": user_idx,
        "file_id": getattr(media, "file_id", ""),
        "file_unique_id": getattr(media, "file_unique_id", ""),
        "file_name": get_name(message),
        "file_size": getattr(media, "file_size", 0),
        "mime_type": getattr(media, "mime_type", "None/unknown"),
    }


async def send_file(client: Client, db_id, file_id: str, message, fallback_file_name: str = None) -> Message:
    """Re-post the media to FLOG_CHANNEL so `client` has its own copy with
    a file_id valid for it specifically (needed for multi-client mode).

    `message` is the original chat Message when this came from a live
    upload/command, but may not be a real Message at all when it's
    triggered by a direct stream link with no chat context — in that case
    we fall back to the file's already-known name from the database and
    skip the "requested by" log line, since there's nothing to attribute
    it to.
    """
    is_real_message = isinstance(message, Message)

    if is_real_message:
        file_caption = getattr(message, "caption", None) or get_name(message)
    else:
        file_caption = fallback_file_name or "file"

    log_msg = await client.send_cached_media(
        chat_id=Telegram.FLOG_CHANNEL, file_id=file_id, caption=f"**{file_caption}**"
    )

    if not is_real_message:
        return log_msg

    if message.chat.type == ChatType.PRIVATE:
        await log_msg.reply_text(
            text=f"**RᴇQᴜᴇꜱᴛᴇᴅ ʙʏ :** [{message.from_user.first_name}](tg://user?id={message.from_user.id})\n"
                 f"**Uꜱᴇʀ ɪᴅ :** `{message.from_user.id}`\n**Fɪʟᴇ ɪᴅ :** `{db_id}`",
            disable_web_page_preview=True, parse_mode=ParseMode.MARKDOWN, quote=True,
        )
    else:
        await log_msg.reply_text(
            text=f"**RᴇQᴜᴇꜱᴛᴇᴅ ʙʏ :** {message.chat.title} \n**Cʜᴀɴɴᴇʟ ɪᴅ :** `{message.chat.id}`\n"
                 f"**Fɪʟᴇ ɪᴅ :** `{db_id}`",
            disable_web_page_preview=True, parse_mode=ParseMode.MARKDOWN, quote=True,
        )
    return log_msg


async def update_file_id(msg_id: int, multi_clients: dict) -> dict:
    """Fetch the log message with every multi-client and record each
    client's own file_id for it."""
    file_ids = {}
    for client_id, client in multi_clients.items():
        log_msg = await client.get_messages(Telegram.FLOG_CHANNEL, msg_id)
        media = get_media_from_message(log_msg)
        file_ids[str(client.id)] = getattr(media, "file_id", "")
    return file_ids


async def get_file_ids(client, db_id: str, multi_clients: dict, message, main_bot) -> Optional[FileId]:
    """Resolve (and lazily populate) the FileId a specific client needs to
    stream this file. `client` may be falsy to mean "just populate every
    client's file_id, I don't need one back right now"."""
    db = get_database()
    file_info = await db.get_file(db_id)

    if "file_ids" not in file_info or not client:
        log_msg = await send_file(main_bot, db_id, file_info["file_id"], message, file_info.get("file_name"))
        await db.update_file_ids(db_id, await update_file_id(log_msg.id, multi_clients))
        if not client:
            return None
        file_info = await db.get_file(db_id)

    file_id_info = file_info.setdefault("file_ids", {})
    if str(client.id) not in file_id_info:
        log_msg = await send_file(main_bot, db_id, file_info["file_id"], message, file_info.get("file_name"))
        msg = await client.get_messages(Telegram.FLOG_CHANNEL, log_msg.id)
        media = get_media_from_message(msg)
        file_id_info[str(client.id)] = getattr(media, "file_id", "")
        await db.update_file_ids(db_id, file_id_info)

    file_id = FileId.decode(file_id_info[str(client.id)])
    file_id.file_size = file_info["file_size"]
    file_id.mime_type = file_info["mime_type"]
    file_id.file_name = file_info["file_name"]
    file_id.unique_id = file_info["file_unique_id"]
    return file_id
