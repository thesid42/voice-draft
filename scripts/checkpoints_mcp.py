"""Checkpoint runner for Draft's MCP surface (SPEC.md §14.A/§14.B). Run
against a live server on :8000 (mirrors scripts/checkpoints.py's style and
PASS/FAIL/exit-code contract; kept standalone/self-contained on purpose --
no imports from the rest of this repo).

Usage:  .venv\\Scripts\\python.exe scripts\\checkpoints_mcp.py

Drives the 8 MCP tools over the SDK's streamable-HTTP client (mcp==2.0.0:
mcp.client.streamable_http.streamable_http_client + mcp.client.session.
ClientSession -- there is no pre-2.0 streamablehttp_client in this package)
while a plain websockets client observes the /ws broadcast side, the same
way a second observer tab would -- asserting hello carries slug + BROWSER_TTS
and that share/reset broadcasts arrive alongside the matching tool calls.
"""
import asyncio, json, sys, time

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

WS_URL = "ws://127.0.0.1:8000/ws"
MCP_URL = "http://127.0.0.1:8000/mcp"
RESULTS = []

EXPECTED_TOOLS = {
    "draft_add", "draft_wrap_up", "draft_read_back", "draft_ignore_objection",
    "draft_new_document", "draft_get_document", "draft_export", "draft_share",
    "draft_list", "draft_open",
}


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok)))
    print(("PASS  " if ok else "FAIL  ") + name + ((" — " + str(detail)[:300]) if detail and not ok else ""))


class WSObserver:
    """Trimmed cousin of scripts/checkpoints.py's Client -- observes
    broadcasts only. All input in this script goes through MCP tool calls,
    not WS utterances, so `say`/`send` aren't needed here."""

    def __init__(self):
        self.msgs = []
        self.ws = None

    async def __aenter__(self):
        import websockets
        self.ws = await websockets.connect(WS_URL, open_timeout=10)
        self._task = asyncio.create_task(self._pump())
        return self

    async def __aexit__(self, *a):
        self._task.cancel()
        await self.ws.close()

    async def _pump(self):
        try:
            async for raw in self.ws:
                m = json.loads(raw)
                m["_t"] = time.time()
                self.msgs.append(m)
        except Exception:
            pass

    async def wait_for(self, typ, timeout=15, pred=None, since=0):
        deadline = time.time() + timeout
        seen = since
        while time.time() < deadline:
            while seen < len(self.msgs):
                m = self.msgs[seen]; seen += 1
                if m["type"] == typ and (pred is None or pred(m)):
                    return m
            await asyncio.sleep(0.1)
        return None


def tool_result(result) -> dict:
    """CallToolResult -> plain dict payload.

    Verified empirically against this exact installed SDK build (a throwaway
    smoke test, not this script): MCPServer.tool() with a plain `-> dict`
    return annotation does NOT populate structured_content (it stays None);
    the payload comes back as pretty-printed JSON text in content[0].text.
    structured_content is still checked first in case that changes.
    """
    sc = getattr(result, "structured_content", None)
    if sc is not None:
        return sc
    for c in getattr(result, "content", []) or []:
        text = getattr(c, "text", None)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                continue
    return {}


