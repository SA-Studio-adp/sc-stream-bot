"""HTTP endpoints for the player's audio-track / embedded-subtitle features."""

from aiohttp import web

from streambot.config import Media
from streambot.web import media_tools
from streambot.web.media_tools import MediaError

CORS = {
    "Access-Control-Allow-Origin": Media.CORS_ORIGINS,
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Range, Content-Type",
}


def _fail(e: MediaError) -> web.Response:
    return web.json_response({"error": str(e)}, status=e.status, headers=CORS)


def _index(raw: str) -> int:
    try:
        n = int(raw)
    except ValueError:
        raise MediaError("bad track index", 400)
    if not 0 <= n < 64:
        raise MediaError("bad track index", 400)
    return n


def build_media_routes() -> web.RouteTableDef:
    routes = web.RouteTableDef()

    @routes.get("/api/tracks/{path}")
    async def tracks(request: web.Request):
        try:
            data = await media_tools.probe(request.match_info["path"])
        except MediaError as e:
            return _fail(e)
        return web.json_response(data, headers={**CORS, "Cache-Control": "public, max-age=300"})

    @routes.get("/api/sub/{path}/{n}")
    async def subtitle(request: web.Request):
        try:
            db_id = media_tools.valid_id(request.match_info["path"])
            state, val = media_tools.sub_state(db_id, _index(request.match_info["n"]))
        except MediaError as e:
            return _fail(e)
        if state == "ready":
            return web.Response(
                body=val.read_bytes(), content_type="text/vtt", charset="utf-8",
                headers={**CORS, "Cache-Control": "public, max-age=86400"},
            )
        if state == "pending":
            return web.json_response({"status": "pending"}, status=202, headers={**CORS, "Retry-After": "3"})
        return web.json_response({"status": "error", "error": val}, status=500, headers=CORS)

    @routes.get("/api/audio/{path}/{n}")
    async def audio(request: web.Request):
        try:
            db_id = media_tools.valid_id(request.match_info["path"])
            n = _index(request.match_info["n"])
        except MediaError as e:
            return _fail(e)
        try:
            info = await media_tools.probe(db_id)  # cached; also rejects bad indexes
        except MediaError as e:
            return _fail(e)
        if n >= len(info["audio"]):
            return _fail(MediaError("no such audio track", 404))
        if not media_tools.audio_slot_free():
            return web.json_response({"error": "busy"}, status=503, headers={**CORS, "Retry-After": "5"})
        resp = web.StreamResponse(status=200, headers={
            **CORS, "Content-Type": "audio/mpeg", "Cache-Control": "no-store",
        })
        await media_tools.stream_audio(
            request, resp, db_id, n, media_tools.clean_start(request.query.get("start"))
        )
        return resp

    return routes
