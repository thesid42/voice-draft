"""Environment + runtime-tunable configuration for the Draft server.

All thresholds/tunables the Gate and DevPanel care about live here. A subset
(CONF_FLOOR, COOLDOWN_S, GRACE_MS, PAUSE_MS, MIN_UTTERANCES_BETWEEN) is
runtime-mutable via the `set_config` WS control and is echoed back to clients
in the `hello` message (see server/main.py and SPEC.md §13.A).

The AsyncOpenAI client is created lazily (see get_openai_client()) so the
server boots cleanly with no OPENAI_API_KEY set (SPEC.md §13.D).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI

logger = logging.getLogger("draft.config")

REPO_ROOT = Path(__file__).resolve().parent.parent

# Load .env from repo root if present. No-ops silently if missing (this
# machine has none set up, which is an expected/valid configuration).
load_dotenv(REPO_ROOT / ".env")


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(float(raw))
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _str_env(name: str, default: str) -> str:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw


def _env_present(name: str) -> bool:
    raw = os.environ.get(name)
    return raw is not None and raw.strip() != ""


# --- Static config (not runtime-mutable) ---------------------------------

OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "") or ""
# Optional OpenAI-compatible base URL (e.g. OpenRouter). Empty = api.openai.com.
OPENAI_BASE_URL: str = _str_env("OPENAI_BASE_URL", "")
MODEL_WRITER: str = _str_env("MODEL_WRITER", "gpt-4o")
MODEL_CRITIC: str = _str_env("MODEL_CRITIC", "gpt-4o")
TTS_MODEL: str = _str_env("TTS_MODEL", "tts-1")
TTS_VOICE: str = _str_env("TTS_VOICE", "onyx")

# Gate rule 4 (duplicate objection message) similarity threshold. Jaccard
# over lowercase, punctuation-stripped token sets. Fixed per SPEC.md §13.E
# (not part of the runtime-mutable/hello set).
DUP_JACCARD_THRESHOLD: float = 0.6

# MCP objection delivery wait (SPEC.md §14.A): draft_add waits this long for
# ITS OWN utterance's critic verdict before returning without one. A verdict
# that arrives later still fires normally (broadcast + mirrored) and surfaces
# as `pending_objection` on a later tool result.
MCP_OBJECTION_WAIT_S: float = _float_env("MCP_OBJECTION_WAIT_S", 2.0)

# Convex live-share mirror (SPEC.md §14.B) and audience share links. Both
# optional -- server/mirror.py is a silent no-op without CONVEX_URL, and an
# empty AUDIENCE_BASE_URL still works (Convex/Pages just aren't live yet).
CONVEX_URL: str = _str_env("CONVEX_URL", "")
AUDIENCE_BASE_URL: str = _str_env("AUDIENCE_BASE_URL", "http://localhost:5173/watch.html#")

# --- Runtime-mutable tunables (exposed via hello / set_config) -----------
# Types matter here: CONF_FLOOR is a float, the rest are ints. Keep it that
# way so `hello` JSON matches SPEC.md §13.A byte-for-byte (e.g. 45 not 45.0).

runtime_config: dict[str, float | int] = {
    "CONF_FLOOR": _float_env("CONF_FLOOR", 0.75),
    "COOLDOWN_S": _int_env("COOLDOWN_S", 45),
    "GRACE_MS": _int_env("GRACE_MS", 2500),
    "PAUSE_MS": _int_env("PAUSE_MS", 700),
    "MIN_UTTERANCES_BETWEEN": _int_env("MIN_UTTERANCES_BETWEEN", 2),
    # BROWSER_TTS (SPEC.md §14.A): 1 = server synthesizes TTS for interrupts
    # and readbacks as usual; 0 = skip synthesis, audio_url always null (the
    # MCP layer auto-flips this once, unless explicitly set -- see
    # _EXPLICIT below).
    "BROWSER_TTS": _int_env("BROWSER_TTS", 1),
}

# Keys the user has explicitly chosen (env var present at startup, or a live
# set_config control) as opposed to just sitting at their code default.
# Consumed today only for BROWSER_TTS (SPEC.md §14.A: the MCP layer's
# first-tool-call auto-flip to 0 must not clobber a value the user picked on
# purpose) but tracked generically since set_config can touch any key.
_EXPLICIT: set[str] = set()
if _env_present("BROWSER_TTS"):
    _EXPLICIT.add("BROWSER_TTS")


def has_openai_key() -> bool:
    return bool(OPENAI_API_KEY)


def get_config_for_hello() -> dict:
    cfg = dict(runtime_config)
    cfg["has_openai_key"] = has_openai_key()
    return cfg


def set_config(key: str, value) -> bool:
    """Update a runtime-mutable config key in place.

    Returns True if the key was recognized and applied, False if unknown
    (caller logs+ignores unknown keys per SPEC.md §13.A.2).
    """
    if key not in runtime_config:
        return False
    current = runtime_config[key]
    try:
        if isinstance(current, float):
            runtime_config[key] = float(value)
        else:
            runtime_config[key] = int(value)
    except (TypeError, ValueError):
        return False
    _EXPLICIT.add(key)
    return True


def is_explicit(key: str) -> bool:
    """True if `key` was set by the user (env var at startup, or a live
    set_config control) rather than left at its code default."""
    return key in _EXPLICIT


# --- Lazy AsyncOpenAI client ------------------------------------------------

_client: Optional[AsyncOpenAI] = None


def get_openai_client() -> Optional[AsyncOpenAI]:
    """Return a lazily-constructed AsyncOpenAI client, or None if no API key.

    Never called at import time anywhere in this codebase -- only from
    inside the async writer/critic/tts call paths, right before use.
    """
    global _client
    if not OPENAI_API_KEY:
        return None
    if _client is None:
        kwargs: dict = {"api_key": OPENAI_API_KEY}
        if OPENAI_BASE_URL:
            kwargs["base_url"] = OPENAI_BASE_URL
        _client = AsyncOpenAI(**kwargs)
        logger.info(
            "openai client ready base_url=%s writer=%s critic=%s",
            OPENAI_BASE_URL or "https://api.openai.com/v1",
            MODEL_WRITER,
            MODEL_CRITIC,
        )
    return _client
