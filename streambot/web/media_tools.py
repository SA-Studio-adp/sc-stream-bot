"""
ffprobe / ffmpeg helpers used by the player's audio-track and embedded-subtitle
features. Everything reads the file through this server's own /dl/ route over
loopback, so it works for any file the bot can already stream.

Free-tier friendly by design: no video is ever transcoded.
  * probe      - reads only the container header (cached)
  * subtitles  - one background job per track, result cached on disk (text only)
  * audio      - ONE audio track re-encoded to MP3 on demand, only while playing
"""

import asyncio
import json
import logging
import math
import re
import time
from pathlib import Path
from typing import Optional

from streambot.config import Media, Server

logger = logging.getLogger(__name__)

# every ffmpeg/ffprobe child we started; /restart kills these so nothing is orphaned
_procs: set = set()

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
TEXT_SUB_CODECS = {"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text"}


class MediaError(Exception):
    def __init__(self, message: str, status: int = 500):
        super().__init__(message)
        self.status = status


def valid_id(db_id: str) -> str:
    if not _ID_RE.match(db_id or ""):
        raise MediaError("invalid file id", 400)
    return db_id


def source_url(db_id: str) -> str:
    return f"http://127.0.0.1:{Server.PORT}/dl/{valid_id(db_id)}"


# --------------------------------------------------------------------------- probe
_probe_cache: dict = {}
_probe_locks: dict = {}
_probe_sem = asyncio.Semaphore(2)


