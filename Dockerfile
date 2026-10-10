FROM python:3.11-slim

WORKDIR /app

# ffmpeg/ffprobe: audio-track switching + embedded subtitle extraction
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x entrypoint.sh

# entrypoint.sh installs pyrofork or wzgram based on PYROGRAM_MODE, then
# starts the bot. Set PYROGRAM_MODE=wzgram in your host's env vars to
# switch; default is pyrofork (PYROGRAM_MODE=py).
ENTRYPOINT ["./entrypoint.sh"]
