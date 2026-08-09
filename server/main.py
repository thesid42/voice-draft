"""FastAPI app: /ws, /tts/{id}.mp3, /replay/start, /replay/stop, /state, /rpc,
static serve, and the MCP tool surface mounted at /mcp.

Run from repo root: uvicorn server.main:app --port 8000
(absolute imports throughout; server/__init__.py makes this a package.)

Construction order (SPEC.md §14.A) matters here: MCPServer.session_manager
raises RuntimeError until streamable_http_app() has been called, and our
lifespan (which enters session_manager.run()) has to exist before the
FastAPI app itself is constructed with it. So: state + every handler
function are defined first (the MCP deps need real callables to close
over), then the MCP server + its Starlette app, then the FastAPI app +
lifespan, then routes, then the MCP app is mounted -- all BEFORE the static
catch-all, which must stay last since Mount("/") prefix-matches everything.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sys
import time
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.routing import Route

from server import config, critic, mirror, replay, router, tts, writer
from server.mcp_server import MCPDeps, build_mcp_server
from server.session import (
    Objection,
    SessionState,
    get_last_block_text,
    objection_to_dict,
    render_markdown,
    reset_state,
    snapshot as session_snapshot,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("draft.main")

REPO_ROOT = Path(__file__).resolve().parent.parent

state = SessionState()
connections: set[WebSocket] = set()


# --- broadcast ---------------------------------------------------------

async def broadcast(message: dict) -> None:
    """Send `message` to every connected WS client (a second observer tab
    must work, per SPEC.md §13.E)."""
    if not connections:
        return
    payload = json.dumps(message)
    dead: list[WebSocket] = []
    for ws in list(connections):
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        connections.discard(ws)


def _hello_message() -> dict:
    cfg = config.get_config_for_hello()
    cfg["slug"] = state.slug
    return {"type": "hello", "config": cfg}


# --- shared message handling (live WS and replay both funnel through here) --

async def handle_client_message(data: dict) -> None:
    msg_type = data.get("type")
    if msg_type == "utterance":
        await _handle_utterance(data)
    elif msg_type == "control":
        await _handle_control(data)
    else:
        logger.info("unknown message type=%r ignored", msg_type)


async def _handle_utterance(data: dict) -> None:
    text = data.get("text")
    text = text.strip() if isinstance(text, str) else ""
    if not text:
        logger.info("utterance ignored: empty text")
        return
    ts = data.get("ts", time.time())
    logger.info("utterance in text=%r ts=%s", text, ts)

    result = router.route(text)
    logger.info("router decision=%s", result.kind)

    if result.kind == "content":
        await _handle_content(text, ts)
    elif result.kind == "finish":
        await _handle_finish()
    elif result.kind == "readback":
        await _handle_readback()
    elif result.kind == "dismiss":
        await _handle_dismiss()
    elif result.kind == "export":
        await _handle_export()
    elif result.kind == "share":
        await _handle_share()
    elif result.kind == "reset":
        await _handle_reset()


async def _handle_content(
    text: str,
    ts,
    on_result: Optional[critic.OnResult] = None,
) -> None:
    """Append `text` to the transcript and kick off the writer + critic.

    `on_result`, when given, is threaded straight through to the critic
    (SPEC.md §14.A) -- this is the ONLY content-handling path; the MCP
    draft_add tool calls this exact function (via _mcp_handle_add below)
    rather than re-implementing any of it.
    """
    utterance = {"text": text, "ts": ts}
    state.transcript.append(utterance)

    # Objection lifecycle (§13.B): spoken -> answered on the next content
    # utterance. Server is authoritative; the objection_update broadcast
    # keeps every client (incl. observer tabs) in sync.
    for obj in state.objections:
        if obj.status == "spoken":
            obj.status = "answered"
            logger.info("objection answered id=%s", obj.id)
            await broadcast({"type": "objection_update", "id": obj.id, "status": "answered"})
            mirror.upsert_objection(state.slug, objection_to_dict(obj))

    state.utterances_since_interrupt += 1

    writer.submit_utterance(state, utterance, broadcast)
    await critic.handle_content_utterance(state, utterance, broadcast, on_result=on_result)


async def _handle_control(data: dict) -> None:
    action = data.get("action")
    if action == "start_session":
        logger.info("control action=start_session")
    elif action == "barged_in":
        # Log-only on the server; the forwarded utterance that follows does
        # the actual state work (§13.B).
        logger.info("control action=barged_in")
    elif action == "dismiss_objection":
        await _handle_dismiss(data.get("objection_id"))
    elif action == "finish":
        await _handle_finish()
    elif action == "share":
        logger.info("control action=share")
        await _handle_share()
    elif action == "set_config":
        key = data.get("key")
        value = data.get("value")
        ok = config.set_config(key, value)
        if ok:
            logger.info("set_config key=%s value=%s", key, value)
            await broadcast(_hello_message())
        else:
            logger.info("set_config ignored: unknown key=%r", key)
    else:
        logger.info("unknown control action=%r ignored", action)


async def _handle_dismiss(objection_id: Optional[str] = None) -> Optional[str]:
    """Dismiss `objection_id`, or (if None) the latest spoken objection.

    Returns the dismissed objection's id, or None if nothing matched --
    lets the MCP draft_ignore_objection tool report success/failure without
    re-deriving "which objection did that dismiss".
    """
    if objection_id:
        for obj in state.objections:
            if obj.id == objection_id:
                obj.status = "dismissed"
                logger.info("dismiss objection id=%s", objection_id)
                await broadcast({"type": "objection_update", "id": obj.id, "status": "dismissed"})
                mirror.upsert_objection(state.slug, objection_to_dict(obj))
                return obj.id
        logger.info("dismiss failed: unknown objection id=%r", objection_id)
        return None
    for obj in reversed(state.objections):
        if obj.status == "spoken":
            obj.status = "dismissed"
            logger.info("dismiss latest spoken objection id=%s", obj.id)
            await broadcast({"type": "objection_update", "id": obj.id, "status": "dismissed"})
            mirror.upsert_objection(state.slug, objection_to_dict(obj))
            return obj.id
    logger.info("dismiss ignored: no spoken objection")
    return None


async def _handle_readback() -> Optional[str]:
    text = get_last_block_text(state)
    if text is None:
        logger.info("readback skipped: no blocks yet")
        return None
    readback_id = state.next_readback_id()
    audio_url = None
    if config.runtime_config["BROWSER_TTS"]:
        audio_url = await tts.synthesize(readback_id, text)
    else:
        logger.info("readback id=%s audio skipped: BROWSER_TTS=0", readback_id)
    logger.info("readback id=%s audio=%s", readback_id, bool(audio_url))
    await broadcast({"type": "readback", "audio_url": audio_url, "text": text})
    return text


async def _handle_export() -> str:
    markdown = render_markdown(state)
    logger.info("export markdown_len=%d", len(markdown))
    await broadcast({"type": "final_doc", "markdown": markdown})
    return markdown


async def _handle_finish() -> str:
    logger.info("finish: starting polish pass")
    markdown = await writer.run_polish(state)
    logger.info("finish: final_doc markdown_len=%d", len(markdown))
    await broadcast({"type": "final_doc", "markdown": markdown})
    mirror.finish(state.slug, markdown)
    return markdown


async def _handle_share() -> str:
    url = f"{config.AUDIENCE_BASE_URL}{state.slug}"
    logger.info("share url=%s", url)
    await broadcast({"type": "share", "url": url})
    return url


async def _handle_reset() -> str:
    old_slug = state.slug
    reset_state(state)
    logger.info("reset: session cleared old_slug=%s new_slug=%s", old_slug, state.slug)
    await broadcast({"type": "reset"})
    mirror.close_and_rotate(old_slug)
    mirror.ensure(state.slug)
    return state.slug


# --- MCP (SPEC.md §14.A) --------------------------------------------------
# draft_add's own pipeline entry: router-defensive (content path only, even
# if the text would parse as a command -- the sibling tools ARE the command
# surface), then the exact same _handle_content() the WS path uses, waiting
# up to MCP_OBJECTION_WAIT_S for this utterance's own critic verdict via the
# on_result hook. Never a second critic call path.

async def _mcp_handle_add(text: str) -> Optional[Objection]:
    text = (text or "").strip()
    if not text:
        logger.info("mcp draft_add: ignored empty text")
        return None

    result = router.route(text)
    if result.kind != "content":
        logger.info(
            "mcp draft_add: router classified %r as %s, forcing content path anyway",
            text,
            result.kind,
        )

    ts = time.time()
    event = asyncio.Event()
    box: list[Optional[Objection]] = [None]

    async def on_result(obj: Optional[Objection]) -> None:
        box[0] = obj
        event.set()

    await _handle_content(text, ts, on_result=on_result)
    try:
        await asyncio.wait_for(event.wait(), timeout=config.MCP_OBJECTION_WAIT_S)
    except asyncio.TimeoutError:
        logger.info(
            "mcp draft_add: objection wait timed out after %.1fs (may still arrive as pending_objection later)",
            config.MCP_OBJECTION_WAIT_S,
        )
    return box[0]


mcp_deps = MCPDeps(
    state=state,
    broadcast=broadcast,
    hello_message=_hello_message,
    handle_add=_mcp_handle_add,
    handle_finish=_handle_finish,
    handle_readback=_handle_readback,
    handle_dismiss=_handle_dismiss,
    handle_reset=_handle_reset,
    handle_export=_handle_export,
    handle_share=_handle_share,
    snapshot=lambda: session_snapshot(state),
)
mcp = build_mcp_server(mcp_deps)

# streamable_http_path="/" (not the default "/mcp") because this whole
# Starlette app is mounted AT "/mcp" below -- otherwise routes would land on
# /mcp/mcp. json_response + stateless_http keep this a plain request/response
# endpoint (no SSE session stream) since VoiceOS is a simple HTTP MCP client.
# Default host="127.0.0.1" is fine -- localhost only, same as VoiceOS itself.
mcp_app = mcp.streamable_http_app(streamable_http_path="/", json_response=True, stateless_http=True)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # mcp.session_manager raises RuntimeError until streamable_http_app() has
    # been called (already done above) -- this is the one place its task
    # group is allowed to start (SPEC.md §14.A).
    async with mcp.session_manager.run():
        mirror.ensure(state.slug)
        yield


app = FastAPI(lifespan=lifespan)


# --- WebSocket endpoint --------------------------------------------------

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    connections.add(websocket)
    logger.info("ws connected clients=%d", len(connections))
    try:
        # Broadcast (not unicast) so every server->client message goes to
        # all connected clients uniformly (§13.E) -- a second observer tab
        # that's already open will just harmlessly re-apply the same config.
        await broadcast(_hello_message())
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.info("ws message invalid json, ignored: %r", raw[:200])
                continue
            if not isinstance(data, dict):
                logger.info("ws message not a JSON object, ignored")
                continue
            try:
                await handle_client_message(data)
            except Exception:
                logger.exception("error handling ws message type=%r", data.get("type"))
    except WebSocketDisconnect:
        logger.info("ws disconnected")
    finally:
        connections.discard(websocket)
        logger.info("ws connections now=%d", len(connections))


# --- TTS -------------------------------------------------------------------

@app.get("/tts/{tts_id}.mp3")
async def get_tts(tts_id: str) -> Response:
    audio = tts.get(tts_id)
    if audio is None:
        return Response(status_code=404)
    return Response(content=audio, media_type="audio/mpeg")


# --- Replay ------------------------------------------------------------

@app.post("/replay/start")
async def replay_start() -> JSONResponse:
    ok, message = await replay.start(REPO_ROOT, handle_client_message)
    return JSONResponse({"ok": ok, "message": message}, status_code=200 if ok else 409)


@app.post("/replay/stop")
async def replay_stop() -> JSONResponse:
    ok, message = await replay.stop()
    return JSONResponse({"ok": ok, "message": message}, status_code=200 if ok else 409)


# --- State + RPC (SPEC.md §14.A) ------------------------------------------
# Thin REST surface backing scripted testing and a possible demo-day stdio
# proxy (not built now).

@app.get("/state")
async def get_state() -> JSONResponse:
    return JSONResponse(session_snapshot(state))


@app.post("/rpc")
async def rpc(request: Request) -> JSONResponse:
    try:
        data = await request.json()
    except Exception:
        logger.info("rpc: invalid json body")
        return JSONResponse({"ok": False, "error": "invalid json body"}, status_code=400)
    if not isinstance(data, dict):
        logger.info("rpc: body is not a JSON object")
        return JSONResponse({"ok": False, "error": "body must be a JSON object"}, status_code=400)
    await handle_client_message(data)
    return JSONResponse({"ok": True})


# --- MCP mount -------------------------------------------------------------
# Must be registered before the static catch-all (next section) for the same
# reason /ws, /tts, /replay, /state, /rpc are: Mount("/") prefix-matches
# every path once it's registered.
#
# This installed Starlette (1.6.0) compiles a Mount's match pattern as
# `path + "/{path:path}"` -- there is no optional-suffix case like older
# Starlette versions had. That means Mount("/mcp", mcp_app) only ever
# matches "/mcp/..." (at least a trailing slash); a bare "POST /mcp" (no
# trailing slash -- the natural way to write this URL, and what an MCP
# client given "http://host:8000/mcp" will send) does not match the Mount
# at all and falls through to the static catch-all below, which 405s any
# non-GET method. Confirmed with curl: POST /mcp/ -> 200, POST /mcp -> 405.
# _BareMCPPassthrough registers the exact literal path "/mcp" as an extra
# Route (Route matches its path exactly, no forced suffix) and rewrites the
# scope to "/" before handing it to the SAME mcp_app -- the same rewrite
# Mount itself does for a matching "/mcp/..." request.
class _BareMCPPassthrough:
    def __init__(self, asgi_app) -> None:
        self._asgi_app = asgi_app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] in ("http", "websocket"):
            scope = {**scope, "path": "/", "root_path": scope.get("root_path", "") + "/mcp"}
        await self._asgi_app(scope, receive, send)


app.router.routes.append(
    Route("/mcp", _BareMCPPassthrough(mcp_app), methods=["GET", "POST", "DELETE"])
)
app.mount("/mcp", mcp_app)
logger.info("mcp mounted at /mcp (streamable-http, json_response, stateless; bare + trailing-slash both handled)")


# --- Static frontend / root hint -----------------------------------------
# Must be registered LAST: a Mount("/") prefix-matches every path, so any
# route added after it would never be reached. Registering it last means
# /ws, /tts/*, /replay/*, /state, /rpc, /mcp above are always matched first.

WEB_DIST = REPO_ROOT / "web" / "dist"

if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIST), html=True), name="static")
    logger.info("serving static frontend from %s", WEB_DIST)
else:
    @app.get("/")
    async def root_hint() -> PlainTextResponse:
        return PlainTextResponse(
            "Draft server is running, but web/dist was not found.\n"
            "Run `npm run dev` in web/ for local development "
            "(it proxies /ws, /tts, /replay to this server on :8000),\n"
            "or `npm run build` in web/ to produce web/dist for this "
            "server to serve directly."
        )

    logger.info("web/dist not found at %s; serving plain-text hint at /", WEB_DIST)
