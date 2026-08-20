"""
All Telegram message/callback handlers, registered explicitly via
register_handlers(bot). No decorator-based auto-discovery — see the
docstring in telegram/client.py for why.
"""

import asyncio
import datetime
import logging
import math
import os
import random
import string
import time

import aiofiles
from pyrogram import Client, filters
from pyrogram.enums.parse_mode import ParseMode
from pyrogram.errors import FloodWait
from pyrogram.file_id import FileId, FileType, PHOTO_TYPES
from pyrogram.handlers import CallbackQueryHandler, MessageHandler
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from streambot import StartTime, __version__
from streambot.config import Server, Telegram
from streambot.database import get_database
from streambot.exceptions import FileNotFound
from streambot.telegram.broadcast import send_broadcast
from streambot.telegram.guards import (
    gen_link, gen_linkx, is_channel_banned, is_channel_exist,
    is_user_authorized, is_user_banned, is_user_exist, is_user_joined, verify_user,
)
from streambot.utils.file_info import get_file_ids, get_file_info
from streambot.utils.formatting import get_readable_time, humanbytes
from streambot.utils.translation import BUTTON, LANG

logger = logging.getLogger(__name__)

MEDIA_FILTER = (
    filters.document | filters.video | filters.video_note
    | filters.audio | filters.voice | filters.animation | filters.photo
)

_broadcast_state: dict = {}


