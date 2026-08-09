"""Debounced Writer loop + finish-flow polish pass (SPEC.md §5 Writer, §7).

One run at a time per session. Content utterances arriving while a run is
in flight are queued in state.pending_utterances and batched into the next
run once the current one finishes (drain loop). status:thinking / status:idle
bracket the whole drain (not each individual LLM call).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Awaitable, Callable

from server import config, mirror
from server.prompts import POLISH_SYSTEM, WRITER_SYSTEM
from server.session import SessionState, apply_patches, doc_update_blocks, render_markdown

logger = logging.getLogger("draft.writer")

Broadcast = Callable[[dict], Awaitable[None]]


def submit_utterance(state: SessionState, utterance: dict, broadcast: Broadcast) -> None:
    """Queue a content utterance and (if idle) kick off the drain loop.

    Non-blocking: returns immediately. The actual writer run(s) happen in a
    background asyncio task so the WS receive loop stays free to keep
    accepting more utterances while the writer "thinks".
    """
    state.pending_utterances.append(utterance)
    if not state.writer_running:
        state.writer_running = True
        asyncio.create_task(_drain_loop(state, broadcast))


async def _drain_loop(state: SessionState, broadcast: Broadcast) -> None:
    await broadcast({"type": "status", "writer": "thinking"})
    try:
        while state.pending_utterances:
            batch = state.pending_utterances
            state.pending_utterances = []
            await _run_pass(state, batch, broadcast)
    finally:
        state.writer_running = False
        await broadcast({"type": "status", "writer": "idle"})


def _build_user_message(state: SessionState, batch: list[dict]) -> str:
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
    lines.append("EDITOR OBJECTIONS (if a new utterance answers one, integrate the answer into its referenced blocks):")
    if state.objections:
        for o in state.objections:
            lines.append(f"{o.id} [{o.kind}] status={o.status} refs={o.refs}: {o.message}")
    else:
        lines.append("(none)")

    lines.append("")
    lines.append(f"NEXT UNUSED BLOCK ID (use this or higher for new blocks): {state.peek_next_block_id()}")

    lines.append("")
    lines.append("NEW UTTERANCES SINCE LAST RUN:")
    for u in batch:
        lines.append(f"- {u.get('text')}")

    return "\n".join(lines)


async def _call_writer_with_retry(client, messages: list[dict]) -> dict | None:
    """Call the Writer model; on a JSON parse failure, retry once with a
    'return only valid JSON' reminder appended (SPEC.md §13.D). Returns None
    (and logs) if both attempts fail, or on any OpenAI error.
    """
    for attempt in (1, 2):
        try:
            response = await client.chat.completions.create(
                model=config.MODEL_WRITER,
                response_format={"type": "json_object"},
                temperature=0.3,
                messages=messages,
            )
        except Exception as exc:  # noqa: BLE001 - swallow all OpenAI errors
            logger.info("writer openai error attempt=%d error=%s", attempt, exc)
            return None

        content = response.choices[0].message.content
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            logger.info("writer json parse failure attempt=%d", attempt)
            if attempt == 1:
                messages = messages + [
                    {"role": "user", "content": "Return ONLY valid JSON."}
                ]
                continue
            logger.info("writer json parse failed twice, dropping run")
            return None
    return None


async def _run_pass(state: SessionState, batch: list[dict], broadcast: Broadcast) -> None:
    start = time.monotonic()
    gen = state.generation
    logger.info("writer run start utterances=%d", len(batch))

    if not config.has_openai_key():
        logger.info("writer skipped: no OPENAI_API_KEY")
        return
    client = config.get_openai_client()
    if client is None:
        logger.info("writer skipped: no OpenAI client")
        return

    messages = [
        {"role": "system", "content": WRITER_SYSTEM},
        {"role": "user", "content": _build_user_message(state, batch)},
    ]
    data = await _call_writer_with_retry(client, messages)
    duration_ms = (time.monotonic() - start) * 1000

    if state.generation != gen:
        logger.info("writer run aborted: session was reset mid-run")
        return

    if data is None:
        logger.info("writer run end duration_ms=%.0f patches=0 (failed)", duration_ms)
        return

    patches = data.get("patches", []) or []
    title = data.get("title")

    existing_count = max(1, len(state.block_order))
    replace_count = sum(1 for p in patches if isinstance(p, dict) and p.get("op") == "replace")
    thrash = (replace_count / existing_count) > 0.6

    touched = apply_patches(state, patches)
    if title:
        state.title = title

    logger.info(
        "writer run end duration_ms=%.0f patches=%d thrash=%s",
        duration_ms,
        len(patches),
        thrash,
    )

    await broadcast(
        {
            "type": "doc_update",
            "title": state.title,
            "blocks": doc_update_blocks(state, touched),
        }
    )
    mirror.update_doc(
        state.slug,
        state.title,
        [{"id": bid, "text": state.blocks[bid]} for bid in state.block_order],
    )


async def run_polish(state: SessionState) -> str:
    """Finish flow: one full-document polish pass (SPEC.md §5 Finish flow).

    Returns markdown. Falls back to the plain (unpolished) rendering on any
    failure (no key, network error, empty response) -- finish must always
    produce a final_doc, never hang or crash.
    """
    fallback = render_markdown(state)

    if not config.has_openai_key():
        logger.info("polish skipped: no OPENAI_API_KEY, falling back to plain render")
        return fallback

    client = config.get_openai_client()
    if client is None:
        logger.info("polish skipped: no OpenAI client, falling back to plain render")
        return fallback

    lines = ["TRANSCRIPT:"]
    for u in state.transcript:
        lines.append(f"[{u.get('ts')}] {u.get('text')}")
    lines.append("")
    lines.append(f"TITLE: {state.title or '(untitled)'}")
    lines.append("")
    lines.append("CURRENT BLOCKS:")
    for bid in state.block_order:
        lines.append(f"{bid}: {state.blocks[bid]}")
    lines.append("")
    lines.append("OBJECTIONS RAISED (resolve points the speaker clarified):")
    if state.objections:
        for o in state.objections:
            lines.append(f"{o.id} [{o.kind}] status={o.status} refs={o.refs}: {o.message}")
    else:
        lines.append("(none)")

    messages = [
        {"role": "system", "content": POLISH_SYSTEM},
        {"role": "user", "content": "\n".join(lines)},
    ]

    start = time.monotonic()
    try:
        response = await client.chat.completions.create(
            model=config.MODEL_WRITER,
            temperature=0.3,
            messages=messages,
        )
        markdown = (response.choices[0].message.content or "").strip()
        duration_ms = (time.monotonic() - start) * 1000
        if not markdown:
            logger.info("polish empty response ms=%.0f, falling back to plain render", duration_ms)
            return fallback
        logger.info("polish ok ms=%.0f chars=%d", duration_ms, len(markdown))
        return markdown + "\n"
    except Exception as exc:  # noqa: BLE001 - must never crash the process
        duration_ms = (time.monotonic() - start) * 1000
        logger.info("polish failed ms=%.0f error=%s, falling back to plain render", duration_ms, exc)
        return fallback
