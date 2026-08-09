"""FastAPI app: /ws, /tts/{id}.mp3, /replay/start, /replay/stop, static serve.

Run from repo root: uvicorn server.main:app --port 8000
(absolute imports throughout; server/__init__.py makes this a package.)
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from server import config, critic, replay, router, tts, writer
from server.session import SessionState, reset_state, render_markdown

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("draft.main")

REPO_ROOT = Path(__file__).resolve().parent.parent

app = FastAPI()

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
    return {"type": "hello", "config": config.get_config_for_hello()}


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
    elif result.kind == "reset":
        await _handle_reset()


async def _handle_content(text: str, ts) -> None:
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

    state.utterances_since_interrupt += 1

    writer.submit_utterance(state, utterance, broadcast)
    await critic.handle_content_utterance(state, utterance, broadcast)


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


async def _handle_dismiss(objection_id: str | None = None) -> None:
    if objection_id:
        for obj in state.objections:
            if obj.id == objection_id:
                obj.status = "dismissed"
                logger.info("dismiss objection id=%s", objection_id)
                await broadcast({"type": "objection_update", "id": obj.id, "status": "dismissed"})
                return
        logger.info("dismiss failed: unknown objection id=%r", objection_id)
        return
    for obj in reversed(state.objections):
        if obj.status == "spoken":
            obj.status = "dismissed"
            logger.info("dismiss latest spoken objection id=%s", obj.id)
            await broadcast({"type": "objection_update", "id": obj.id, "status": "dismissed"})
            return
    logger.info("dismiss ignored: no spoken objection")


async def _handle_readback() -> None:
    if not state.block_order:
        logger.info("readback skipped: no blocks yet")
        return
    last_id = state.block_order[-1]
    text = state.blocks[last_id]
    readback_id = state.next_readback_id()
    audio_url = await tts.synthesize(readback_id, text)
    logger.info("readback id=%s block=%s audio=%s", readback_id, last_id, bool(audio_url))
    await broadcast({"type": "readback", "audio_url": audio_url, "text": text})


async def _handle_export() -> None:
    markdown = render_markdown(state)
    logger.info("export markdown_len=%d", len(markdown))
    await broadcast({"type": "final_doc", "markdown": markdown})


async def _handle_finish() -> None:
    logger.info("finish: starting polish pass")
    markdown = await writer.run_polish(state)
    logger.info("finish: final_doc markdown_len=%d", len(markdown))
    await broadcast({"type": "final_doc", "markdown": markdown})


async def _handle_reset() -> None:
    reset_state(state)
    logger.info("reset: session cleared")
    await broadcast({"type": "reset"})


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


# --- Static frontend / root hint -----------------------------------------
# Must be registered LAST: a Mount("/") prefix-matches every path, so any
# route added after it would never be reached. Registering it last means
# /ws, /tts/*, /replay/* above are always matched first.

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
