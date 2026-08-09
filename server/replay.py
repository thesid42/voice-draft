"""Replay engine (SPEC.md §5 Replay engine, §13.E paths) -- demo fallback.

Reads demo/replay_script.json and feeds its events through the exact same
`handle_message` entry point server/main.py uses for live WS utterances, with
real delays between events (as an asyncio task). Indistinguishable from live
input downstream: router -> writer/critic -> gate all run unmodified.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Awaitable, Callable, Optional

logger = logging.getLogger("draft.replay")

HandleMessage = Callable[[dict], Awaitable[None]]

_task: Optional[asyncio.Task] = None


def is_running() -> bool:
    return _task is not None and not _task.done()


async def start(repo_root: Path, handle_message: HandleMessage) -> tuple[bool, str]:
    """Start replaying demo/replay_script.json. Returns (ok, message)."""
    global _task
    if is_running():
        logger.info("replay start rejected: already running")
        return False, "replay already running"

    script_path = repo_root / "demo" / "replay_script.json"
    if not script_path.exists():
        logger.info("replay start failed: script not found at %s", script_path)
        return False, f"replay script not found at {script_path}"

    try:
        raw = script_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        events = data.get("events", [])
        if not isinstance(events, list):
            raise ValueError("'events' is not a list")
    except Exception as exc:  # noqa: BLE001
        logger.info("replay start failed: could not read/parse script: %s", exc)
        return False, f"could not read/parse replay script: {exc}"

    logger.info("replay start events=%d", len(events))
    _task = asyncio.create_task(_run(events, handle_message))
    return True, f"replay started ({len(events)} events)"


async def stop() -> tuple[bool, str]:
    """Cancel a running replay. Returns (ok, message)."""
    global _task
    if not is_running():
        logger.info("replay stop rejected: not running")
        return False, "replay not running"
    _task.cancel()
    logger.info("replay stop requested")
    return True, "replay stopped"


async def _run(events: list[dict], handle_message: HandleMessage) -> None:
    global _task
    try:
        for event in events:
            if not isinstance(event, dict):
                continue
            delay_ms = event.get("delay_ms", 0) or 0
            if delay_ms:
                await asyncio.sleep(delay_ms / 1000)
            message = {k: v for k, v in event.items() if k != "delay_ms"}
            logger.info("replay event type=%s", message.get("type"))
            try:
                await handle_message(message)
            except Exception:  # noqa: BLE001 - one bad event must not kill replay
                logger.exception("replay event handler error, continuing")
        logger.info("replay complete")
    except asyncio.CancelledError:
        logger.info("replay cancelled")
        raise
    finally:
        _task = None
