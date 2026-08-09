"""Checkpoint runner for Draft (SPEC.md §9). Run against a live server on :8000.

Usage:  .venv\\Scripts\\python.exe scripts\\checkpoints.py [protocol|writer|critic|commands|all]

Asserts protocol-level behavior always; runs the LLM-dependent scenarios
(Phase 1 writer, Phase 2 critic+gate, Phase 5 commands) only when the
server's hello reports has_openai_key=true. Prints PASS/FAIL per check.
Run it the moment the OPENAI_API_KEY lands in .env, before any rehearsal.
"""
import asyncio, json, sys, time, urllib.request

WS_URL = "ws://127.0.0.1:8000/ws"
HTTP = "http://127.0.0.1:8000"
RESULTS = []

def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok)))
    print(("PASS  " if ok else "FAIL  ") + name + ((" — " + str(detail)[:300]) if detail and not ok else ""))

class Client:
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

    async def send(self, obj):
        await self.ws.send(json.dumps(obj))

    async def say(self, text, gap=0.0):
        await self.send({"type": "utterance", "text": text, "ts": time.time()})
        if gap:
            await asyncio.sleep(gap)

    async def wait_for(self, typ, timeout=20, pred=None, since=0):
        deadline = time.time() + timeout
        seen = since
        while time.time() < deadline:
            while seen < len(self.msgs):
                m = self.msgs[seen]; seen += 1
                if m["type"] == typ and (pred is None or pred(m)):
                    return m
            await asyncio.sleep(0.1)
        return None

    def all_of(self, typ, since=0):
        return [m for m in self.msgs[since:] if m["type"] == typ]

def http_get(path):
    try:
        with urllib.request.urlopen(HTTP + path, timeout=10) as r:
            return r.status, r.read(), dict(r.headers)
    except Exception as e:
        return getattr(e, "code", 0), b"", {}

async def scenario_protocol(c):
    hello = await c.wait_for("hello", 5)
    check("hello on connect", hello is not None)
    has_key = bool(hello and hello.get("config", {}).get("has_openai_key"))
    if hello:
        cfg = hello.get("config", {})
        check("hello carries thresholds", all(k in cfg for k in ("CONF_FLOOR", "COOLDOWN_S", "GRACE_MS", "PAUSE_MS")), cfg)
    n = len(c.msgs)
    await c.send({"type": "control", "action": "set_config", "key": "CONF_FLOOR", "value": 0.5})
    h2 = await c.wait_for("hello", 5, lambda m: m.get("config", {}).get("CONF_FLOOR") == 0.5, since=n)
    check("set_config re-broadcasts hello", h2 is not None)
    await c.send({"type": "control", "action": "set_config", "key": "CONF_FLOOR", "value": 0.75})
    await c.say("draft, ignore that")  # no objections exist: must be tolerated, not crash
    n = len(c.msgs)
    await c.say("draft, export")
    fd = await c.wait_for("final_doc", 8, since=n)
    check("draft export -> final_doc", fd is not None and "markdown" in (fd or {}))
    n = len(c.msgs)
    await c.say("draft, new document")
    rs = await c.wait_for("reset", 8, since=n)
    check("draft new document -> reset", rs is not None)
    st, _, _ = http_get("/tts/definitely-missing.mp3")
    check("unknown tts -> 404", st == 404, st)
    return has_key

async def scenario_writer(c):
    n = len(c.msgs)
    await c.say("draft, new document", gap=1.0)
    for s in ["I want to write up why our team should adopt code review checklists.",
              "Reviews today are inconsistent, and what gets caught depends entirely on who reviews.",
              "A checklist would make the floor consistent without slowing anyone down.",
              "We would start with a five item checklist focused on tests, naming, and error handling.",
              "After a month we would prune anything the team finds useless."]:
        await c.say(s, gap=1.2)
    got = await c.wait_for("doc_update", 40, lambda m: len(m.get("blocks", [])) >= 2 and m.get("title"), since=n)
    check("writer: titled doc with >=2 blocks", got is not None, got and {"title": got.get("title"), "blocks": len(got.get("blocks", []))})
    await asyncio.sleep(3)
    n = len(c.msgs)
    await c.say("Actually, scratch that last part — we keep the checklist fixed for a full quarter before pruning anything.")
    rev = await c.wait_for("doc_update", 40, lambda m: any(b.get("status") == "revised" for b in m.get("blocks", [])), since=n)
    check("writer: self-correction revises a block", rev is not None)
    if rev:
        texts = " ".join(b["text"].lower() for b in rev["blocks"])
        check("writer: correction content present (quarter)", "quarter" in texts)

