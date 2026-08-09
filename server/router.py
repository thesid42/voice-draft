"""Command router (SPEC.md §5 Router).

Runs on every utterance, before anything else. Pure/stateless: classifies
text into a route kind. Callers (server/main.py, server/replay.py via the
same code path) perform the actual side effects.
"""
from __future__ import annotations

import re
import string
from dataclasses import dataclass

COMMAND_PREFIXES = ("draft", "draught")  # "draught" - ASR misspells "draft"

_PUNCT_TABLE = str.maketrans("", "", string.punctuation)


def normalize(text: str) -> str:
    """lowercase, strip punctuation, collapse whitespace."""
    text = text.lower().translate(_PUNCT_TABLE)
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class RouteResult:
    kind: str  # "content" | "finish" | "readback" | "dismiss" | "export" | "reset"
    raw_text: str
    normalized: str


def route(text: str) -> RouteResult:
    normalized = normalize(text)
    tokens = normalized.split(" ") if normalized else []

    if tokens and tokens[0] in COMMAND_PREFIXES:
        rest = " ".join(tokens[1:])

        if "wrap" in rest:
            return RouteResult("finish", text, normalized)
        if "read" in rest and ("back" in rest or "that" in rest):
            return RouteResult("readback", text, normalized)
        if "ignore" in rest or "dismiss" in rest:
            return RouteResult("dismiss", text, normalized)
        if "export" in rest:
            return RouteResult("export", text, normalized)
        if "new" in rest or "start over" in rest:
            return RouteResult("reset", text, normalized)
        # unrecognized after "draft"/"draught" -> fail open to content
        return RouteResult("content", text, normalized)

    return RouteResult("content", text, normalized)
