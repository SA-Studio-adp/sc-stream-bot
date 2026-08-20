import logging
import math
import mimetypes
import time
import traceback

from aiohttp import web
from aiohttp.http_exceptions import BadStatusLine

from streambot import StartTime, __version__
from streambot.config import Performance, Server, Telegram
from streambot.exceptions import FileNotFound, InvalidHash
from streambot.utils.file_info import get_name
from streambot.utils.formatting import get_readable_time
from streambot.web.render_template import render_page
from streambot.web.streamer import ByteStreamer

logger = logging.getLogger(__name__)


def build_routes(bot, multi_clients: dict, work_loads: dict) -> web.RouteTableDef:
    routes = web.RouteTableDef()
    streamer_cache: dict = {}

    @routes.get("/ping", allow_head=True)
    async def ping_route_handler(_):
        """Cheap endpoint hit by the keep-alive task (and any external
        uptime monitor) so the host sees traffic without touching Telegram
        or the database at all."""
        return web.json_response({"status": "alive", "uptime": time.time() - StartTime})

    @routes.get("/status", allow_head=True)
    async def root_route_handler(_):
        return web.json_response({
            "server_status": "running",
            "uptime": get_readable_time(time.time() - StartTime),
            "telegram_bot": "@" + bot.username,
            "connected_bots": len(multi_clients),
            "multi_client": Telegram.MULTI_CLIENT,
            "loads": dict(
                ("bot" + str(c + 1), l)
                for c, (_, l) in enumerate(sorted(work_loads.items(), key=lambda x: x[1], reverse=True))
            ),
            "version": __version__,
        })

    @routes.get("/watch/{path}", allow_head=True)
    async def watch_handler(request: web.Request):
        try:
            path = request.match_info["path"]
            return web.Response(text=await render_page(path), content_type="text/html")
        except InvalidHash as e:
            raise web.HTTPForbidden(text=e.message)
        except FileNotFound as e:
            raise web.HTTPNotFound(text=e.message)
        except (AttributeError, BadStatusLine, ConnectionResetError):
            pass

    @routes.get("/dl/{path}", allow_head=True)
    async def dl_handler(request: web.Request):
        try:
            path = request.match_info["path"]
            return await media_streamer(request, path)
        except InvalidHash as e:
            raise web.HTTPForbidden(text=e.message)
        except FileNotFound as e:
            raise web.HTTPNotFound(text=e.message)
        except (AttributeError, BadStatusLine, ConnectionResetError):
            pass
        except Exception as e:
            logger.critical(traceback.format_exc())
            raise web.HTTPInternalServerError(text=str(e))

    async def media_streamer(request: web.Request, db_id: str):
        range_header = request.headers.get("Range", 0)

        index = min(work_loads, key=work_loads.get)
        faster_client = multi_clients[index]

        if Telegram.MULTI_CLIENT:
            logger.info(f"Client {index} is now serving {request.headers.get('X-Forwarded-For', request.remote)}")

        if faster_client in streamer_cache:
            tg_connect = streamer_cache[faster_client]
        else:
            tg_connect = ByteStreamer(faster_client, work_loads, bot)
            streamer_cache[faster_client] = tg_connect

        file_id = await tg_connect.get_file_properties(db_id, multi_clients)
        file_size = file_id.file_size

        if range_header:
            from_bytes, until_bytes = range_header.replace("bytes=", "").split("-")
            from_bytes = int(from_bytes)
            until_bytes = int(until_bytes) if until_bytes else file_size - 1
        else:
            from_bytes = request.http_range.start or 0
            until_bytes = (request.http_range.stop or file_size) - 1

        if (until_bytes > file_size) or (from_bytes < 0) or (until_bytes < from_bytes):
            return web.Response(
                status=416, body="416: Range not satisfiable",
                headers={"Content-Range": f"bytes */{file_size}"},
            )

        chunk_size = Performance.CHUNK_SIZE
        until_bytes = min(until_bytes, file_size - 1)

        offset = from_bytes - (from_bytes % chunk_size)
        first_part_cut = from_bytes - offset
        last_part_cut = until_bytes % chunk_size + 1

        req_length = until_bytes - from_bytes + 1
        part_count = math.ceil(until_bytes / chunk_size) - math.floor(offset / chunk_size)
        body = tg_connect.yield_file(file_id, index, offset, first_part_cut, last_part_cut, part_count, chunk_size)

        mime_type = file_id.mime_type
        file_name = get_name(file_id)
        disposition = "attachment"
        if not mime_type:
            mime_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"

        return web.Response(
            status=206 if range_header else 200,
            body=body,
            headers={
                "Content-Type": f"{mime_type}",
                "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
                "Content-Length": str(req_length),
                "Content-Disposition": f'{disposition}; filename="{file_name}"',
                "Accept-Ranges": "bytes",
                "Cache-Control": "public, max-age=604800, immutable",
            },
        )

    return routes