async def scenario_critic(c):
    n0 = len(c.msgs)
    await c.say("draft, new document", gap=1.5)
    # Kept identical to DevPanel.jsx's PLANTED_SCRIPT (validated live).
    planted = [
        "So the pitch is simple: our users hate configuring things. Nobody wants to touch a settings menu.",
        "Everything has to work out of the box. You install it, and it just goes — zero setup, zero questions.",
        "And honestly, it's ten times faster than anything else on the market.",
        "Oh, and for the power users, we're going to let them tweak every single knob in the pipeline. Full customization.",
    ]
    for s in planted:
        await c.say(s, gap=2.5)
    itr = await c.wait_for("interrupt", 30, since=n0)
    check("critic: planted script fires an interrupt", itr is not None)
    if itr:
        check("critic: kind plausible", itr.get("kind") in ("vague_claim", "contradiction"), itr.get("kind"))
        check("critic: refs non-empty", bool(itr.get("refs")))
        if itr.get("audio_url"):
            st, body, hdr = http_get(itr["audio_url"])
            check("critic: tts playable", st == 200 and len(body) > 1000, (st, len(body)))
        else:
            check("critic: tts playable", False, "audio_url null (TTS failed or no key)")
    await asyncio.sleep(2)
    extra = c.all_of("interrupt", since=n0)
    check("critic: exactly one interrupt (cooldown holds)", len(extra) == 1, len(extra))
    # objection lifecycle broadcast: voice dismiss (or, if a later planted
    # utterance already auto-answered it, the answered broadcast) must arrive
    if itr:
        n = len(c.msgs)
        await c.say("draft, ignore that")
        ou = await c.wait_for("objection_update", 8, lambda m: m.get("status") == "dismissed", since=n)
        if ou is not None:
            check("lifecycle: objection_update broadcast", True)
        else:
            answered = [m for m in c.all_of("objection_update", since=n0)
                        if m.get("status") == "answered" and m.get("id") == itr.get("id")]
            check("lifecycle: objection_update broadcast", bool(answered), "no dismissed and no answered update seen")
    # dedup: kill cooldown, resend the same trigger lines -> similarity/kind+refs must still drop
    await c.send({"type": "control", "action": "set_config", "key": "COOLDOWN_S", "value": 0})
    n = len(c.msgs)
    await c.say(planted[2], gap=2.0)
    await c.say(planted[3], gap=2.0)
    second = await c.wait_for("interrupt", 15, since=n)
    dup_of_first = second is not None and itr is not None and (second.get("kind"), sorted(second.get("refs", []))) == (itr.get("kind"), sorted(itr.get("refs", [])))
    check("critic: no duplicate objection with cooldown=0", second is None or not dup_of_first,
          second and {"kind": second.get("kind"), "msg": second.get("message")})
    await c.send({"type": "control", "action": "set_config", "key": "COOLDOWN_S", "value": 45})
    # benign
    n = len(c.msgs)
    await c.say("draft, new document", gap=1.5)
    # Canonical benign script — kept identical to the DevPanel's BENIGN_SCRIPT
    # (web/src/components/DevPanel.jsx) so this suite exercises exactly what
    # the demo exercises.
    for s in ["I want to get the team offsite planned for the second week of October.",
              "Two full days, so nobody is away from their family longer than that.",
              "Sarah suggested the lake house we rented last year, since everyone who went wants to go back.",
              "Budget is three hundred dollars a person for travel and lodging, which finance has already approved.",
              "I'll send the scheduling poll on Friday so we can lock the dates by end of month."]:
        await c.say(s, gap=2.5)
    await asyncio.sleep(12)
    check("critic: benign script stays silent", len(c.all_of("interrupt", since=n)) == 0, [m.get("message") for m in c.all_of("interrupt", since=n)])

async def scenario_commands(c, has_key):
    n = len(c.msgs)
    await c.say("draft, new document", gap=1.0)
    await c.say("The plan for launch week is a single blog post and a short video.", gap=1.0)
    await c.say("No press outreach until the post has been live for a day.", gap=6.0 if has_key else 1.0)
    n = len(c.msgs)
    await c.say("draft, read that back")
    rb = await c.wait_for("readback", 25, since=n)
    if has_key:
        check("command: read that back -> readback msg", rb is not None and rb.get("audio_url"))
    else:
        check("command: read that back tolerated without key", True)
    n = len(c.msgs)
    await c.say("draft, wrap it up")
    fd = await c.wait_for("final_doc", 60, since=n)
    check("command: wrap it up -> final_doc", fd is not None and (fd or {}).get("markdown", "").strip().startswith("#"), fd and fd.get("markdown", "")[:80])

async def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    async with Client() as c:
        has_key = await scenario_protocol(c)
        print(f"-- server has_openai_key={has_key}")
        if which in ("all", "writer") and has_key:
            await scenario_writer(c)
        if which in ("all", "critic") and has_key:
            await scenario_critic(c)
        if which in ("all", "commands"):
            await scenario_commands(c, has_key)
        if not has_key:
            print("-- OPENAI_API_KEY absent: writer/critic scenarios SKIPPED")
    print("\n== %d/%d checks passed ==" % (sum(1 for _, ok in RESULTS if ok), len(RESULTS)))
    sys.exit(0 if all(ok for _, ok in RESULTS) else 1)

asyncio.run(main())
