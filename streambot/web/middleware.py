import logging
import time
from collections import defaultdict, deque

from aiohttp import web

from streambot.config import Performance

logger = logging.getLogger(__name__)

_request_log = defaultdict(deque)
_active_streams = defaultdict(int)
_LIMITED_PREFIXES = ("/dl/", "/watch/")
_api_log = defaultdict(deque)


def _client_ip(request: web.Request) -> str:
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote or "unknown"


@web.middleware
async def cors_middleware(request: web.Request, handler):
    """Answers CORS preflights for /api/*; the handlers add the headers themselves."""
    if request.method == "OPTIONS" and request.path.startswith("/api/"):
        from streambot.web.media_routes import CORS
        return web.Response(status=204, headers=CORS)
    return await handler(request)


@web.middleware
async def rate_limit_middleware(request: web.Request, handler):
    path = request.path
    # ffmpeg reads files back through /dl/ over loopback; never throttle that.
    if request.remote in ("127.0.0.1", "::1") and "X-Forwarded-For" not in request.headers:
        return await handler(request)
    if path.startswith("/api/") and Performance.API_RATE_LIMIT_REQUESTS > 0:
        ip = _client_ip(request)
        now = time.time()
        window = _api_log[ip]
        window.append(now)
        cutoff = now - Performance.RATE_LIMIT_WINDOW
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) > Performance.API_RATE_LIMIT_REQUESTS:
            from streambot.web.media_routes import CORS
            return web.json_response(
                {"error": "rate_limited", "message": "Too many requests, slow down."},
                status=429, headers={**CORS, "Retry-After": str(Performance.RATE_LIMIT_WINDOW)},
            )
        return await handler(request)
    if not any(path.startswith(p) for p in _LIMITED_PREFIXES):
        return await handler(request)

    ip = _client_ip(request)
    now = time.time()

    if Performance.RATE_LIMIT_REQUESTS > 0:
        window = _request_log[ip]
        window.append(now)
        cutoff = now - Performance.RATE_LIMIT_WINDOW
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) > Performance.RATE_LIMIT_REQUESTS:
            logger.info(f"Rate limit hit for {ip} on {path}")
            return web.json_response(
                {"error": "rate_limited", "message": "Too many requests, slow down."},
                status=429, headers={"Retry-After": str(Performance.RATE_LIMIT_WINDOW)},
            )

    if Performance.MAX_STREAMS_PER_IP > 0 and path.startswith("/dl/"):
        if _active_streams[ip] >= Performance.MAX_STREAMS_PER_IP:
            logger.info(f"Concurrent stream cap hit for {ip}")
            return web.json_response(
                {"error": "too_many_streams", "message": "Too many concurrent downloads."}, status=429,
            )
        _active_streams[ip] += 1
        try:
            return await handler(request)
        finally:
            _active_streams[ip] -= 1

    return await handler(request)
