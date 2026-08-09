"""Interrupt Gate (SPEC.md §5 Gate) -- pure functions, no I/O, no LLM calls.

The Critic never emits an interrupt directly; its verdict always passes
through evaluate() first. All thresholds are read from server.config at
call time (runtime-mutable via the set_config WS control).
"""
from __future__ import annotations

import string
from typing import Optional

from server.config import DUP_JACCARD_THRESHOLD
from server.session import SessionState

_PUNCT_TABLE = str.maketrans("", "", string.punctuation)


def _tokenize(text: str) -> set[str]:
    text = (text or "").lower().translate(_PUNCT_TABLE)
    return {t for t in text.split() if t}


def jaccard(a: str, b: str) -> float:
    """Jaccard similarity over lowercase, punctuation-stripped token sets."""
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    union = ta | tb
    if not union:
        return 0.0
    return len(ta & tb) / len(union)


def evaluate(
    state: SessionState,
    candidate: dict,
    *,
    conf_floor: float,
    cooldown_s: float,
    min_utterances_between: int,
    now: float,
) -> tuple[bool, Optional[str]]:
    """Decide whether a candidate interrupt from the Critic should fire.

    Returns (allowed, drop_reason). drop_reason is None iff allowed is True.
    Rule order matches SPEC.md §5 Gate (1-5); first failing rule wins.
    """
    confidence = candidate.get("confidence", 0.0)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0

    # 1. confidence floor
    if confidence < conf_floor:
        return False, "confidence_below_floor"

    # 2. cooldown since last interrupt
    if state.last_interrupt_ts is not None and (now - state.last_interrupt_ts) < cooldown_s:
        return False, "cooldown"

    # 3. minimum content utterances since last interrupt
    if state.utterances_since_interrupt < min_utterances_between:
        return False, "min_utterances"

    candidate_message = candidate.get("message", "") or ""
    candidate_kind = candidate.get("kind")
    candidate_refs = tuple(sorted(candidate.get("refs", []) or []))

    # 4. token-overlap (Jaccard) similarity vs any prior objection message
    for obj in state.objections:
        if jaccard(candidate_message, obj.message) >= DUP_JACCARD_THRESHOLD:
            return False, "duplicate_message"

    # 5. same (kind, sorted(refs)) already exists
    for obj in state.objections:
        if obj.kind == candidate_kind and tuple(sorted(obj.refs)) == candidate_refs:
            return False, "duplicate_kind_refs"

    return True, None
