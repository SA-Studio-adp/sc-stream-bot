#!/bin/sh
# Installs whichever Pyrogram-compatible package PYROGRAM_MODE selects,
# then starts the bot. This has to happen at install time (not as a
# runtime if/else in Python) because both pyrofork and wzgram register
# themselves under the same top-level "pyrogram" import name — having
# both installed at once means one silently overwrites the other's files
# in site-packages, so only one can actually be installed at a time.
#
# PYROGRAM_MODE=py       -> pyrofork (default, the one this bot shipped with)
# PYROGRAM_MODE=wzgram   -> wzgram (https://pypi.org/project/wzgram/)
#
# The rest of the codebase needs no changes either way: every module here
# does `from pyrogram import ...`, and both packages provide that same
# import path.

set -e

MODE="${PYROGRAM_MODE:-py}"

case "$MODE" in
  wzgram)
    echo "PYROGRAM_MODE=wzgram -> installing wzgram"
    pip install --no-cache-dir --upgrade wzgram
    ;;
  py|pyrofork|"")
    echo "PYROGRAM_MODE=py -> installing pyrofork"
    pip install --no-cache-dir --upgrade pyrofork
    ;;
  *)
    echo "Unknown PYROGRAM_MODE='$MODE' (expected 'py' or 'wzgram'). Defaulting to pyrofork."
    pip install --no-cache-dir --upgrade pyrofork
    ;;
esac

exec python -m streambot
