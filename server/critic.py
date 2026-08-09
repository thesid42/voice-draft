"""Critic (SPEC.md §5 Critic, §7) -- fire-and-forget per content utterance.

The Critic never emits an interrupt directly: its verdict always goes
through server.gate.evaluate() first. TTS is synthesized BEFORE the
interrupt is broadcast so audio_url is immediately playable.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Awaitable, Callable

from server import config, tts
from server.gate import evaluate as gate_evaluate
from server.prompts import CRITIC_SYSTEM
from server.session import Objection, SessionState

logger = logging.getLogger("draft.critic")

Broadcast = Callable[[dict], Awaitable[None]]


def _build_user_message(state: SessionState, utterance: dict) -> str:
    lines = ["TRANSCRIPT:"]
    if state.transcript:
        for u in state.transcript:
            lines.append(f"[{u.get('ts')}] {u.get('text')}")
    else:
        lines.append("(empty)")

    lines.append("")
    lines.append("CURRENT BLOCKS:")
    if state.block_order:
        for bid in state.block_order:
            lines.append(f"{bid}: {state.blocks[bid]}")
    else:
        lines.append("(none yet)")

    lines.append("")
    lines.append("OBJECTIONS ALREADY RAISED:")
    if state.objections:
        for o in state.objections:
            lines.append(f"{o.id} [{o.kind}] status={o.status} refs={o.refs}: {o.message}")
    else:
        lines.append("(none)")

    lines.append("")
    lines.append(f"LATEST UTTERANCE: {utterance.get('text')}")
    return "\n".join(lines)


async def handle_content_utterance(state: SessionState, utterance: dict, broadcast: Broadcast) -> None:
    """Schedule the critic evaluation as an independent background task.

    Fire-and-forget by design: the caller does not await the LLM round trip.
    """
    asyncio.create_task(_run(state, utterance, broadcast))


async def _run(state: SessionState, utterance: dict, broadcast: Broadcast) -> None:
    gen = state.generation

    if not config.has_openai_key():
        logger.info("critic skipped: no OPENAI_API_KEY")
        return
    client = config.get_openai_client()
    if client is None:
        logger.info("critic skipped: no OpenAI client")
        return

    messages = [
        {"role": "system", "content": CRITIC_SYSTEM},
        {"role": "user", "content": _build_user_message(state, utterance)},
    ]

    try:
        response = await client.chat.completions.create(
            model=config.MODEL_CRITIC,
            response_format={"type": "json_object"},
            temperature=0.2,
            messages=messages,
        )
        data = json.loads(response.choices[0].message.content)
    except json.JSONDecodeError:
        logger.info("critic json parse failure -> stay_silent")
        return
    except Exception as exc:  # noqa: BLE001 - swallow all OpenAI errors
        logger.info("critic openai error=%s -> stay_silent", exc)
        return

    if state.generation != gen:
        logger.info("critic run aborted: session was reset mid-run")
        return

    action = data.get("action")
    if action != "interrupt":
        logger.info("critic verdict=stay_silent")
        return

    confidence = data.get("confidence", 0.0)
    kind = data.get("kind")
    logger.info("critic verdict=interrupt kind=%s confidence=%s", kind, confidence)

    now = time.monotonic()
    allowed, reason = gate_evaluate(
        state,
        data,
        conf_floor=config.runtime_config["CONF_FLOOR"],
        cooldown_s=config.runtime_config["COOLDOWN_S"],
        min_utterances_between=config.runtime_config["MIN_UTTERANCES_BETWEEN"],
        now=now,
    )
    if not allowed:
        logger.info("gate decision=drop reason=%s", reason)
        return

    message = data.get("message", "") or ""
    refs = data.get("refs", []) or []
    objection_id = state.next_objection_id()

    audio_url = await tts.synthesize(objection_id, message)

    if state.generation != gen:
        logger.info("critic interrupt aborted post-tts: session was reset mid-run")
        return

    state.objections.append(
        Objection(id=objection_id, kind=kind, message=message, refs=refs, status="spoken")
    )
    state.last_interrupt_ts = now
    state.utterances_since_interrupt = 0

    logger.info("gate decision=allow id=%s", objection_id)
    await broadcast(
        {
            "type": "interrupt",
            "id": objection_id,
            "kind": kind,
            "message": message,
            "refs": refs,
            "audio_url": audio_url,
        }
    )
