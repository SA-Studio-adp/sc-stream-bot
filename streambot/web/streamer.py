"""
Fetches raw file bytes from Telegram's MTProto layer in chunks.
"""

import asyncio
import logging
from typing import Dict, Union

from pyrogram import Client, raw, utils
from pyrogram.errors import AuthBytesInvalid, FloodWait
from pyrogram.file_id import FileId, FileType, ThumbnailSource
from pyrogram.session import Auth, Session

from streambot.config import Performance
from streambot.utils.file_info import get_file_ids

logger = logging.getLogger(__name__)

# Substrings that show up in pyrogram's own error messages when a media
# session's underlying TCP transport has died (e.g. after a network blip)
# but the Session object itself is still cached as "good". Once we see
# one of these, the cached session for that DC must be thrown away, or
# every subsequent request to that DC retries the same dead connection
# forever — this was the cause of "a handful of files just never load"
# even though everything else works: those files happened to live on the
# one DC whose session died.
_DEAD_TRANSPORT_MARKERS = ("closed=True", "handler is closed", "transport is closed")


def _looks_like_dead_transport(exc: Exception) -> bool:
    msg = str(exc)
    return any(marker in msg for marker in _DEAD_TRANSPORT_MARKERS)


class ByteStreamer:
    def __init__(self, client: Client, work_loads: Dict[int, int], main_bot: Client):
        self.clean_timer = Performance.CACHE_TIME
        self.client = client
        self.work_loads = work_loads
        self.main_bot = main_bot
        self.cached_file_ids: Dict[str, FileId] = {}
        asyncio.create_task(self.clean_cache())

    async def get_file_properties(self, db_id: str, multi_clients) -> FileId:
        if db_id not in self.cached_file_ids:
            await self.generate_file_properties(db_id, multi_clients)
        return self.cached_file_ids[db_id]

    async def generate_file_properties(self, db_id: str, multi_clients) -> FileId:
        file_id = await get_file_ids(self.client, db_id, multi_clients, None, self.main_bot)
        self.cached_file_ids[db_id] = file_id
        return file_id

    async def generate_media_session(self, client: Client, file_id: FileId) -> Session:
        media_session = client.media_sessions.get(file_id.dc_id, None)

        if media_session is None:
            if file_id.dc_id != await client.storage.dc_id():
                media_session = Session(
                    client, file_id.dc_id,
                    await Auth(client, file_id.dc_id, await client.storage.test_mode()).create(),
                    await client.storage.test_mode(), is_media=True,
                )
                await media_session.start()

                for _ in range(6):
                    exported_auth = await client.invoke(raw.functions.auth.ExportAuthorization(dc_id=file_id.dc_id))
                    try:
                        await media_session.invoke(
                            raw.functions.auth.ImportAuthorization(id=exported_auth.id, bytes=exported_auth.bytes)
                        )
                        break
                    except AuthBytesInvalid:
                        continue
                else:
                    await media_session.stop()
                    raise AuthBytesInvalid
            else:
                media_session = Session(
                    client, file_id.dc_id, await client.storage.auth_key(),
                    await client.storage.test_mode(), is_media=True,
                )
                await media_session.start()
            client.media_sessions[file_id.dc_id] = media_session
        return media_session

    @staticmethod
    async def get_location(file_id: FileId) -> Union[
        raw.types.InputPhotoFileLocation,
        raw.types.InputDocumentFileLocation,
        raw.types.InputPeerPhotoFileLocation,
    ]:
        file_type = file_id.file_type

        if file_type == FileType.CHAT_PHOTO:
            if file_id.chat_id > 0:
                peer = raw.types.InputPeerUser(user_id=file_id.chat_id, access_hash=file_id.chat_access_hash)
            elif file_id.chat_access_hash == 0:
                peer = raw.types.InputPeerChat(chat_id=-file_id.chat_id)
            else:
                peer = raw.types.InputPeerChannel(
                    channel_id=utils.get_channel_id(file_id.chat_id), access_hash=file_id.chat_access_hash,
                )
            return raw.types.InputPeerPhotoFileLocation(
                peer=peer, volume_id=file_id.volume_id, local_id=file_id.local_id,
                big=file_id.thumbnail_source == ThumbnailSource.CHAT_PHOTO_BIG,
            )
        elif file_type == FileType.PHOTO:
            return raw.types.InputPhotoFileLocation(
                id=file_id.media_id, access_hash=file_id.access_hash,
                file_reference=file_id.file_reference, thumb_size=file_id.thumbnail_size,
            )
        return raw.types.InputDocumentFileLocation(
            id=file_id.media_id, access_hash=file_id.access_hash,
            file_reference=file_id.file_reference, thumb_size=file_id.thumbnail_size,
        )

    async def yield_file(
        self, file_id: FileId, index: int, offset: int,
        first_part_cut: int, last_part_cut: int, part_count: int, chunk_size: int,
    ):
        client = self.client
        self.work_loads[index] += 1
        media_session = await self.generate_media_session(client, file_id)
        current_part = 1
        location = await self.get_location(file_id)

        async def fetch_with_retry(off: int):
            last_err = None
            for attempt in range(Performance.STREAM_RETRIES):
                try:
                    return await media_session.invoke(
                        raw.functions.upload.GetFile(location=location, offset=off, limit=chunk_size)
                    )
                except FloodWait as e:
                    logger.warning(f"FloodWait {e.value}s while streaming")
                    await asyncio.sleep(e.value)
                    last_err = e
                except (TimeoutError, ConnectionError, OSError, RuntimeError) as e:
                    last_err = e
                    if _looks_like_dead_transport(e):
                        logger.warning(
                            f"Media session for DC {file_id.dc_id} has a dead transport, discarding it: {e}"
                        )
                        client.media_sessions.pop(file_id.dc_id, None)
                        break
                    if attempt < Performance.STREAM_RETRIES - 1:
                        await asyncio.sleep(Performance.STREAM_RETRY_DELAY * (attempt + 1))
            if last_err:
                raise last_err

        try:
            r = await fetch_with_retry(offset)
            if isinstance(r, raw.types.upload.File):
                while True:
                    chunk = r.bytes
                    if not chunk:
                        break
                    elif part_count == 1:
                        yield chunk[first_part_cut:last_part_cut]
                    elif current_part == 1:
                        yield chunk[first_part_cut:]
                    elif current_part == part_count:
                        yield chunk[:last_part_cut]
                    else:
                        yield chunk

                    current_part += 1
                    offset += chunk_size
                    if current_part > part_count:
                        break
                    r = await fetch_with_retry(offset)
        except (TimeoutError, AttributeError):
            pass
        except AuthBytesInvalid:
            logger.warning(f"Invalid auth for DC {file_id.dc_id}, dropping cached session.")
            client.media_sessions.pop(file_id.dc_id, None)
        except (ConnectionError, OSError, RuntimeError) as e:
            if _looks_like_dead_transport(e):
                client.media_sessions.pop(file_id.dc_id, None)
            logger.warning(f"Stream dropped/network error: {e}")
        finally:
            self.work_loads[index] -= 1

    async def clean_cache(self):
        while True:
            await asyncio.sleep(self.clean_timer)
            self.cached_file_ids.clear()
