# Stream Bot (v2 — rebuilt)

Same stack (Pyrogram/Pyrofork + aiohttp + MongoDB), same database schema,
same link format (`/watch/{id}`, `/dl/{id}`) — every old link and every
user/ban record keeps working. Re-use the same `DATABASE_URL` and
`BOT_TOKEN`.

## This round's fix: stale media session on network blips

If a network hiccup killed one Telegram DC connection, the old code
correctly caught the failure but never discarded the dead connection
object — so every subsequent request to that same DC kept retrying a
connection that was already dead, forever, until a manual restart. That
was the "a few old files just won't load" symptom. Fixed in
`streambot/web/streamer.py`: the cached session for that DC is now thrown
away as soon as a dead-transport error is detected, so the next request
opens a fresh connection instead of repeating the same failure.

## IMPORTANT — HTML templates are placeholders

`streambot/web/templates/dl.html` and `play.html` in this build are
minimal functional placeholders, not your original styled pages (a tooling
hiccup on my end lost the copies partway through this session). Please
copy your actual `dl.html` / `play.html` from your current repo
(`SA-Studio-adp/sc-stream-bot` or `FileStreamBot`) into
`streambot/web/templates/` before deploying, so the watch/download pages
look like they did before. Everything else (all Python logic, DB schema,
link format) is complete and unaffected by this.

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
