"""Convex live-share mirror (SPEC.md §14.B) -- fire-and-forget, best-effort.

Every public function here is a silent (log-only) no-op when CONVEX_URL is
unset, and never raises into its caller: the `convex` package's ConvexClient
is a synchronous/blocking client, so each call runs in a background asyncio
task via asyncio.to_thread and any error is caught and logged as one line.
The mirror must never affect the primary WS/MCP pipeline -- it only ever
watches it.

Call sites (SPEC.md §14.B): writer.py after every doc_update broadcast;
critic.py after every interrupt broadcast; main.py after objection_update
transitions, after final_doc from the finish flow (not export), and on
reset (closes the old row, then ensures the new one).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from server import config

logger = logging.getLogger("draft.mirror")

try:
    from convex import ConvexClient
except ImportError:  # pragma: no cover - convex is a hard requirement, but
    # degrade instead of crashing server boot if it's ever missing.
    ConvexClient = None  # type: ignore[assignment,misc]

_client: Optional["ConvexClient"] = None


def _get_client():
    """Lazily construct the module-level ConvexClient. Returns None (and the
    caller logs+no-ops) if CONVEX_URL is unset or the package failed to
    import."""
    global _client
    if not config.CONVEX_URL or ConvexClient is None:
        return None
    if _client is None:
        _client = ConvexClient(config.CONVEX_URL)
    return _client


def _fire(fn_name: str, args: dict, *, slug: str) -> None:
    """Kick off the Convex mutation `fn_name(args)` as a background task.

    Silent no-op (one log line, no task, no exception) without CONVEX_URL.
    """
    client = _get_client()
    if client is None:
        logger.info("mirror skipped: no CONVEX_URL fn=%s", fn_name)
        return
    asyncio.create_task(_run(client, fn_name, args, slug))


async def _run(client, fn_name: str, args: dict, slug: str) -> None:
    try:
        await asyncio.to_thread(client.mutation, fn_name, args)
        logger.info("mirror ok fn=%s slug=%s", fn_name, slug)
    except Exception as exc:  # noqa: BLE001 - must never surface to the caller
        logger.info("mirror error fn=%s slug=%s error=%s", fn_name, slug, exc)


def ensure(slug: str) -> None:
    """Get-or-create the Convex row for `slug`."""
    _fire("sessions:ensure", {"slug": slug}, slug=slug)


def update_doc(slug: str, title: str, blocks: list[dict]) -> None:
    """Mirror the current title + blocks ([{id,text}]) for `slug`."""
    _fire("sessions:updateDoc", {"slug": slug, "title": title, "blocks": blocks}, slug=slug)


def upsert_objection(slug: str, objection: dict) -> None:
    """Mirror one objection (id/kind/message/refs/status) for `slug`."""
    _fire("sessions:upsertObjection", {"slug": slug, "objection": objection}, slug=slug)


def finish(slug: str, markdown: str) -> None:
    """Mark `slug` finished with its final polished markdown."""
    _fire("sessions:finish", {"slug": slug, "markdown": markdown}, slug=slug)


def close_and_rotate(old_slug: str) -> None:
    """Close the outgoing session's Convex row on reset.

    Named for the caller's intent (main.py mints+ensures the new slug
    separately right after calling this) -- this function itself only
    closes `old_slug`.
    """
    _fire("sessions:close", {"slug": old_slug}, slug=old_slug)


# --- Reads (drafts-history UI; SPEC.md §14.B) ------------------------------
# Unlike the fire-and-forget writers above, these are awaited by the
# /drafts endpoints and RAISE on network errors (the endpoint reports a
# clean 502). Still None without CONVEX_URL.

def _query_sync(fn_name: str, args: dict):
    client = _get_client()
    if client is None:
        return None
    return client.query(fn_name, args)


async def fetch_sessions():
    """sessions:list — newest first, for the drafts sidebar."""
    return await asyncio.to_thread(_query_sync, "sessions:list", {})


async def fetch_session(slug: str):
    """sessions:getBySlug — one stored draft, full content."""
    return await asyncio.to_thread(_query_sync, "sessions:getBySlug", {"slug": slug})
