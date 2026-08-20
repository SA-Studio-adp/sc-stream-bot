"""
User/channel access checks and stream-link generation. Kept behaviorally
identical to the previous version — same DB fields, same link format
(/watch/{id}, /dl/{id}) — so old links and existing user/ban records
keep working unchanged.
"""

import asyncio
import logging
from typing import Union

from pyrogram.enums.parse_mode import ParseMode
from pyrogram.errors import FloodWait, UserNotParticipant
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from streambot.config import Server, Telegram
from streambot.database import get_database
from streambot.utils.formatting import humanbytes
from streambot.utils.translation import LANG

logger = logging.getLogger(__name__)


async def get_invite_link(bot, chat_id: Union[str, int]):
    try:
        return await bot.create_chat_invite_link(chat_id=chat_id)
    except FloodWait as e:
        logger.warning(f"FloodWait {e.value}s creating invite link")
        await asyncio.sleep(e.value)
        return await get_invite_link(bot, chat_id)


async def is_user_joined(bot, message: Message) -> bool:
    if Telegram.FORCE_SUB_ID and Telegram.FORCE_SUB_ID.startswith("-100"):
        channel_chat_id = int(Telegram.FORCE_SUB_ID)
    elif Telegram.FORCE_SUB_ID:
        channel_chat_id = Telegram.FORCE_SUB_ID
    else:
        return True

    try:
        user = await bot.get_chat_member(chat_id=channel_chat_id, user_id=message.from_user.id)
        if str(user.status) == "BANNED":
            await message.reply_text(
                text=LANG.BAN_TEXT.format(Telegram.OWNER_ID),
                parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True,
            )
            return False
    except UserNotParticipant:
        invite_link = await get_invite_link(bot, chat_id=channel_chat_id)
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("❆ Jᴏɪɴ Oᴜʀ Cʜᴀɴɴᴇʟ ❆", url=invite_link.invite_link)]])
        if Telegram.VERIFY_PIC:
            ver = await message.reply_photo(
                photo=Telegram.VERIFY_PIC,
                caption="<i>Jᴏɪɴ ᴍʏ ᴜᴘᴅᴀᴛᴇ ᴄʜᴀɴɴᴇʟ ᴛᴏ ᴜsᴇ ᴍᴇ 🔐</i>",
                parse_mode=ParseMode.HTML, reply_markup=markup,
            )
        else:
            ver = await message.reply_text(
                text="<i>Jᴏɪɴ ᴍʏ ᴜᴘᴅᴀᴛᴇ ᴄʜᴀɴɴᴇʟ ᴛᴏ ᴜsᴇ ᴍᴇ 🔐</i>",
                reply_markup=markup, parse_mode=ParseMode.HTML,
            )
        await asyncio.sleep(30)
        for target in (ver, message):
            try:
                await target.delete()
            except Exception:
                pass
        return False
    except Exception:
        await message.reply_text(
            text=f"<i>Sᴏᴍᴇᴛʜɪɴɢ ᴡʀᴏɴɢ ᴄᴏɴᴛᴀᴄᴛ ᴍʏ ᴅᴇᴠᴇʟᴏᴘᴇʀ</i> "
                 f"<b><a href='https://t.me/{Telegram.UPDATES_CHANNEL}'>[ ᴄʟɪᴄᴋ ʜᴇʀᴇ ]</a></b>",
            parse_mode=ParseMode.HTML, disable_web_page_preview=True,
        )
        return False
    return True


async def gen_link(_id, bot_username: str):
    db = get_database()
    file_info = await db.get_file(_id)
    file_name = file_info["file_name"]
    file_size = humanbytes(file_info["file_size"])
    mime_type = file_info["mime_type"]

    page_link = f"{Server.URL}watch/{_id}"
    stream_link = f"{Server.URL}dl/{_id}"
    file_link = f"https://t.me/{bot_username}?start=file_{_id}"

    if "video" in mime_type:
        stream_text = LANG.STREAM_TEXT.format(file_name, file_size, stream_link, page_link, file_link)
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("sᴛʀᴇᴀᴍ", url=page_link), InlineKeyboardButton("ᴅᴏᴡɴʟᴏᴀᴅ", url=stream_link)],
            [InlineKeyboardButton("ɢᴇᴛ ғɪʟᴇ", url=file_link), InlineKeyboardButton("ʀᴇᴠᴏᴋᴇ ғɪʟᴇ", callback_data=f"msgdelpvt_{_id}")],
            [InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close")],
        ])
    else:
        stream_text = LANG.STREAM_TEXT_X.format(file_name, file_size, stream_link, file_link)
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("ᴅᴏᴡɴʟᴏᴀᴅ", url=stream_link)],
            [InlineKeyboardButton("ɢᴇᴛ ғɪʟᴇ", url=file_link), InlineKeyboardButton("ʀᴇᴠᴏᴋᴇ ғɪʟᴇ", callback_data=f"msgdelpvt_{_id}")],
            [InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close")],
        ])
    return reply_markup, stream_text


