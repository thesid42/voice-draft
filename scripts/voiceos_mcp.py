#!/usr/bin/env python3
"""VoiceOS stdio MCP bridge (SPEC.md §14.A demo-day proxy).

VoiceOS Custom Integrations only spawn a local command over stdin/stdout.
This process is that command: it speaks MCP on stdio and forwards every
tool call to the running Draft server at DRAFT_MCP_URL
(default http://127.0.0.1:8000/mcp). Pipeline logic stays on the server.

Logs go to stderr only — stdout is the MCP wire.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer

# stdout is the protocol. Anything else must go to stderr.
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="voiceos-mcp %(levelname)s %(message)s")
logger = logging.getLogger("draft.voiceos_mcp")

DRAFT_MCP_URL = os.environ.get("DRAFT_MCP_URL", "http://127.0.0.1:8000/mcp").rstrip("/")

mcp = MCPServer(name="draft", version="1.0.0")


def _parse_tool_result(result) -> dict:
    sc = getattr(result, "structured_content", None)
    if isinstance(sc, dict):
        return sc
    for c in getattr(result, "content", []) or []:
        text = getattr(c, "text", None)
        if not text:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return {}


def _objection_line(payload: dict) -> str:
    obj = payload.get("pending_objection")
    if not isinstance(obj, dict):
        return ""
    message = (obj.get("message") or "").strip()
    if not message:
        return ""
    kind = (obj.get("kind") or "note").replace("_", " ")
    return f" The editor interrupted ({kind}): {message}"


def _speak(tool: str, payload: dict) -> str:
    """Turn a Draft tool dict into one thing VoiceOS can say out loud."""
    extra = _objection_line(payload)

    if tool == "draft_add":
        return ("Added to the draft." if payload.get("ok", True) else "Could not add that.") + extra
    if tool == "draft_wrap_up":
        md = payload.get("markdown") or ""
        title = ""
        if md.lstrip().startswith("#"):
            title = md.lstrip().split("\n", 1)[0].lstrip("# ").strip()
        base = f"Wrapped up the draft{f' titled {title}' if title else ''}."
        return base + extra
    if tool == "draft_read_back":
        text = (payload.get("text") or "").strip()
        if not text:
            return "Nothing to read back yet." + extra
        return text + extra
    if tool == "draft_ignore_objection":
        ok = payload.get("ok")
        return ("Ignored that objection." if ok else "There was no objection to ignore.") + extra
    if tool == "draft_new_document":
        return "Started a new document." + extra
    if tool == "draft_get_document":
        title = (payload.get("title") or "Untitled").strip() or "Untitled"
        blocks = payload.get("blocks") or []
        paras = []
        for b in blocks:
            if isinstance(b, dict):
                t = (b.get("text") or "").strip()
            else:
                t = str(b).strip()
            if t:
                paras.append(t)
        if not paras:
            return f"The document is titled {title}, but there are no paragraphs yet." + extra
        return f"{title}. " + " ".join(paras) + extra
    if tool == "draft_export":
        md = (payload.get("markdown") or "").strip()
        if not md:
            return "Nothing to export yet." + extra
        return md + extra
    if tool == "draft_share":
        url = (payload.get("url") or "").strip()
        if not url:
            return "Could not create a share link." + extra
        return f"Share link is ready: {url}" + extra
    if tool == "draft_list":
        if payload.get("configured") is False:
            return "Draft history needs Convex set up on the laptop first." + extra
        drafts = payload.get("drafts") or []
        if not drafts:
            return "You have no stored drafts yet." + extra
        parts = []
        for d in drafts[:6]:
            label = f"{d.get('index')}: {d.get('title')}"
            if d.get("status") == "finished":
                label += ", finished"
            parts.append(label)
        more = f" And {len(drafts) - 6} more." if len(drafts) > 6 else ""
        return (
            f"You have {len(drafts)} stored draft{'s' if len(drafts) != 1 else ''}. "
            + ". ".join(parts)
            + "."
            + more
            + " Say open draft and the number or name."
            + extra
        )
    if tool == "draft_open":
        if payload.get("configured") is False:
            return "Draft history needs Convex set up on the laptop first."
        if not payload.get("ok"):
            cands = payload.get("candidates") or []
            if cands:
                names = "; ".join(f"{c.get('index')}: {c.get('title')}" for c in cands)
                return f"I couldn't match that draft. Closest: {names}. Which one?"
            return "I couldn't find that draft." + extra
        title = payload.get("title") or "Untitled"
        n = payload.get("blocks") or 0
        return (
            f"Opened {title} — {n} paragraph{'s' if n != 1 else ''}. "
            "Keep talking to continue it." + extra
        )
    return json.dumps(payload)


async def _call(tool: str, arguments: dict | None = None) -> dict:
    timeout = httpx.Timeout(60.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as http:
        async with streamable_http_client(DRAFT_MCP_URL, http_client=http) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, arguments or {})
    payload = _parse_tool_result(result)
    logger.info("forward %s ok keys=%s", tool, sorted(payload.keys()))
    return payload


async def _forward(tool: str, arguments: dict | None = None) -> str:
    try:
        payload = await _call(tool, arguments)
    except Exception as exc:  # noqa: BLE001 — VoiceOS should hear a usable reason
        logger.info("forward %s failed: %s", tool, exc)
        return (
            f"Cannot reach the Draft server at {DRAFT_MCP_URL}. "
            "Start uvicorn on port 8000, keep the browser tab open, then try again."
        )
    return _speak(tool, payload)


@mcp.tool(
    description=(
        "Add the user's spoken thoughts to the live Draft document. "
        "Use this whenever they are dictating content, pitching, answering "
        "the editor, or thinking out loud. Pass their words as text. "
        "If the reply mentions an editor interruption, speak that objection "
        "to the user and wait for their answer or 'ignore that'."
    )
)
async def draft_add(text: str) -> str:
    try:
        payload = await _call("draft_add", {"text": text})
        # Critic often finishes just after draft_add returns; pick up the
        # objection so VoiceOS can speak it (BROWSER_TTS is muted in MCP).
        if not payload.get("pending_objection"):
            for _ in range(6):
                await asyncio.sleep(1.5)
                follow = await _call("draft_get_document")
                obj = follow.get("pending_objection")
                if obj:
                    payload["pending_objection"] = obj
                    break
    except Exception as exc:  # noqa: BLE001
        logger.info("draft_add failed: %s", exc)
        return (
            f"Cannot reach the Draft server at {DRAFT_MCP_URL}. "
            "Start uvicorn on port 8000, keep the browser tab open, then try again."
        )
    return _speak("draft_add", payload)


@mcp.tool(
    description=(
        "Finish the draft. Call once when the user confirms they are done "
        "(wrap it up, finalize, that's it). This runs an irreversible polish rewrite."
    )
)
async def draft_wrap_up() -> str:
    return await _forward("draft_wrap_up")


@mcp.tool(description="Read back only the most recent paragraph of the draft, out loud.")
async def draft_read_back() -> str:
    return await _forward("draft_read_back")


@mcp.tool(
    description=(
        "Dismiss the Critic's most recent objection when the user says "
        "ignore that, skip that, never mind, or dismiss."
    )
)
async def draft_ignore_objection() -> str:
    return await _forward("draft_ignore_objection")


@mcp.tool(description="Start a brand new document, clearing the current transcript and objections.")
async def draft_new_document() -> str:
    return await _forward("draft_new_document")


@mcp.tool(description="Get the full document — title and every paragraph — when they ask what is written.")
async def draft_get_document() -> str:
    return await _forward("draft_get_document")


@mcp.tool(description="Export the current document as Markdown text.")
async def draft_export() -> str:
    return await _forward("draft_export")


@mcp.tool(description="Create a shareable live-audience URL for the current document.")
async def draft_share() -> str:
    return await _forward("draft_share")


@mcp.tool(
    description=(
        "List the user's stored drafts with index numbers when they ask what "
        "drafts they have or want to continue an earlier one. Read the list "
        "back so they can pick by number or name."
    )
)
async def draft_list() -> str:
    return await _forward("draft_list")


@mcp.tool(
    description=(
        "Open a stored draft to continue editing it. Pass query exactly as "
        "the user referred to it: the number from draft_list, words from the "
        "title, or the slug. After this, draft_add continues that document."
    )
)
async def draft_open(query: str) -> str:
    return await _forward("draft_open", {"query": query})


if __name__ == "__main__":
    mcp.run(transport="stdio")