async def main():
    async with WSObserver() as ws:
        hello1 = await ws.wait_for("hello", 10)
        check("ws: hello on connect", hello1 is not None)
        cfg1 = (hello1 or {}).get("config", {})
        check("ws: hello carries slug", bool(cfg1.get("slug")), cfg1)
        check("ws: hello carries BROWSER_TTS", "BROWSER_TTS" in cfg1, cfg1)
        slug1 = cfg1.get("slug")
        hello_seen = len(ws.msgs)

        async with streamable_http_client(MCP_URL) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                check("mcp: initialize ok", init is not None and init.server_info is not None)

                tools = await session.list_tools()
                names = {t.name for t in tools.tools}
                check("mcp: exactly 10 tools", len(tools.tools) == 10, names)
                check("mcp: tool names match expected set", names == EXPECTED_TOOLS, names)

                # -- stored-drafts tools degrade cleanly without CONVEX_URL --
                dl = tool_result(await session.call_tool("draft_list", {}))
                check(
                    "mcp: draft_list keyless/convexless shape",
                    isinstance(dl, dict) and "drafts" in dl and (dl.get("ok") is True or dl.get("configured") is False),
                    dl,
                )
                do = tool_result(await session.call_tool("draft_open", {"query": "nonexistent draft"}))
                check(
                    "mcp: draft_open tolerates no-match/no-convex",
                    isinstance(do, dict) and do.get("ok") is not True,
                    do,
                )

                # -- draft_add x2 (planted-contradiction script lines 1-2, SPEC.md §8) --
                r1 = tool_result(await session.call_tool("draft_add", {
                    "text": "So the thing about our product is that users absolutely hate configuring things. Nobody wants settings.",
                }))
                check("mcp: draft_add #1 ok", r1.get("ok") is True, r1)
                has_key = bool(r1.get("has_openai_key"))
                print(f"-- server has_openai_key={has_key}")

                hello2 = await ws.wait_for(
                    "hello", 10,
                    lambda m: m.get("config", {}).get("BROWSER_TTS") == 0,
                    since=hello_seen,
                )
                check("ws: first mcp tool call flips BROWSER_TTS to 0 + re-broadcasts hello", hello2 is not None)

                r2 = tool_result(await session.call_tool("draft_add", {
                    "text": "The core flow has to work with zero setup, out of the box.",
                }))
                check("mcp: draft_add #2 ok", r2.get("ok") is True, r2)

                # -- draft_get_document --
                doc = tool_result(await session.call_tool("draft_get_document", {}))
                check(
                    "mcp: get_document has title/blocks/objections/slug/has_openai_key shape",
                    all(k in doc for k in ("title", "blocks", "objections", "slug", "has_openai_key")),
                    doc,
                )
                check("mcp: get_document.objections == []", doc.get("objections") == [], doc.get("objections"))
                if not has_key:
                    check("mcp: get_document.blocks empty without OPENAI key", doc.get("blocks") == [], doc.get("blocks"))
                check("mcp: get_document.slug matches hello slug", doc.get("slug") == slug1, (doc.get("slug"), slug1))

                # -- draft_share --
                n = len(ws.msgs)
                share = tool_result(await session.call_tool("draft_share", {}))
                check(
                    "mcp: draft_share ok + url contains slug",
                    share.get("ok") is True and bool(slug1) and slug1 in (share.get("url") or ""),
                    share,
                )
                share_bc = await ws.wait_for("share", 10, since=n)
                check(
                    "ws: share broadcast arrives and matches tool result url",
                    share_bc is not None and share_bc.get("url") == share.get("url"),
                    share_bc,
                )

                # -- draft_export --
                exp = tool_result(await session.call_tool("draft_export", {}))
                check(
                    "mcp: draft_export returns markdown string",
                    isinstance(exp.get("markdown"), str) and exp["markdown"].strip().startswith("#"),
                    exp,
                )

                # -- draft_new_document --
                n = len(ws.msgs)
                newdoc = tool_result(await session.call_tool("draft_new_document", {}))
                check(
                    "mcp: draft_new_document ok + mints a new slug",
                    newdoc.get("ok") is True and bool(newdoc.get("slug")) and newdoc.get("slug") != slug1,
                    newdoc,
                )
                reset_bc = await ws.wait_for("reset", 10, since=n)
                check("ws: reset broadcast arrives", reset_bc is not None)

    print("\n== %d/%d checks passed ==" % (sum(1 for _, ok in RESULTS if ok), len(RESULTS)))
    sys.exit(0 if all(ok for _, ok in RESULTS) else 1)


asyncio.run(main())
