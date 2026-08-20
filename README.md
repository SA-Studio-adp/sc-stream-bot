# Stream Bot (v2 — rebuilt)

A clean rewrite of the Telegram file-streaming bot: same stack (Pyrogram/Pyrofork
+ aiohttp + MongoDB), same database schema, same link format
(`/watch/{id}`, `/dl/{id}`) — **every link and every user/ban record from the
previous deployment keeps working unchanged.** Just re-use the same
`DATABASE_URL` and `BOT_TOKEN`.

## What changed structurally

- **No more Pyrogram plugin auto-discovery.** The old codebase used
  `Client(plugins={"root": "..."})`, which imports handler files — and binds
  their `@Client.on_message` decorators to whatever event loop exists — at
  *Client construction time*. That's what caused the "bot builds and connects
  fine but never responds to any message" bug once `uvloop` got installed
  afterward. Handlers are now registered explicitly in
  `streambot/telegram/handlers.py` via `register_handlers()`, called only
  after the event loop and bot are both fully set up. No import-time magic,
  no ordering traps.
- **One shared `Database` instance.** The old code created a fresh
  `Database(...)` — a fresh Mongo connection pool — separately in five
  different files. Now there's a single instance via
  `streambot.database.get_database()`, initialized once at startup.
- **Validated startup config.** Missing/invalid required env vars (`API_ID`,
  `BOT_TOKEN`, `DATABASE_URL`, `FLOG_CHANNEL`, etc.) now produce one clear
  message listing exactly what's wrong, instead of a raw `TypeError` three
  files deep.
- **Explicit dependency passing.** `multi_clients`, `work_loads`, and the bot
  instance are passed into the pieces that need them (`ByteStreamer`,
  route handlers, etc.) instead of being imported as module-level globals
  from a `bot` package — makes the data flow traceable.
- **Mongo connection timeouts.** An unreachable database now fails fast with
  a clear log line at startup instead of making every command hang silently
  forever (this exact bug made the bot look "completely unresponsive" with
  no errors in the logs).
- **Fixed file_id vs message class bug.** Streaming a file via direct link
  (no live chat message behind it) used to crash because the old code passed
  the literal `Message` *class* as a placeholder and then tried to read
  `.caption`/`.chat`/`.file_name` off it. Now falls back to the file's
  already-known metadata from the database.

## Features carried over / included

- Auto keep-alive self-ping (`AUTO_PING`, `PING_INTERVAL`) so free-tier hosts
  (Render, Koyeb, Replit) don't sleep the process.
- Multi-client load-balanced streaming (`MULTI_TOKEN1`, `MULTI_TOKEN2`, ...),
  with the primary bot correctly included in the load-balancer pool.
- Configurable chunk size, retry/backoff on transient stream errors,
  `max_concurrent_transmissions` tuning, `uvloop` event loop.
- Per-IP rate limiting and concurrent-stream caps on `/dl` and `/watch`.
- Bot command list (`/setcommands`-equivalent) auto-updated on every start.
- Force-subscribe, user/channel banning, broadcast, file browsing (`/files`),
  admin `/status` with live client load and uptime.

## Running it

```
pip install -r requirements.txt
python -m streambot
```

or via Docker:

```
docker build -t streambot .
docker run --env-file .env -p 8080:8080 streambot
```

See `app.json` for the full environment variable list.

## Project layout

```
streambot/
  __main__.py           entrypoint — uvloop install, config validation, wiring
  config.py              validated env config
  database.py             MongoDB access (single shared instance)
  logging_setup.py        logging configuration
  exceptions.py           FileNotFound / InvalidHash
  telegram/
    client.py             Pyrogram Client construction (main + multi-clients)
    handlers.py            all message/callback handlers, explicit registration
    guards.py              auth/ban/force-sub checks, link text generation
    broadcast.py           /broadcast helper
    bot_commands.py         push /start /files /status etc. to Telegram
    keep_alive.py           self-ping loop
  web/
    app.py                  aiohttp app factory
    routes.py                /ping /status /watch /dl
    middleware.py            rate limiting
    streamer.py               chunked Telegram file fetch (ByteStreamer)
    render_template.py        renders watch page HTML
    templates/                dl.html, play.html
  utils/
    file_info.py              media metadata + multi-client file_id sync
    formatting.py              humanbytes / readable time
    translation.py             bot text + inline keyboards
```
