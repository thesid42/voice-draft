"""MCP server factory (SPEC.md §14.A) -- the VoiceOS-facing tool surface.

`build_mcp_server(deps)` registers the 8 Draft tools on a fresh MCPServer
and returns it. Every tool handler is THIN: it calls straight into `deps`
(callables supplied by server/main.py that already wrap the existing
WS pipeline helpers) and never re-implements any pipeline logic -- zero
duplication between the WS path and the MCP path.

No import of server.main at module scope (main.py imports THIS module to
call build_mcp_server(), so the reverse import would be circular). `deps` is
a small dataclass defined right here instead.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from mcp.server import MCPServer

from server import config
from server.session import Objection, SessionState, objection_to_dict

logger = logging.getLogger("draft.mcp")

Broadcast = Callable[[dict], Awaitable[None]]


@dataclass
class MCPDeps:
    """Callables/state supplied by server/main.py. Every `handle_*` here IS
    (or thinly wraps) the same function the WS/router path already calls --
    see SPEC.md §14.A "MCP tools funnel through the existing pipeline
    helpers"."""

    state: SessionState
    broadcast: Broadcast
    hello_message: Callable[[], dict]
    # draft_add's own pipeline call: router-defensive, then the same
    # _handle_content() the WS path uses, waiting up to
    # config.MCP_OBJECTION_WAIT_S for THIS utterance's own critic verdict.
    handle_add: Callable[[str], Awaitable[Optional[Objection]]]
    handle_finish: Callable[[], Awaitable[str]]
    handle_readback: Callable[[], Awaitable[Optional[str]]]
    handle_dismiss: Callable[[], Awaitable[Optional[str]]]
    handle_reset: Callable[[], Awaitable[str]]
    handle_export: Callable[[], Awaitable[str]]
    handle_share: Callable[[], Awaitable[str]]
    snapshot: Callable[[], dict]


def _objection_seq(objection_id: str) -> int:
    """Objection id 'o12' -> 12. Ids are minted strictly increasing (§13.E),
    so the numeric suffix doubles as a delivery watermark with no extra
    field on Objection."""
    try:
        return int(objection_id[1:])
    except (ValueError, IndexError):
        return 0


def build_mcp_server(deps: MCPDeps) -> MCPServer:
    mcp = MCPServer(name="draft")

    # Mutable across tool calls for the life of the process (single session,
    # single process -- SPEC.md §2). No lock needed: every await point below
    # is explicit and nothing here does file/network I/O of its own.
    mcp_state = {"last_delivered_seq": 0}

    async def _maybe_flip_browser_tts() -> None:
        """First MCP tool call, ever, auto-flips BROWSER_TTS to 0 unless the
        user explicitly chose a value (env var or a prior set_config) --
        second-echo-loop mitigation (SPEC.md §14.A). Runs before the tool's
        own work so even that very first call gets the flipped behavior."""
        if config.is_explicit("BROWSER_TTS"):
            return
        config.set_config("BROWSER_TTS", 0)
        logger.info("mcp: first tool call, auto-flipped BROWSER_TTS 1 -> 0")
        await deps.broadcast(deps.hello_message())

    def _pending_objection() -> Optional[dict]:
        """An objection newer than the last one we handed back, if any
        (SPEC.md §14.A): fired-late verdicts, or another tool's objection
        that arrived between calls, surface here exactly once."""
        candidates = [
            o
            for o in deps.state.objections
            if o.status in ("spoken", "answered") and _objection_seq(o.id) > mcp_state["last_delivered_seq"]
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda o: _objection_seq(o.id))
        newest = candidates[-1]
        mcp_state["last_delivered_seq"] = _objection_seq(newest.id)
        return objection_to_dict(newest)

    def _finalize(base: dict) -> dict:
        """Every tool result carries has_openai_key and, when one exists,
        pending_objection (SPEC.md §14.A)."""
        result = dict(base)
        result["has_openai_key"] = config.has_openai_key()
        pending = _pending_objection()
        if pending is not None:
            result["pending_objection"] = pending
        return result

    @mcp.tool(
        description=(
            "Add a spoken/dictated line to the document. Content only -- "
            "this never routes as a command, even if the text looks like "
            "one; use the other draft_* tools for commands."
        )
    )
    async def draft_add(text: str) -> dict:
        logger.info("mcp tool=draft_add text=%r", text)
        await _maybe_flip_browser_tts()
        await deps.handle_add(text)
        return _finalize({"ok": True})

    @mcp.tool(
        description=(
            "Call once, at the end, when the user confirms they're done -- "
            "this runs an irreversible polish rewrite."
        )
    )
    async def draft_wrap_up() -> dict:
        logger.info("mcp tool=draft_wrap_up")
        await _maybe_flip_browser_tts()
        markdown = await deps.handle_finish()
        return _finalize({"ok": True, "markdown": markdown})

    @mcp.tool(description="Read back only the most recent paragraph.")
    async def draft_read_back() -> dict:
        logger.info("mcp tool=draft_read_back")
        await _maybe_flip_browser_tts()
        text = await deps.handle_readback()
        return _finalize({"ok": text is not None, "text": text or ""})

    @mcp.tool(description="Dismiss the most recently spoken, unanswered objection.")
    async def draft_ignore_objection() -> dict:
        logger.info("mcp tool=draft_ignore_objection")
        await _maybe_flip_browser_tts()
        dismissed_id = await deps.handle_dismiss()
        return _finalize({"ok": dismissed_id is not None, "dismissed_id": dismissed_id})

    @mcp.tool(
        description="Start a brand new document, clearing the current transcript, blocks, and objections."
    )
    async def draft_new_document() -> dict:
        logger.info("mcp tool=draft_new_document")
        await _maybe_flip_browser_tts()
        new_slug = await deps.handle_reset()
        return _finalize({"ok": True, "slug": new_slug})

    @mcp.tool(description="Get the full document -- title, all paragraph blocks, and objections.")
    async def draft_get_document() -> dict:
        logger.info("mcp tool=draft_get_document")
        await _maybe_flip_browser_tts()
        snap = deps.snapshot()
        return _finalize(snap)

    @mcp.tool(description="Export the current document as Markdown text.")
    async def draft_export() -> dict:
        logger.info("mcp tool=draft_export")
        await _maybe_flip_browser_tts()
        markdown = await deps.handle_export()
        return _finalize({"ok": True, "markdown": markdown})

    @mcp.tool(description="Create a shareable live-audience URL for the current document.")
    async def draft_share() -> dict:
        logger.info("mcp tool=draft_share")
        await _maybe_flip_browser_tts()
        url = await deps.handle_share()
        return _finalize({"ok": True, "url": url})

    return mcp