def register_handlers(bot: Client, multi_clients: dict, work_loads: dict):
    """Attach every handler to `bot`. Called once at startup, after the
    event loop is fully set up."""

    # ------------------------------------------------------------ /start
    async def start(client: Client, message: Message):
        if not await verify_user(client, message):
            return
        db = get_database()
        arg = message.text.split("_")[-1]

        if arg == "/start":
            caption = LANG.START_TEXT.format(message.from_user.mention, bot.username)
            if Telegram.START_PIC:
                await message.reply_photo(photo=Telegram.START_PIC, caption=caption,
                                           parse_mode=ParseMode.HTML, reply_markup=BUTTON.START_BUTTONS)
            else:
                await message.reply_text(text=caption, parse_mode=ParseMode.HTML,
                                          disable_web_page_preview=True, reply_markup=BUTTON.START_BUTTONS)
            return

        if "stream_" in message.text:
            try:
                file_check = await db.get_file(arg)
                file_id = str(file_check["_id"])
                if file_id == arg:
                    reply_markup, stream_text = await gen_linkx(_id=file_id, bot_username=bot.username)
                    await message.reply_text(text=stream_text, parse_mode=ParseMode.HTML,
                                              disable_web_page_preview=True, reply_markup=reply_markup, quote=True)
            except FileNotFound:
                await message.reply_text("File Not Found")
            except Exception as e:
                await message.reply_text("Something Went Wrong")
                logger.error(e)
        elif "file_" in message.text:
            try:
                file_check = await db.get_file(arg)
                db_id = str(file_check["_id"])
                if db_id == arg:
                    filex = await message.reply_cached_media(
                        file_id=file_check["file_id"], caption=f"**{file_check['file_name']}**"
                    )
                    await asyncio.sleep(3600)
                    for target in (filex, message):
                        try:
                            await target.delete()
                        except Exception:
                            pass
            except FileNotFound:
                await message.reply_text("**File Not Found**")
            except Exception as e:
                await message.reply_text("Something Went Wrong")
                logger.error(e)
        else:
            await message.reply_text("**Invalid Command**")

    # ------------------------------------------------------------- /help
    async def help_handler(client: Client, message: Message):
        if not await verify_user(client, message):
            return
        caption = LANG.HELP_TEXT.format(Telegram.OWNER_ID)
        if Telegram.START_PIC:
            await message.reply_photo(photo=Telegram.START_PIC, caption=caption,
                                       parse_mode=ParseMode.HTML, reply_markup=BUTTON.HELP_BUTTONS)
        else:
            await message.reply_text(text=caption, parse_mode=ParseMode.HTML,
                                      disable_web_page_preview=True, reply_markup=BUTTON.HELP_BUTTONS)

    # ------------------------------------------------------------ /about
    async def about_handler(client: Client, message: Message):
        if not await verify_user(client, message):
            return
        caption = LANG.ABOUT_TEXT.format(bot.fname, __version__)
        if Telegram.START_PIC:
            await message.reply_photo(photo=Telegram.START_PIC, caption=caption,
                                       parse_mode=ParseMode.HTML, reply_markup=BUTTON.ABOUT_BUTTONS)
        else:
            await message.reply_text(text=caption, disable_web_page_preview=True, reply_markup=BUTTON.ABOUT_BUTTONS)

    # ------------------------------------------------------------ /files
    async def my_files(client: Client, message: Message):
        if not await verify_user(client, message):
            return
        db = get_database()
        user_files, total_files = await db.find_files(message.from_user.id, [1, 10])

        file_list = []
        async for x in user_files:
            file_list.append([InlineKeyboardButton(x["file_name"], callback_data=f"myfile_{x['_id']}_1")])
        if total_files > 10:
            file_list.append([
                InlineKeyboardButton("◄", callback_data="N/A"),
                InlineKeyboardButton(f"1/{math.ceil(total_files / 10)}", callback_data="N/A"),
                InlineKeyboardButton("►", callback_data="userfiles_2"),
            ])
        if not file_list:
            file_list.append([InlineKeyboardButton("ᴇᴍᴘᴛʏ", callback_data="N/A")])
        file_list.append([InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close")])
        await message.reply_photo(photo=Telegram.FILE_PIC, caption=f"Total files: {total_files}",
                                   reply_markup=InlineKeyboardMarkup(file_list))

    # ------------------------------------------------------- media intake
    async def private_receive_handler(client: Client, message: Message):
        if not await is_user_authorized(message):
            return
        if await is_user_banned(message):
            return
        await is_user_exist(client, message)
        if Telegram.FORCE_SUB and not await is_user_joined(client, message):
            return

        db = get_database()
        try:
            inserted_id = await db.add_file(get_file_info(message))
            await get_file_ids(False, inserted_id, multi_clients, message, bot)
            reply_markup, stream_text = await gen_link(_id=inserted_id, bot_username=bot.username)
            await message.reply_text(text=stream_text, parse_mode=ParseMode.HTML,
                                      disable_web_page_preview=True, reply_markup=reply_markup, quote=True)
        except FloodWait as e:
            logger.warning(f"FloodWait {e.value}s on upload")
            await asyncio.sleep(e.value)
            await client.send_message(
                chat_id=Telegram.ULOG_CHANNEL,
                text=f"Gᴏᴛ FʟᴏᴏᴅWᴀɪᴛ ᴏғ {e.value}s ғʀᴏᴍ [{message.from_user.first_name}](tg://user?id={message.from_user.id})\n\n"
                     f"**ᴜsᴇʀ ɪᴅ :** `{message.from_user.id}`",
                disable_web_page_preview=True, parse_mode=ParseMode.MARKDOWN,
            )

    async def channel_receive_handler(client: Client, message: Message):
        if await is_channel_banned(client, message):
            return
        await is_channel_exist(client, message)
        db = get_database()
        try:
            inserted_id = await db.add_file(get_file_info(message))
            await get_file_ids(False, inserted_id, multi_clients, message, bot)
            await client.edit_message_reply_markup(
                chat_id=message.chat.id, message_id=message.id,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                    "Dᴏᴡɴʟᴏᴀᴅ ʟɪɴᴋ 📥", url=f"https://t.me/{bot.username}?start=stream_{inserted_id}")]]),
            )
        except FloodWait as e:
            logger.warning(f"FloodWait {e.value}s on channel upload")
            await asyncio.sleep(e.value)
            await client.send_message(
                chat_id=Telegram.ULOG_CHANNEL,
                text=f"ɢᴏᴛ ғʟᴏᴏᴅᴡᴀɪᴛ ᴏғ {e.value}s ғʀᴏᴍ {message.chat.title}\n\n**ᴄʜᴀɴɴᴇʟ ɪᴅ :** `{message.chat.id}`",
                disable_web_page_preview=True,
            )
        except Exception as e:
            await client.send_message(chat_id=Telegram.ULOG_CHANNEL, text=f"**#EʀʀᴏʀTʀᴀᴄᴋʙᴀᴄᴋ:** `{e}`",
                                       disable_web_page_preview=True)
            logger.error(f"Can't edit broadcast message: {e}")

    # --------------------------------------------------------- admin: /status
    async def status_handler(client: Client, message: Message):
        db = get_database()
        loads = "\n".join(f"  • Client {cid}: `{load}` active streams" for cid, load in work_loads.items())
        await message.reply_text(
            text=f"""**Total Users in DB:** `{await db.total_users_count()}`
**Banned Users in DB:** `{await db.total_banned_users_count()}`
**Total Links Generated:** `{await db.total_files()}`

**Uptime:** `{get_readable_time(time.time() - StartTime)}`
**Streaming Clients:** `{len(multi_clients)}` {"(multi-client load balancing on)" if Telegram.MULTI_CLIENT else "(single client)"}
**Auto-Ping:** `{"enabled, every " + str(Server.PING_INTERVAL) + "s" if Server.should_auto_ping() else "disabled"}`
**Current Load:**
{loads or "  • n/a"}""",
            parse_mode=ParseMode.MARKDOWN, quote=True,
        )

    # ----------------------------------------------------------- admin: /ban
    async def ban_handler(client: Client, message: Message):
        db = get_database()
        target_id = message.text.split("/ban ")[-1]
        if await db.is_user_banned(int(target_id)):
            await message.reply_text(text=f"`{target_id}`** is Already Banned** ", parse_mode=ParseMode.MARKDOWN, quote=True)
            return
        try:
            await db.ban_user(int(target_id))
            await db.delete_user(int(target_id))
            await message.reply_text(text=f"`{target_id}`** is Banned** ", parse_mode=ParseMode.MARKDOWN, quote=True)
            if not str(target_id).startswith("-100"):
                await client.send_message(chat_id=target_id, text="**Your Banned to Use The Bot**",
                                           parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        except Exception as e:
            await message.reply_text(text=f"**something went wrong: {e}** ", parse_mode=ParseMode.MARKDOWN, quote=True)

    # --------------------------------------------------------- admin: /unban
    async def unban_handler(client: Client, message: Message):
        db = get_database()
        target_id = message.text.split("/unban ")[-1]
        if not await db.is_user_banned(int(target_id)):
            await message.reply_text(text=f"`{target_id}`** is not Banned** ", parse_mode=ParseMode.MARKDOWN, quote=True)
            return
        try:
            await db.unban_user(int(target_id))
            await message.reply_text(text=f"`{target_id}`** is Unbanned** ", parse_mode=ParseMode.MARKDOWN, quote=True)
            if not str(target_id).startswith("-100"):
                await client.send_message(chat_id=target_id, text="**Your Unbanned now Use can use The Bot**",
                                           parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        except Exception as e:
            await message.reply_text(text=f"** something went wrong: {e}**", parse_mode=ParseMode.MARKDOWN, quote=True)

    # ------------------------------------------------------- admin: /broadcast
    async def broadcast_handler(client: Client, message: Message):
        db = get_database()
        all_users = await db.get_all_users()
        broadcast_msg = message.reply_to_message
        while True:
            broadcast_id = "".join(random.choice(string.ascii_letters) for _ in range(3))
            if not _broadcast_state.get(broadcast_id):
                break
        out = await message.reply_text("Broadcast initiated! You will be notified with log file when all the users are notified.")
        start_time = time.time()
        total_users = await db.total_users_count()
        done = failed = success = 0
        _broadcast_state[broadcast_id] = dict(total=total_users, current=done, failed=failed, success=success)

        async with aiofiles.open("broadcast.txt", "w") as log_file:
            async for user in all_users:
                status, msg = await send_broadcast(int(user["id"]), broadcast_msg)
                if msg is not None:
                    await log_file.write(msg)
                if status == 200:
                    success += 1
                else:
                    failed += 1
                if status == 400:
                    await db.delete_user(user["id"])
                done += 1
                if broadcast_id not in _broadcast_state:
                    break
                _broadcast_state[broadcast_id].update(current=done, failed=failed, success=success)
                try:
                    await out.edit_text(f"Broadcast Status\n\ncurrent: {done}\nfailed:{failed}\nsuccess: {success}")
                except Exception:
                    pass

        _broadcast_state.pop(broadcast_id, None)
        completed_in = datetime.timedelta(seconds=int(time.time() - start_time))
        await asyncio.sleep(3)
        await out.delete()
        summary = f"broadcast completed in `{completed_in}`\n\nTotal users {total_users}.\nTotal done {done}, {success} success and {failed} failed."
        if failed == 0:
            await message.reply_text(text=summary, quote=True)
        else:
            await message.reply_document(document="broadcast.txt", caption=summary, quote=True)
        os.remove("broadcast.txt")

    # ------------------------------------------------------------ admin: /del
    async def delete_handler(client: Client, message: Message):
        db = get_database()
        file_id = message.text.split(" ")[-1]
        try:
            file_info = await db.get_file(file_id)
        except FileNotFound:
            await message.reply_text(text="**ꜰɪʟᴇ ᴀʟʀᴇᴀᴅʏ ᴅᴇʟᴇᴛᴇᴅ**", quote=True)
            return
        await db.delete_one_file(file_info["_id"])
        await db.count_links(file_info["user_id"], "-")
        await message.reply_text(text="**Fɪʟᴇ Dᴇʟᴇᴛᴇᴅ Sᴜᴄᴄᴇssғᴜʟʟʏ !** ", quote=True)

    # --------------------------------------------------------------- callbacks
    async def gen_file_list_button(file_list_no: int, user_id: int):
        db = get_database()
        file_range = [file_list_no * 10 - 10 + 1, file_list_no * 10]
        user_files, total_files = await db.find_files(user_id, file_range)
        file_list = []
        async for x in user_files:
            file_list.append([InlineKeyboardButton(x["file_name"], callback_data=f"myfile_{x['_id']}_{file_list_no}")])
        if total_files > 10:
            file_list.append([
                InlineKeyboardButton("◄", callback_data="userfiles_" + str(file_list_no - 1) if file_list_no > 1 else "N/A"),
                InlineKeyboardButton(f"{file_list_no}/{math.ceil(total_files / 10)}", callback_data="N/A"),
                InlineKeyboardButton("►", callback_data="userfiles_" + str(file_list_no + 1) if total_files > file_list_no * 10 else "N/A"),
            ])
        if not file_list:
            file_list.append([InlineKeyboardButton("ᴇᴍᴘᴛʏ", callback_data="N/A")])
        file_list.append([InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close")])
        return file_list, total_files

    async def gen_file_menu(_id, file_list_no, update: CallbackQuery):
        db = get_database()
        try:
            myfile_info = await db.get_file(_id)
        except FileNotFound:
            await update.answer("File Not Found")
            return

        file_id = FileId.decode(myfile_info["file_id"])
        if file_id.file_type in PHOTO_TYPES:
            file_type = "Image"
        elif file_id.file_type == FileType.VOICE:
            file_type = "Voice"
        elif file_id.file_type in (FileType.VIDEO, FileType.ANIMATION, FileType.VIDEO_NOTE):
            file_type = "Video"
        elif file_id.file_type == FileType.DOCUMENT:
            file_type = "Document"
        elif file_id.file_type == FileType.STICKER:
            file_type = "Sticker"
        elif file_id.file_type == FileType.AUDIO:
            file_type = "Audio"
        else:
            file_type = "Unknown"

        page_link = f"{Server.URL}watch/{myfile_info['_id']}"
        stream_link = f"{Server.URL}dl/{myfile_info['_id']}"
        rows = []
        if "video" in file_type.lower():
            rows.append([InlineKeyboardButton("sᴛʀᴇᴀᴍ", url=page_link), InlineKeyboardButton("ᴅᴏᴡɴʟᴏᴀᴅ", url=stream_link)])
        else:
            rows.append([InlineKeyboardButton("ᴅᴏᴡɴʟᴏᴀᴅ", url=stream_link)])
        rows.append([InlineKeyboardButton("ɢᴇᴛ ғɪʟᴇ", callback_data=f"sendfile_{myfile_info['_id']}"),
                     InlineKeyboardButton("ʀᴇᴠᴏᴋᴇ ғɪʟᴇ", callback_data=f"msgdelete_{myfile_info['_id']}_{file_list_no}")])
        rows.append([InlineKeyboardButton("ʙᴀᴄᴋ", callback_data=f"userfiles_{file_list_no}")])

        TiMe = myfile_info["time"]
        date_str = TiMe if isinstance(TiMe, str) else datetime.datetime.fromtimestamp(TiMe).date()
        await update.edit_message_caption(
            caption="**File Name :** `{}`\n**File Size :** `{}`\n**File Type :** `{}`\n**Created On :** `{}`".format(
                myfile_info["file_name"], humanbytes(int(myfile_info["file_size"])), file_type, date_str),
            reply_markup=InlineKeyboardMarkup(rows),
        )

    async def delete_user_file(_id, file_list_no: int, update: CallbackQuery):
        db = get_database()
        try:
            myfile_info = await db.get_file(_id)
        except FileNotFound:
            await update.answer("File Already Deleted")
            return
        await db.delete_one_file(myfile_info["_id"])
        await db.count_links(update.from_user.id, "-")
        await update.message.edit_caption(
            caption="**Fɪʟᴇ Dᴇʟᴇᴛᴇᴅ Sᴜᴄᴄᴇssғᴜʟʟʏ !**" + (update.message.caption or "").replace(
                "Cᴏɴғɪʀᴍ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴅᴇʟᴇᴛᴇ ᴛʜᴇ Fɪʟᴇ", ""),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ʙᴀᴄᴋ", callback_data="userfiles_1")]]),
        )

    async def delete_user_filex(_id, update: CallbackQuery):
        db = get_database()
        try:
            myfile_info = await db.get_file(_id)
        except FileNotFound:
            await update.answer("File Already Deleted")
            return
        await db.delete_one_file(myfile_info["_id"])
        await db.count_links(update.from_user.id, "-")
        await update.message.edit_caption(
            caption="**Fɪʟᴇ Dᴇʟᴇᴛᴇᴅ Sᴜᴄᴄᴇssғᴜʟʟʏ !**\n\n",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close")]]),
        )

    async def callback_handler(client: Client, update: CallbackQuery):
        db = get_database()
        cmd = update.data.split("_")
        action = cmd[0]

        if action == "home":
            await update.message.edit_text(text=LANG.START_TEXT.format(update.from_user.mention, bot.username),
                                            disable_web_page_preview=True, reply_markup=BUTTON.START_BUTTONS)
        elif action == "help":
            await update.message.edit_text(text=LANG.HELP_TEXT.format(Telegram.OWNER_ID),
                                            disable_web_page_preview=True, reply_markup=BUTTON.HELP_BUTTONS)
        elif action == "about":
            await update.message.edit_text(text=LANG.ABOUT_TEXT.format(bot.fname, __version__),
                                            disable_web_page_preview=True, reply_markup=BUTTON.ABOUT_BUTTONS)
        elif action == "N/A":
            await update.answer("N/A", True)
        elif action == "close":
            await update.message.delete()
        elif action == "msgdelete":
            await update.message.edit_caption(
                caption="**Cᴏɴғɪʀᴍ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴅᴇʟᴇᴛᴇ ᴛʜᴇ Fɪʟᴇ**\n\n",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("ʏᴇs", callback_data=f"msgdelyes_{cmd[1]}_{cmd[2]}"),
                    InlineKeyboardButton("ɴᴏ", callback_data=f"myfile_{cmd[1]}_{cmd[2]}")]]),
            )
        elif action == "msgdelyes":
            await delete_user_file(cmd[1], int(cmd[2]), update)
        elif action == "msgdelpvt":
            await update.message.edit_caption(
                caption="**Cᴏɴғɪʀᴍ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴅᴇʟᴇᴛᴇ ᴛʜᴇ Fɪʟᴇ**\n\n",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("ʏᴇs", callback_data=f"msgdelpvtyes_{cmd[1]}"),
                    InlineKeyboardButton("ɴᴏ", callback_data=f"mainstream_{cmd[1]}")]]),
            )
        elif action == "msgdelpvtyes":
            await delete_user_filex(cmd[1], update)
        elif action == "mainstream":
            reply_markup, stream_text = await gen_link(_id=cmd[1], bot_username=bot.username)
            await update.message.edit_text(text=stream_text, parse_mode=ParseMode.HTML,
                                            disable_web_page_preview=True, reply_markup=reply_markup)
        elif action == "userfiles":
            file_list, total_files = await gen_file_list_button(int(cmd[1]), update.from_user.id)
            await update.message.edit_caption(caption=f"Total files: {total_files}",
                                               reply_markup=InlineKeyboardMarkup(file_list))
        elif action == "myfile":
            await gen_file_menu(cmd[1], cmd[2], update)
        elif action == "sendfile":
            myfile = await db.get_file(cmd[1])
            await update.answer(f"Sending File {myfile['file_name']}")
            await update.message.reply_cached_media(myfile["file_id"], caption=f"**{myfile['file_name']}**")
        else:
            await update.message.delete()

    # --------------------------------------------------------------- register
    owner_filter = filters.private & filters.user(Telegram.OWNER_ID)
    bot.add_handler(MessageHandler(start, filters.command("start") & filters.private))
    bot.add_handler(MessageHandler(help_handler, filters.command("help") & filters.private))
    bot.add_handler(MessageHandler(about_handler, filters.command("about") & filters.private))
    bot.add_handler(MessageHandler(my_files, filters.command("files") & filters.private))
    bot.add_handler(MessageHandler(private_receive_handler, filters.private & MEDIA_FILTER), group=4)
    bot.add_handler(MessageHandler(
        channel_receive_handler,
        filters.channel & ~filters.forwarded & ~filters.media_group & MEDIA_FILTER,
    ))
    bot.add_handler(MessageHandler(status_handler, filters.command("status") & owner_filter))
    bot.add_handler(MessageHandler(ban_handler, filters.command("ban") & owner_filter))
    bot.add_handler(MessageHandler(unban_handler, filters.command("unban") & owner_filter))
    bot.add_handler(MessageHandler(broadcast_handler, filters.command("broadcast") & owner_filter & filters.reply))
    bot.add_handler(MessageHandler(delete_handler, filters.command("del") & owner_filter))
    bot.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("All handlers registered.")
