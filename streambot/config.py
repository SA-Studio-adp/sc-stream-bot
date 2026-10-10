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
    MULTI_CLIENT = False
    MODE = env.get("MODE", "primary")
    SECONDARY = MODE.strip().lower() == "secondary"
    AUTH_USERS = list(set(int(x) for x in str(env.get("AUTH_USERS", "")).split()))


class Server:
    PORT = int(env.get("PORT", 8080))
    BIND_ADDRESS = str(env.get("BIND_ADDRESS", "0.0.0.0"))
    PING_INTERVAL = int(env.get("PING_INTERVAL", "600"))
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
    # /api/* (track list, subtitle polling, audio) gets its own, looser bucket so viewers
    # sharing one carrier/NAT IP don't starve each other or eat the /dl budget
    API_RATE_LIMIT_REQUESTS = int(env.get("API_RATE_LIMIT_REQUESTS", "300"))
    RATE_LIMIT_WINDOW = int(env.get("RATE_LIMIT_WINDOW", "60"))
    STREAM_RETRIES = int(env.get("STREAM_RETRIES", "3"))
    STREAM_RETRY_DELAY = float(env.get("STREAM_RETRY_DELAY", "1.0"))
    MAX_CONCURRENT_TRANSMISSIONS = int(env.get("MAX_CONCURRENT_TRANSMISSIONS", "6"))


class Media:
    """ffmpeg-powered track tools (audio switching + embedded subtitles)."""
    ENABLED = _bool("MEDIA_TOOLS", "1")
    FFMPEG = str(env.get("FFMPEG_PATH", "ffmpeg"))
    FFPROBE = str(env.get("FFPROBE_PATH", "ffprobe"))
    CACHE_DIR = str(env.get("MEDIA_CACHE_DIR", "/tmp/scfiles-media"))
    CACHE_MAX_FILES = int(env.get("MEDIA_CACHE_MAX_FILES", "200"))
    PROBE_TTL = int(env.get("MEDIA_PROBE_TTL", str(6 * 3600)))
    MAX_AUDIO_STREAMS = int(env.get("MEDIA_MAX_AUDIO_STREAMS", "2"))
    SUB_TIMEOUT = int(env.get("MEDIA_SUB_TIMEOUT", "1800"))
    AUDIO_BITRATE = str(env.get("MEDIA_AUDIO_BITRATE", "128k"))
    CORS_ORIGINS = str(env.get("CORS_ORIGINS", "*"))


def validate_and_bind():
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
