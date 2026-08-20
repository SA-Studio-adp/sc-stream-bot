import sys
import logging
import logging.handlers as handlers


def configure_logging():
    logging.basicConfig(
        level=logging.INFO,
        datefmt="%d/%m/%Y %H:%M:%S",
        format="[%(asctime)s] {%(pathname)s:%(lineno)d} %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(stream=sys.stdout),
            handlers.RotatingFileHandler(
                "streambot.log", mode="a", maxBytes=104857600, backupCount=2, encoding="utf-8"
            ),
        ],
    )
    logging.getLogger("aiohttp").setLevel(logging.ERROR)
    logging.getLogger("aiohttp.web").setLevel(logging.ERROR)
    # WARNING (not ERROR) so anything unusual in Pyrogram — like a handler
    # failing to register — actually shows up instead of vanishing.
    logging.getLogger("pyrogram").setLevel(logging.WARNING)
