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
from typing import Awaitable, Callable, Optional

from server import config, mirror, tts
from server.gate import evaluate as gate_evaluate
from server.prompts import CRITIC_SYSTEM
from server.session import Objection, SessionState, objection_to_dict

logger = logging.getLogger("draft.critic")

Broadcast = Callable[[dict], Awaitable[None]]
# Invoked exactly once at the end of every _run() (SPEC.md §14.A): the fired
# Objection, or None on stay_silent/error/gate-drop/reset-abort. Lets the MCP
# draft_add tool wait (with a timeout) for its own utterance's verdict
# without a second critic call path.
OnResult = Callable[[Optional[Objection]], Awaitable[None]]


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
    enabled = config.enabled_critic_kinds()
    if enabled:
        lines.append(f"ENABLED INTERRUPT KINDS (stay silent for any other kind): {', '.join(enabled)}")
    else:
        lines.append("ENABLED INTERRUPT KINDS: none — you MUST stay_silent.")

    lines.append("")
    lines.append(f"LATEST UTTERANCE: {utterance.get('text')}")
    return "\n".join(lines)


async def handle_content_utterance(
    state: SessionState,
    utterance: dict,
    broadcast: Broadcast,
    on_result: Optional[OnResult] = None,
) -> None:
    """Schedule the critic evaluation as an independent background task.

    Fire-and-forget by design: the caller does not await the LLM round trip.
    """
    asyncio.create_task(_run(state, utterance, broadcast, on_result))


async def _run(
    state: SessionState,
    utterance: dict,
    broadcast: Broadcast,
    on_result: Optional[OnResult] = None,
) -> None:
    gen = state.generation

    async def _finish(result: Optional[Objection]) -> None:
        if on_result is None:
            return
        try:
            await on_result(result)
        except Exception:  # noqa: BLE001 - a caller's callback bug must not
            # blow up the critic task.
            logger.exception("critic on_result callback raised")

    if not config.enabled_critic_kinds():
        logger.info("critic skipped: all interrupt kinds disabled")
        await _finish(None)
        return

    if not config.has_openai_key():
        logger.info("critic skipped: no OPENAI_API_KEY")
        await _finish(None)
        return
    client = config.get_openai_client()
    if client is None:
        logger.info("critic skipped: no OpenAI client")
        await _finish(None)
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
        await _finish(None)
        return
    except Exception as exc:  # noqa: BLE001 - swallow all OpenAI errors
        logger.info("critic openai error=%s -> stay_silent", exc)
        await _finish(None)
        return

    if state.generation != gen:
        logger.info("critic run aborted: session was reset mid-run")
        await _finish(None)
        return

    action = data.get("action")
    if action != "interrupt":
        logger.info("critic verdict=stay_silent")
        await _finish(None)
        return

    confidence = data.get("confidence", 0.0)
    kind = data.get("kind")
    logger.info("critic verdict=interrupt kind=%s confidence=%s", kind, confidence)

    if not config.critic_kind_enabled(kind):
        logger.info("critic interrupt skipped: kind=%s disabled", kind)
        await _finish(None)
        return

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
        await _finish(None)
        return

    message = data.get("message", "") or ""
    refs = data.get("refs", []) or []
    # Refs sanitation: the model sometimes returns [] or ids that don't exist,
    # which glows nothing (or the wrong block) in the UI. Keep only real block
    # ids; if none survive, anchor to the newest block — the trigger
    # utterance's content is almost always the last thing written.
    refs = [r for r in refs if r in state.blocks]
    if not refs and state.block_order:
        refs = [state.block_order[-1]]
    # A contradiction has two sides; the model often lists only the earlier
    # one. The new conflicting statement is almost always the newest block —
    # include it so BOTH sides glow.
    if kind == "contradiction" and len(refs) == 1 and state.block_order:
        newest = state.block_order[-1]
        if newest not in refs:
            refs.append(newest)
    objection_id = state.next_objection_id()

    # Claim cooldown + dedup BEFORE TTS. Two critic tasks often finish
    # together; if we wait until after synth, both pass the gate, the
    # client starts clip A then immediately kill+plays clip B — that
    # sounds like a beep. Spec counters update "when an interrupt fires";
    # fire = gate allow, not "after mp3 lands".
    objection = Objection(id=objection_id, kind=kind, message=message, refs=refs, status="spoken")
    state.objections.append(objection)
    state.last_interrupt_ts = now
    state.utterances_since_interrupt = 0
    logger.info("gate decision=allow id=%s", objection_id)

    audio_url = None
    if config.runtime_config["BROWSER_TTS"]:
        audio_url = await tts.synthesize(objection_id, message)
    else:
        logger.info("interrupt id=%s audio skipped: BROWSER_TTS=0", objection_id)

    if state.generation != gen:
        logger.info("critic interrupt aborted post-tts: session was reset mid-run")
        await _finish(None)
        return
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
    mirror.upsert_objection(state.slug, objection_to_dict(objection))
    await _finish(objection)
