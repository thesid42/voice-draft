"""OpenAI TTS -> mp3 bytes, in-memory cache (SPEC.md §5 TTS, §13.E ids).

Served by server/main.py at GET /tts/{id}.mp3. Never raises: callers get
None back on any failure (no key, network error, API error) and degrade
gracefully per SPEC.md §13.D (interrupt/readback still broadcasts, just
with audio_url null).
"""
from __future__ import annotations

import inspect
import logging
import time
from typing import Optional

from server import config

logger = logging.getLogger("draft.tts")

CACHE: dict[str, bytes] = {}


def get(tts_id: str) -> Optional[bytes]:
    return CACHE.get(tts_id)


async def synthesize(tts_id: str, text: str) -> Optional[str]:
    """Synthesize `text` to mp3, cache it under `tts_id`, return its URL.

    Returns None (and logs one line) on any failure -- missing key, network
    error, API error -- without raising. Synthesis happens BEFORE the caller
    broadcasts anything, so the returned URL (if any) is immediately playable.
    """
    if not text:
        return None

    if not config.has_openai_key():
        logger.info("tts skipped id=%s reason=no_api_key", tts_id)
        return None

    client = config.get_openai_client()
    if client is None:
        logger.info("tts skipped id=%s reason=no_client", tts_id)
        return None

    start = time.monotonic()
    try:
        response = await client.audio.speech.create(
            model=config.TTS_MODEL,
            voice=config.TTS_VOICE,
            input=text,
            response_format="mp3",
        )
        # SDK response shapes vary (HttpxBinaryResponseContent, streamed
        # httpx.Response, ...): .content may be plain bytes OR a property
        # that raises until the body is read; .read/.aread may be sync or
        # async. Try every shape without letting one failure mask another.
        audio_bytes = None
        try:
            candidate = response.content
            if isinstance(candidate, (bytes, bytearray)):
                audio_bytes = bytes(candidate)
        except Exception:
            audio_bytes = None
        if not audio_bytes:
            for reader in ("aread", "read"):
                fn = getattr(response, reader, None)
                if fn is None:
                    continue
                try:
                    maybe = fn()
                    if inspect.isawaitable(maybe):
                        maybe = await maybe
                    if isinstance(maybe, (bytes, bytearray)):
                        audio_bytes = bytes(maybe)
                except Exception:
                    audio_bytes = None
                if audio_bytes:
                    break
        if not audio_bytes:
            raise ValueError("could not extract audio bytes from TTS response")
        CACHE[tts_id] = audio_bytes
        duration_ms = (time.monotonic() - start) * 1000
        logger.info("tts synth id=%s ms=%.0f bytes=%d", tts_id, duration_ms, len(audio_bytes))
        return f"/tts/{tts_id}.mp3"
    except Exception as exc:  # noqa: BLE001 - must never crash the process
        duration_ms = (time.monotonic() - start) * 1000
        logger.info("tts failed id=%s ms=%.0f error=%s", tts_id, duration_ms, exc)
        return None
