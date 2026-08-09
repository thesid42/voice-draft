"""Environment + runtime-tunable configuration for the Draft server.

All thresholds/tunables the Gate and DevPanel care about live here. A subset
(CONF_FLOOR, COOLDOWN_S, GRACE_MS, PAUSE_MS, MIN_UTTERANCES_BETWEEN) is
runtime-mutable via the `set_config` WS control and is echoed back to clients
in the `hello` message (see server/main.py and SPEC.md §13.A).

The AsyncOpenAI client is created lazily (see get_openai_client()) so the
server boots cleanly with no OPENAI_API_KEY set (SPEC.md §13.D).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI

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


# --- Static config (not runtime-mutable) ---------------------------------

OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "") or ""
MODEL_WRITER: str = _str_env("MODEL_WRITER", "gpt-4o")
MODEL_CRITIC: str = _str_env("MODEL_CRITIC", "gpt-4o")
TTS_MODEL: str = _str_env("TTS_MODEL", "tts-1")
TTS_VOICE: str = _str_env("TTS_VOICE", "onyx")

# Gate rule 4 (duplicate objection message) similarity threshold. Jaccard
# over lowercase, punctuation-stripped token sets. Fixed per SPEC.md §13.E
# (not part of the runtime-mutable/hello set).
DUP_JACCARD_THRESHOLD: float = 0.6

# --- Runtime-mutable tunables (exposed via hello / set_config) -----------
# Types matter here: CONF_FLOOR is a float, the rest are ints. Keep it that
# way so `hello` JSON matches SPEC.md §13.A byte-for-byte (e.g. 45 not 45.0).

runtime_config: dict[str, float | int] = {
    "CONF_FLOOR": _float_env("CONF_FLOOR", 0.75),
    "COOLDOWN_S": _int_env("COOLDOWN_S", 45),
    "GRACE_MS": _int_env("GRACE_MS", 2500),
    "PAUSE_MS": _int_env("PAUSE_MS", 700),
    "MIN_UTTERANCES_BETWEEN": _int_env("MIN_UTTERANCES_BETWEEN", 2),
}


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
    return True


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
        _client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    return _client
