import urllib.parse
from pathlib import Path

import aiohttp
import jinja2

from streambot.config import Server
from streambot.database import get_database
from streambot.utils.formatting import humanbytes

TEMPLATE_DIR = Path(__file__).parent / "templates"


async def render_page(db_id: str) -> str:
    db = get_database()
    file_data = await db.get_file(db_id)
    src = urllib.parse.urljoin(Server.URL, f"dl/{file_data['_id']}")
    file_size = humanbytes(file_data["file_size"])
    file_name = file_data["file_name"].replace("_", " ")

    if str(file_data["mime_type"]).split("/")[0].strip() == "video":
        template_file = TEMPLATE_DIR / "play.html"
    else:
        template_file = TEMPLATE_DIR / "dl.html"
        async with aiohttp.ClientSession() as s:
            async with s.get(src) as resp:
                content_length = resp.headers.get("Content-Length")
                if content_length:
                    file_size = humanbytes(int(content_length))

    template = jinja2.Template(template_file.read_text())
    return template.render(file_name=file_name, file_url=src, file_size=file_size)
