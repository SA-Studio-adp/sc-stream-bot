"""
Simple in-memory sliding-window rate limiter and a per-IP concurrent-
stream cap, scoped to the streaming endpoints. Purely in-process — fine
for a single instance; swap for a Redis-backed limiter if you ever scale
to multiple instances behind a shared load balancer.
"""

import logging
import time
from collections import defaultdict, deque

from aiohttp import web

from streambot.config import Performance

logger = logging.getLogger(__name__)

_request_log = defaultdict(deque)
_active_streams = defaultdict(int)
_LIMITED_PREFIXES = ("/dl/", "/watch/")


def _client_ip(request: web.Request) -> str:
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote or "unknown"


@web.middleware
async def rate_limit_middleware(request: web.Request, handler):
    path = request.path
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
