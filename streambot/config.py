"""
Central, validated configuration.

Unlike the previous version (which crashed with a raw TypeError if a
required var like FLOG_CHANNEL was missing), this module validates
everything up front and raises one clear, readable error listing exactly
what's missing/wrong — so a bad deployment fails in the first second with
a message you can act on, instead of a cryptic traceback three files deep.
"""

import sys
from os import environ as env

from dotenv import load_dotenv

load_dotenv()


class ConfigError(Exception):
    pass


def _require_str(name: str) -> str:
    val = env.get(name)
    if not val:
        raise ConfigError(f"{name} is required but not set.")
    return str(val)


def _require_int(name: str) -> int:
    val = _require_str(name)
    try:
        return int(val)
    except ValueError:
        raise ConfigError(f"{name} must be an integer, got: {val!r}")


def _bool(name: str, default: str = "0") -> bool:
    return str(env.get(name, default)).strip().lower() in ("1", "true", "t", "yes", "y")


class Telegram:
    API_ID: int
    API_HASH: str
    BOT_TOKEN: str
    DATABASE_URL: str
    FLOG_CHANNEL: int
    ULOG_CHANNEL: int

    OWNER_ID = int(env.get("OWNER_ID", "7978482443"))
    WORKERS = int(env.get("WORKERS", "6"))
    UPDATES_CHANNEL = str(env.get("UPDATES_CHANNEL", "Telegram"))
    SESSION_NAME = str(env.get("SESSION_NAME", "FileStream"))
    FORCE_SUB_ID = env.get("FORCE_SUB_ID", None)
    FORCE_SUB = _bool("FORCE_UPDATES_CHANNEL")
    SLEEP_THRESHOLD = int(env.get("SLEEP_THRESHOLD", "60"))
    FILE_PIC = env.get("FILE_PIC", "https://graph.org/file/5bb9935be0229adf98b73.jpg")
    START_PIC = env.get("START_PIC", "https://graph.org/file/290af25276fa34fa8f0aa.jpg")
    VERIFY_PIC = env.get("VERIFY_PIC", "https://graph.org/file/736e21cc0efa4d8c2a0e4.jpg")
    MULTI_CLIENT = False  # flipped True at runtime once extra clients start
    MODE = env.get("MODE", "primary")
    SECONDARY = MODE.strip().lower() == "secondary"
    AUTH_USERS = list(set(int(x) for x in str(env.get("AUTH_USERS", "")).split()))


class Server:
    PORT = int(env.get("PORT", 8080))
    BIND_ADDRESS = str(env.get("BIND_ADDRESS", "0.0.0.0"))
    # How often (seconds) the bot pings its own /ping endpoint to prevent
    # free-tier hosts (Render, Koyeb, Replit, etc.) from sleeping.
    PING_INTERVAL = int(env.get("PING_INTERVAL", "600"))
    # Force the self-ping loop on/off; unset = auto-detect from FQDN.
    AUTO_PING = env.get("AUTO_PING", None)
    HAS_SSL = _bool("HAS_SSL")
    NO_PORT = _bool("NO_PORT")
    FQDN = str(env.get("FQDN", BIND_ADDRESS))
    URL = "http{}://{}{}/".format(
        "s" if HAS_SSL else "", FQDN, "" if NO_PORT else ":" + str(PORT)
    )

    @classmethod
    def should_auto_ping(cls) -> bool:
        if cls.AUTO_PING is not None:
            return str(cls.AUTO_PING).lower() in ("1", "true", "t", "yes", "y")
        return cls.FQDN not in ("0.0.0.0", "127.0.0.1", "localhost", "")


class Performance:
    CHUNK_SIZE = int(env.get("CHUNK_SIZE", 1024 * 1024))
    CACHE_TIME = int(env.get("CACHE_TIME", str(30 * 60)))
    MAX_STREAMS_PER_IP = int(env.get("MAX_STREAMS_PER_IP", "8"))
    RATE_LIMIT_REQUESTS = int(env.get("RATE_LIMIT_REQUESTS", "60"))
    RATE_LIMIT_WINDOW = int(env.get("RATE_LIMIT_WINDOW", "60"))
    STREAM_RETRIES = int(env.get("STREAM_RETRIES", "3"))
    STREAM_RETRY_DELAY = float(env.get("STREAM_RETRY_DELAY", "1.0"))
    # Parallel MTProto connections per Pyrogram Client for transmissions.
    # Pyrogram's own default is 1 (fully serial); raising this lets one
    # client fetch multiple chunks concurrently — speeds up both send and
    # receive. Tune down if you start seeing FloodWaits.
    MAX_CONCURRENT_TRANSMISSIONS = int(env.get("MAX_CONCURRENT_TRANSMISSIONS", "6"))


def validate_and_bind():
    """Fail fast, with one readable message, instead of a deep traceback
    the first time something touches a missing/invalid required var."""
    errors = []
    for name, caster in (
        ("API_ID", _require_int),
        ("API_HASH", _require_str),
        ("BOT_TOKEN", _require_str),
        ("DATABASE_URL", _require_str),
        ("FLOG_CHANNEL", _require_int),
        ("ULOG_CHANNEL", _require_int),
    ):
        try:
            setattr(Telegram, name, caster(name))
        except ConfigError as e:
            errors.append(str(e))

    if errors:
        print("\n----------------------- CONFIGURATION ERROR -----------------------")
        for e in errors:
            print(f"  - {e}")
        print("Set these in your environment (.env locally, or your host's")
        print("environment variables panel) and restart.")
        print("---------------------------------------------------------------------\n")
        sys.exit(1)