async def gen_linkx(_id, bot_username: str):
    """Same as gen_link but for the compact /start deep-link reply (no
    revoke/close buttons, since there's no owning chat context)."""
    db = get_database()
    file_info = await db.get_file(_id)
    file_name = file_info["file_name"]
    mime_type = file_info["mime_type"]
    file_size = humanbytes(file_info["file_size"])

    page_link = f"{Server.URL}watch/{_id}"
    stream_link = f"{Server.URL}dl/{_id}"
    file_link = f"https://t.me/{bot_username}?start=file_{_id}"

    if "video" in mime_type:
        stream_text = LANG.STREAM_TEXT_X.format(file_name, file_size, stream_link, page_link)
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("sᴛʀᴇᴀᴍ", url=page_link), InlineKeyboardButton("ᴅᴏᴡɴʟᴏᴀᴅ", url=stream_link)]
        ])
    else:
        stream_text = LANG.STREAM_TEXT_X.format(file_name, file_size, stream_link, file_link)
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("ᴅᴏᴡɴʟᴏᴀᴅ", url=stream_link)]])
    return reply_markup, stream_text


async def is_user_banned(message: Message) -> bool:
    db = get_database()
    if await db.is_user_banned(message.from_user.id):
        await message.reply_text(
            text=LANG.BAN_TEXT.format(Telegram.OWNER_ID),
            parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True,
        )
        return True
    return False


async def is_channel_banned(bot, message: Message) -> bool:
    db = get_database()
    if await db.is_user_banned(message.chat.id):
        await bot.edit_message_reply_markup(
            chat_id=message.chat.id, message_id=message.id,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ᴄʜᴀɴɴᴇʟ ɪs ʙᴀɴɴᴇᴅ", callback_data="N/A")]]),
        )
        return True
    return False


async def is_user_authorized(message: Message) -> bool:
    if Telegram.AUTH_USERS:
        user_id = message.from_user.id
        if user_id == Telegram.OWNER_ID:
            return True
        if user_id not in Telegram.AUTH_USERS:
            await message.reply_text(
                text="Yᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴛᴏ ᴜsᴇ ᴛʜɪs ʙᴏᴛ.",
                parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True,
            )
            return False
    return True


async def is_user_exist(bot, message: Message):
    db = get_database()
    if not await db.get_user(message.from_user.id):
        await db.add_user(message.from_user.id)
        await bot.send_message(
            Telegram.ULOG_CHANNEL,
            f"**#NᴇᴡUsᴇʀ**\n**⬩ ᴜsᴇʀ ɴᴀᴍᴇ :** [{message.from_user.first_name}](tg://user?id={message.from_user.id})\n"
            f"**⬩ ᴜsᴇʀ ɪᴅ :** `{message.from_user.id}`",
        )


async def is_channel_exist(bot, message: Message):
    db = get_database()
    if not await db.get_user(message.chat.id):
        await db.add_user(message.chat.id)
        members = await bot.get_chat_members_count(message.chat.id)
        await bot.send_message(
            Telegram.ULOG_CHANNEL,
            f"**#NᴇᴡCʜᴀɴɴᴇʟ** \n**⬩ ᴄʜᴀᴛ ɴᴀᴍᴇ :** `{message.chat.title}`\n"
            f"**⬩ ᴄʜᴀᴛ ɪᴅ :** `{message.chat.id}`\n**⬩ ᴛᴏᴛᴀʟ ᴍᴇᴍʙᴇʀs :** `{members}`",
        )


async def verify_user(bot, message: Message) -> bool:
    try:
        if not await is_user_authorized(message):
            return False
        if await is_user_banned(message):
            return False
        await is_user_exist(bot, message)
        if Telegram.FORCE_SUB and not await is_user_joined(bot, message):
            return False
        return True
    except Exception as e:
        # Never let an unexpected error (DB hiccup, bad channel ID, etc.)
        # make the bot look completely unresponsive.
        logger.error(f"verify_user failed: {e}")
        try:
            await message.reply_text(
                "Something went wrong on my end. Please try again in a moment; "
                "if it keeps happening, contact the bot owner."
            )
        except Exception:
            pass
        return False
