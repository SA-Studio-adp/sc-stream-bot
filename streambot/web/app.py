from aiohttp import web

from streambot.web.middleware import rate_limit_middleware
from streambot.web.routes import build_routes


def build_web_app(bot, multi_clients: dict, work_loads: dict) -> web.Application:
    app = web.Application(client_max_size=30000000, middlewares=[rate_limit_middleware])
    app.add_routes(build_routes(bot, multi_clients, work_loads))
    return app