def _parse_probe(data: dict) -> dict:
    audio, subs, skipped = [], [], 0
    sub_ordinal = 0
    for s in data.get("streams", []):
        tags = {k.lower(): v for k, v in (s.get("tags") or {}).items()}
        disp = s.get("disposition") or {}
        kind = s.get("codec_type")
        if kind == "audio":
            audio.append({
                "index": len(audio),
                "codec": s.get("codec_name"),
                "lang": tags.get("language", "und"),
                "title": tags.get("title", ""),
                "channels": s.get("channels"),
                "default": bool(disp.get("default")),
            })
        elif kind == "subtitle":
            # ordinal counts EVERY subtitle stream: it is what `-map 0:s:N` expects
            if s.get("codec_name") in TEXT_SUB_CODECS:
                subs.append({
                    "index": sub_ordinal,
                    "codec": s.get("codec_name"),
                    "lang": tags.get("language", "und"),
                    "title": tags.get("title", ""),
                    "default": bool(disp.get("default")),
                    "forced": bool(disp.get("forced")),
                })
            else:
                skipped += 1
            sub_ordinal += 1
    try:
        duration = float((data.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
    try:
        size = int((data.get("format") or {}).get("size"))
    except (TypeError, ValueError):
        size = None
    return {"duration": duration, "size": size, "audio": audio, "subtitles": subs, "skipped_subtitles": skipped}


async def probe(db_id: str) -> dict:
    valid_id(db_id)
    hit = _probe_cache.get(db_id)
    if hit and time.time() - hit[0] < Media.PROBE_TTL:
        return hit[1]

    lock = _probe_locks.setdefault(db_id, asyncio.Lock())
    async with lock:
        hit = _probe_cache.get(db_id)
        if hit and time.time() - hit[0] < Media.PROBE_TTL:
            return hit[1]
        async with _probe_sem:
            proc = await asyncio.create_subprocess_exec(
                Media.FFPROBE, "-v", "error", "-print_format", "json",
                "-show_streams", "-show_format",
                "-probesize", "10M", "-analyzeduration", "10M",
                source_url(db_id),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            _procs.add(proc)
            try:
                out, err = await asyncio.wait_for(proc.communicate(), 60)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise MediaError("probe timed out", 504)
            finally:
                _procs.discard(proc)
        if proc.returncode != 0:
            msg = err.decode(errors="replace")
            status = 404 if "404" in msg else 502
            raise MediaError("could not read file" if status == 502 else "file not found", status)
        try:
            result = _parse_probe(json.loads(out))
        except ValueError:
            raise MediaError("bad probe output", 502)
        _probe_cache[db_id] = (time.time(), result)
        return result


# ---------------------------------------------------------------------- subtitles
_sub_tasks: dict = {}
_sub_errors: dict = {}
_sub_sem = asyncio.Semaphore(1)  # one full-file read at a time on the free tier


def _cache_dir() -> Path:
    d = Path(Media.CACHE_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sub_path(db_id: str, n: int) -> Path:
    return _cache_dir() / f"{valid_id(db_id)}.s{n}.vtt"


def _prune_cache():
    files = sorted(_cache_dir().glob("*.vtt"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[Media.CACHE_MAX_FILES:]:
        try:
            old.unlink()
        except OSError:
            pass


async def _extract_sub(db_id: str, n: int, dest: Path):
    tmp = dest.with_suffix(".part")
    async with _sub_sem:
        proc = await asyncio.create_subprocess_exec(
            Media.FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-i", source_url(db_id), "-map", f"0:s:{n}",
            "-vn", "-an", "-dn", "-c:s", "webvtt", "-f", "webvtt", "-y", str(tmp),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _procs.add(proc)
        try:
            _, err = await asyncio.wait_for(proc.communicate(), Media.SUB_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            tmp.unlink(missing_ok=True)
            raise MediaError("subtitle extraction timed out")
        finally:
            _procs.discard(proc)
    if proc.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        logger.warning(f"subtitle extract failed for {db_id} s{n}: {err.decode(errors='replace')[:300]}")
        raise MediaError("subtitle extraction failed")
    tmp.replace(dest)
    _prune_cache()


def sub_state(db_id: str, n: int):
    """Returns ('ready', Path) | ('pending', None) | ('error', message). Starts the job if needed."""
    key = (db_id, n)
    dest = _sub_path(db_id, n)
    if dest.exists():
        dest.touch()
        return "ready", dest

    task = _sub_tasks.get(key)
    if task is not None and task.done():
        _sub_tasks.pop(key, None)
        exc = None if task.cancelled() else task.exception()
        if exc is not None:
            _sub_errors[key] = (time.time(), str(exc))
        elif dest.exists():
            return "ready", dest
        task = None

    err = _sub_errors.get(key)
    if err and time.time() - err[0] < 30:  # short cool-down before a retry
        return "error", err[1]
    if err:
        _sub_errors.pop(key, None)

    if task is None:
        _sub_tasks[key] = asyncio.create_task(_extract_sub(db_id, n, dest))
    return "pending", None


# ---------------------------------------------------------------------------- audio
_audio_active = 0


def audio_slot_free() -> bool:
    return _audio_active < Media.MAX_AUDIO_STREAMS


def clean_start(raw: Optional[str]) -> float:
    try:
        v = float(raw or 0)
    except ValueError:
        return 0.0
    return v if math.isfinite(v) and v > 0 else 0.0


async def stream_audio(request, response, db_id: str, n: int, start: float):
    """Pipe ffmpeg's MP3 output into an already-prepared StreamResponse."""
    global _audio_active
    _audio_active += 1
    proc = await asyncio.create_subprocess_exec(
        Media.FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-ss", f"{start:.3f}", "-i", source_url(db_id),
        "-map", f"0:a:{n}", "-vn", "-sn", "-dn",
        "-threads", "1", "-c:a", "libmp3lame", "-b:a", Media.AUDIO_BITRATE, "-ac", "2",
        "-f", "mp3", "pipe:1",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    _procs.add(proc)
    try:
        await response.prepare(request)
        while True:
            chunk = await proc.stdout.read(32768)
            if not chunk:
                break
            # a client that stops reading for 2 min (paused tab) frees its slot
            await asyncio.wait_for(response.write(chunk), 120)
    except (ConnectionError, asyncio.TimeoutError):
        pass
    finally:
        _audio_active -= 1
        _procs.discard(proc)
        if proc.returncode is None:
            proc.kill()
        await proc.wait()


# --------------------------------------------------------------------------- reset
def clear_all() -> dict:
    """Stop every ffmpeg/ffprobe job and forget everything cached (used by /restart).

    Returns counts so the owner can see what was cleared.
    """
    killed = 0
    for proc in list(_procs):
        if proc.returncode is None:
            try:
                proc.kill()
                killed += 1
            except ProcessLookupError:
                pass
    _procs.clear()

    for task in list(_sub_tasks.values()):
        task.cancel()
    probes = len(_probe_cache)
    _probe_cache.clear()
    _probe_locks.clear()
    _sub_tasks.clear()
    _sub_errors.clear()

    files = freed = 0
    d = Path(Media.CACHE_DIR)
    if d.is_dir():
        for f in d.iterdir():
            if f.is_file():
                try:
                    size = f.stat().st_size
                    f.unlink()
                    files += 1
                    freed += size
                except OSError:
                    pass
    return {"jobs_killed": killed, "track_lists": probes, "subtitle_files": files, "bytes_freed": freed}
