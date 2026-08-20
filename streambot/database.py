"""
MongoDB access layer.

Collection/field names are kept byte-for-byte identical to the previous
version (`users`, `blacklist`, `file`, with the same field names within
each) so that a database from an older deployment keeps working without
any migration — every link ever generated still resolves.

Only one Database instance should exist per process; use get_database()
rather than constructing Database() directly, so every module shares the
same Mongo connection pool instead of each file opening its own (the old
codebase had five separate `Database(...)` instantiations scattered across
plugin files).
"""

import logging
import time

import pymongo
import motor.motor_asyncio
from bson.objectid import ObjectId
from bson.errors import InvalidId

from streambot.exceptions import FileNotFound

logger = logging.getLogger(__name__)

_instance = None


class Database:
    def __init__(self, uri: str, database_name: str):
        # Without explicit timeouts, an unreachable Mongo host (e.g. IP not
        # allow-listed on Atlas) makes every call hang indefinitely instead
        # of failing — which looks exactly like "the bot stopped
        # responding" from the outside. Fail fast instead, with a clear
        # error, so it's obvious what's actually wrong.
        self._client = motor.motor_asyncio.AsyncIOMotorClient(
            uri,
            serverSelectionTimeoutMS=10000,
            connectTimeoutMS=10000,
            socketTimeoutMS=20000,
        )
        self.db = self._client[database_name]
        self.col = self.db.users
        self.black = self.db.blacklist
        self.file = self.db.file

    async def ping(self) -> bool:
        try:
            await self._client.admin.command("ping")
            return True
        except Exception as e:
            logger.error(f"MongoDB is not reachable: {e}")
            return False

    # ---------------------[ users ]---------------------
    def _new_user(self, id):
        return dict(id=id, join_date=time.time(), Links=0)

    async def add_user(self, id):
        await self.col.insert_one(self._new_user(id))

    async def get_user(self, id):
        return await self.col.find_one({"id": int(id)})

    async def total_users_count(self):
        return await self.col.count_documents({})

    async def get_all_users(self):
        return self.col.find({})

    async def delete_user(self, user_id):
        await self.col.delete_many({"id": int(user_id)})

    async def count_links(self, id, operation: str):
        if operation == "-":
            await self.col.update_one({"id": id}, {"$inc": {"Links": -1}})
        elif operation == "+":
            await self.col.update_one({"id": id}, {"$inc": {"Links": 1}})

    # ---------------------[ ban list ]---------------------
    def _black_user(self, id):
        return dict(id=id, ban_date=time.time())

    async def ban_user(self, id):
        await self.black.insert_one(self._black_user(id))

    async def unban_user(self, id):
        await self.black.delete_one({"id": int(id)})

    async def is_user_banned(self, id) -> bool:
        return bool(await self.black.find_one({"id": int(id)}))

    async def total_banned_users_count(self):
        return await self.black.count_documents({})

    # ---------------------[ files ]---------------------
    async def add_file(self, file_info: dict):
        file_info["time"] = time.time()
        existing = await self.get_file_by_fileuniqueid(
            file_info["user_id"], file_info["file_unique_id"]
        )
        if existing:
            return existing["_id"]
        await self.count_links(file_info["user_id"], "+")
        return (await self.file.insert_one(file_info)).inserted_id

    async def find_files(self, user_id, index_range):
        cursor = self.file.find({"user_id": user_id})
        cursor.skip(index_range[0] - 1)
        cursor.limit(index_range[1] - index_range[0] + 1)
        cursor.sort("_id", pymongo.DESCENDING)
        total = await self.file.count_documents({"user_id": user_id})
        return cursor, total

    async def get_file(self, _id):
        try:
            file_info = await self.file.find_one({"_id": ObjectId(_id)})
        except InvalidId:
            raise FileNotFound
        if not file_info:
            raise FileNotFound
        return file_info

    async def get_file_by_fileuniqueid(self, id, file_unique_id, many: bool = False):
        if many:
            return self.file.find({"file_unique_id": file_unique_id})
        file_info = await self.file.find_one({"user_id": id, "file_unique_id": file_unique_id})
        return file_info or False

    async def total_files(self, id=None):
        if id:
            return await self.file.count_documents({"user_id": id})
        return await self.file.count_documents({})

    async def delete_one_file(self, _id):
        await self.file.delete_one({"_id": ObjectId(_id)})

    async def update_file_ids(self, _id, file_ids: dict):
        await self.file.update_one({"_id": ObjectId(_id)}, {"$set": {"file_ids": file_ids}})


def init_database(uri: str, database_name: str) -> Database:
    """Call exactly once at startup."""
    global _instance
    _instance = Database(uri, database_name)
    return _instance


def get_database() -> Database:
    if _instance is None:
        raise RuntimeError("Database not initialized — call init_database() first.")
    return _instance
