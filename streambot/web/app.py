from aiohttp import web

from streambot.config import Media
from streambot.web.middleware import cors_middleware, rate_limit_middleware
from streambot.web.routes import build_routes


def build_web_app(bot, multi_clients: dict, work_loads: dict) -> web.Application:
    app = web.Application(
        client_max_size=30000000, middlewares=[cors_middleware, rate_limit_middleware]
    )
    app.add_routes(build_routes(bot, multi_clients, work_loads))
    if Media.ENABLED:
        from streambot.web.media_routes import build_media_routes
        app.add_routes(build_media_routes())
    return app
