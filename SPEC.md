# DRAFT — Build Spec (authoritative, Claude Code handoff)

**One-liner:** You talk, it writes — and it argues back. A voice-first writing tool where an AI Writer turns thinking-out-loud into a document in real time, and an AI Critic interrupts (out loud) when you contradict yourself, make a naked claim, or lose the thread.

**Context:** 6-hour hackathon build, 2-person team, demoed live on stage. Voice input comes from VoiceOS (a third-party desktop dictation app that types polished text into whatever field has focus — we do NOT integrate its SDK; it just types into our web app). Judges reward: usefulness, execution, creativity, demo quality. Optimize for one golden demo path, not completeness.

**Prize alignment:** all model calls use OpenAI (chat + TTS). No other model providers.

## 1. Product behavior (the golden path)

1. User opens the app. A capture field has focus. They speak; VoiceOS types their words into the field.
2. The app cuts the incoming text into utterances and sends them to the server.
3. A Writer model continuously turns the transcript into a document (title + paragraph blocks) rendered live. Revised blocks flash. The page is never blank after ~2 utterances.
4. A Critic model evaluates after every utterance. Default: silence. When it catches a contradiction / unanchored claim / undefined term / lost thread / implausible claim, it interrupts: an orb pulses, a one-sentence objection plays as audio (our own TTS), and the referenced blocks glow.
5. The user answers by speaking — the answer is just the next utterance; the Writer weaves it in and the doc visibly improves. Or they say "Draft, ignore that."
6. Voice commands (prefix "Draft, …"): wrap it up / read that back / ignore that / export / new document. The entire app is operable with zero keyboard/mouse.
7. "Draft, wrap it up" → one final full-document polish pass → clean final view → export as Markdown.

**Critical interaction — echo protection:** the Critic's audio plays through speakers; the laptop mic + VoiceOS will transcribe it and type it back into our own field. We must detect and discard this echo (we know the objection script verbatim) while still allowing real user barge-in. See §6 Floor state machine.

## 2. Architecture

```
Browser (React/Vite)                         FastAPI server
┌──────────────────────────┐                 ┌──────────────────────────────┐
│ CaptureField (focused)   │  utterances     │ ROUTER  "draft, ..." prefix? │
│  ← VoiceOS types here    │ ──────────────▶ │  ├─ command → handlers       │
│ Chunker (pause/punct)    │   one WS        │  └─ content → SessionState   │
│ Document renderer        │ ◀────────────── │ WRITER (debounced, patches)  │
│ Orb + InterruptBanner    │  doc_update /   │ CRITIC (every utterance)     │
│ Audio player + duck      │  interrupt /    │ GATE (code, not LLM)         │
│ Floor state machine      │  status /       │ TTS (OpenAI) → /tts/{id}.mp3 │
│ Echo matcher             │  final_doc      │ Replay engine (demo)         │
│ DevPanel (?dev=1)        │                 │ Serves built frontend        │
└──────────────────────────┘                 └──────────────────────────────┘
```

- Audio never touches the server on the input side. Server sees text only.
- Single session, single user. No auth, no DB, no persistence beyond process memory (plus export download).

## 3. Repo layout

```
draft/                     # = E:\Projects\Draft (repo root)
  server/
    __init__.py
    main.py          # FastAPI app, /ws endpoint, /tts/{id}.mp3, static serve, /replay
    session.py       # SessionState dataclass + apply_patches
    router.py        # command parsing ("draft, ..." fuzzy match)
    writer.py        # debounced writer loop
    critic.py        # critic call
    gate.py          # interrupt gate (pure functions)
    tts.py           # OpenAI TTS → mp3 bytes, in-memory cache {id: bytes}
    replay.py        # feeds demo/replay_script.json through the same pipeline
    prompts.py       # WRITER_SYSTEM, CRITIC_SYSTEM, POLISH_SYSTEM
    config.py        # env + tunables (all thresholds live here)
    requirements.txt # fastapi uvicorn[standard] openai python-dotenv
  web/
    index.html
    src/
      main.jsx / App.jsx
      ws.js          # websocket client, auto-reconnect
      chunker.js     # input-event → utterance cutting
      floor.js       # floor state machine + echo matcher
      audio.js       # playback, volume-duck fast path (WebAudio mic RMS)
      components/
        CaptureField.jsx   # visually minimal, always focused (focus guard)
        Document.jsx       # title + blocks, flash on revise, glow on refs
        Orb.jsx            # idle / thinking / speaking states
        InterruptBanner.jsx# objection text + kind + [Ignore] (voice or click)
        DevPanel.jsx       # ?dev=1 only — see §8
    package.json     # react, vite, tailwind. Nothing else unless essential.
  demo/
    replay_script.json
  .env.example
  README.md          # run instructions, demo-day checklist
```

## 4. WebSocket protocol (exact)

Client → server:

```json
{"type":"utterance","text":"users hate configuring things","ts":1723.4}
{"type":"control","action":"start_session"}
{"type":"control","action":"barged_in"}
{"type":"control","action":"dismiss_objection","objection_id":"o3"}
{"type":"control","action":"finish"}
```
(`finish` is the same as "draft, wrap it up".)

Server → client:

```json
{"type":"doc_update","title":"...","blocks":[
  {"id":"b1","text":"...","status":"unchanged"},
  {"id":"b2","text":"...","status":"revised"},
  {"id":"b3","text":"...","status":"new"}]}

{"type":"interrupt","id":"o3","kind":"contradiction",
 "message":"Earlier you said users hate configuring things — now everything's customizable. Which is it?",
 "refs":["b2","b7"],"audio_url":"/tts/o3.mp3"}

{"type":"status","writer":"thinking"}
{"type":"readback","audio_url":"/tts/r1.mp3","text":"..."}
{"type":"final_doc","markdown":"# Title\n\n..."}
{"type":"reset"}
```

(`status.writer` is `"thinking"` or `"idle"`. `readback` has no gate and no orb-objection styling.)

Server always sends the full ordered block list in `doc_update` (Writer produces patches internally; server applies them to state and broadcasts the whole doc with per-block status). Frontend just re-renders; no client-side patch logic.

## 5. Server spec

### SessionState

```python
transcript: list[{text, ts}]
blocks: ordered dict {id: text}           # b1, b2, ...
title: str
objections: list[{id, kind, message, refs, status}]  # status: spoken|dismissed|answered
last_interrupt_ts: float | None
utterances_since_interrupt: int
writer_running: bool
pending_utterances: list                  # queued while writer runs
```

### Router (runs on every utterance, before anything else)

Normalize: lowercase, strip punctuation. If it starts with `draft` (allow "draught" — ASR misspells):

- contains `wrap` → finish flow
- contains `read` and (`back` or `that`) → readback (TTS the most recent block; no gate)
- contains `ignore` or `dismiss` → dismiss latest spoken objection
- contains `export` → send `{"type":"final_doc"}` with current markdown (frontend downloads)
- contains `new` or `start over` → reset session, send `{"type":"reset"}`
- unrecognized after "draft" → treat as content (fail open)

Anything not starting with `draft` → content path.

### Writer (debounced)

- Trigger: new content utterance appended. If `writer_running`, queue in `pending_utterances`; when the run finishes, if queue non-empty, run again with all queued items batched.
- Call: chat completions, `MODEL_WRITER`, JSON response format, system = `WRITER_SYSTEM` (§7), user message = full transcript + current blocks + "new since last run" utterances.
- Output: `{"patches":[{"op":"add|replace|delete","id":"b7","after":"b6","text":"..."}],"title":"..."}`. Apply to state; broadcast `doc_update` with statuses (added→new, replaced→revised).
- Guardrail in code: if the model returns >60% of blocks as `replace` in one pass, apply anyway but log a warning (thrash detector for prompt tuning).

### Critic (every content utterance, fire-and-forget task)

- Call: `MODEL_CRITIC`, JSON response format, system = `CRITIC_SYSTEM` (§7), user = transcript + blocks + objections already raised (message + kind + refs + status).
- Output: `{"action":"stay_silent"}` or `{"action":"interrupt","kind":...,"message":...,"refs":[...],"confidence":0.0-1.0}`.
- Result goes to the Gate. The Critic never emits directly.

### Gate (pure code — `gate.py`)

Drop the interrupt if ANY of:

1. `confidence < CONF_FLOOR` (default 0.75)
2. `now - last_interrupt_ts < COOLDOWN_S` (default 45)
3. `utterances_since_interrupt < 2`
4. token-overlap similarity vs any prior objection message ≥ 0.6
5. same `(kind, sorted(refs))` already exists

Else: allocate id, synthesize TTS, cache mp3, broadcast `interrupt`, update counters. All thresholds in `config.py`, overridable via env — they WILL be tuned on demo day.

### Finish flow

One full-document polish pass is allowed here (the only place): `POLISH_SYSTEM` — tighten, order, resolve answered objections, keep speaker's voice, no new claims. Broadcast `final_doc` markdown.

### TTS

OpenAI speech API, model from `TTS_MODEL` env (default `tts-1`), voice `onyx`, mp3, in-memory `{id: bytes}`, served at `/tts/{id}.mp3`. Synthesize BEFORE broadcasting the interrupt so `audio_url` is immediately playable.

### Replay engine (demo fallback — do not skip)

`POST /replay/start` reads `demo/replay_script.json`:

```json
{"events":[{"delay_ms":1200,"type":"utterance","text":"..."},
           {"delay_ms":9000,"type":"utterance","text":"..."}]}
```

Feeds events into the exact same pipeline (router → writer/critic → gate) with real timing. Indistinguishable from live input downstream. `POST /replay/stop` cancels.

## 6. Frontend spec

### Chunker (`chunker.js`)

VoiceOS commits text into the field in bursts. Listen to input events on CaptureField; close an utterance when:

- no new characters for `PAUSE_MS` (default 700, adjustable live in DevPanel), OR
- text ends with `.` `?` `!` followed by a space/idle beat.

On close: emit utterance (trimmed), clear the field. Never send empty/whitespace.

### Focus guard

CaptureField must ALWAYS hold focus (VoiceOS types wherever the cursor is). Global click/keydown handler refocuses it. Field is visually minimal — thin strip at the bottom showing in-flight text, fading once chunked.

### Floor state machine (`floor.js`) — the critical piece

```
USER_FLOOR (default)
  chunker output → send as utterance.

AGENT_SPEAKING (entered when objection audio starts)
  chunker output → quarantine → echoMatch(text, currentObjectionScript)
    match     → drop silently (our own TTS transcribed back)
    no match  → BARGE-IN: stop audio immediately, send control:barged_in,
                forward text as utterance, → USER_FLOOR.

GRACE (for GRACE_MS = 2500 after audio ends)
  matcher stays armed — VoiceOS's transcription of our audio often lands
  AFTER playback finishes. Non-matching text = normal utterance. → USER_FLOOR.
```

`echoMatch`: normalize both (lowercase, strip punct), token-set overlap ratio of incoming utterance vs objection script ≥ 0.6 → echo. Keep it dumb.

### Volume-duck fast path (`audio.js`)

While objection audio plays, monitor mic RMS via WebAudio (getUserMedia — request permission on load). Sustained energy above threshold (~200ms) → duck TTS volume to 10% instantly. Then the text verdict decides: barge-in confirms kill; echo match (or silence) restores volume. Threshold + ducking toggleable in DevPanel (rooms vary). If mic permission is denied, skip ducking gracefully — text-match barge-in still works, just ~1s slower.

### Components

- **Document.jsx** — big serif type, generous spacing, dark theme, readable from the back of a room. `status:new` fades in; `status:revised` flashes; `refs` blocks glow (amber ring) while an objection is active, clear on answer/dismiss.
- **Orb.jsx** — idle (dim pulse) / thinking (writer status) / speaking (bright pulse synced to audio).
- **InterruptBanner.jsx** — objection text + kind tag; auto-hides 10s after audio ends unless refs still glowing.
- Aesthetic target: calm, editorial, "a serious writing tool," not a dashboard. No gradients-and-glassmorphism template look.

### Export

"Draft, export" or `final_doc` → download `draft.md` client-side from current state.

## 7. Prompts (`prompts.py`) — use verbatim as the starting point

WRITER_SYSTEM

```
You are the Writer for "Draft", a voice-first writing tool. The user is thinking
out loud; you maintain a written document from their spoken transcript.

You receive the full transcript (timestamped utterances), the current document
as blocks {id, text}, and the utterances that are new since your last run.

Return ONLY JSON:
{"patches":[{"op":"add"|"replace"|"delete","id":"bN","after":"bM","text":"..."}],
 "title":"..."}

Rules:
- Write in the speaker's voice. Keep their word choices and tone; strip filler,
  false starts, and repetition.
- NEVER invent claims, facts, numbers, or examples they did not say.
- When they self-correct ("actually, scratch that", restating a point
  differently), REPLACE the relevant block; do not append a contradiction.
- When they answer an editor's objection, integrate the answer into the
  referenced blocks so the document improves.
- Prefer minimal patches. Do not touch blocks that don't need to change.
  Never rewrite the whole document.
- Blocks are paragraphs of 1–4 sentences. "after" places new blocks; omit it
  to append at the end.
- Set a short title once the topic is clear; change it only if the topic
  clearly changes.
```

CRITIC_SYSTEM

```
You are the Critic for "Draft" — a sharp, terse editor listening to someone
think out loud. You see the full transcript, the current document blocks, and
objections already raised.

Your default is SILENCE. Interrupt only for:
1. contradiction — the latest utterances directly conflict with something
   said earlier in the transcript or written in the document.
2. vague_claim — a number, superlative, or comparison with no anchor
   ("10x faster" — than what? "everyone wants this" — who?).
3. undefined_term — a load-bearing term or acronym used repeatedly and never
   explained.
4. lost_thread — the last several utterances have no clear connection to the
   stated point of the document.
5. implausible_claim — the latest utterance states something that is
   obviously false or physically impossible as a real-world fact
   ("a truck can fly", "water is dry", "the sun is ice-cold"). Challenge it
   directly. Do NOT use this for unverifiable product boasts, opinions,
   future plans, metaphors, or fiction the speaker is clearly writing as
   fiction — only for claims presented as literal fact that cannot be true.

Do NOT interrupt for: style, grammar, mild repetition, an incomplete thought
still in progress, anything covered by a past objection, or anything the
speaker seems about to address themselves.

Return ONLY JSON:
{"action":"stay_silent"}
or
{"action":"interrupt","kind":"contradiction|vague_claim|undefined_term|lost_thread|implausible_claim",
 "message":"...","refs":["b2","b7"],"confidence":0.0-1.0}

message: ONE spoken sentence, conversational and direct, quoting at most six
of the speaker's own words. It will be read aloud. No preamble, no hedging.
Good examples:
- "Earlier you said users hate configuring things — now everything's
  customizable. Which is it?"
- "Ten times faster than what?"
- "A truck can fly — do you mean that literally?"
refs: the block ids the objection concerns (two for contradictions).
confidence: how sure you are this is worth interrupting a person mid-thought.
Below 0.75, choose stay_silent.
```

POLISH_SYSTEM

```
Final pass on a voice-drafted document. Tighten and order it, resolve points
the speaker clarified after objections, keep the speaker's voice, remove
duplication. Do not add any claim not present in the transcript. Return
ONLY the final document as Markdown with a # title.
```

## 8. DevPanel (`?dev=1`) — build this EARLY, it is how everything gets tested without VoiceOS

- Sim VoiceOS textarea + "Speak" button: splits input into sentences and commits them into CaptureField in bursts (300–900ms random gaps) to mimic dictation commit patterns. Goes through the real chunker.
- Buttons: Planted-contradiction script (see below), Benign script, Undefined-term script, Lost-thread script (one rehearsal script per Critic sense — all four kinds demoable on demand), Fake objection (client-only, no key needed), Barge-in now (injects non-matching text during AGENT_SPEAKING), Echo now (injects the current objection text — must be silently dropped).
- Live sliders: `PAUSE_MS`, `CONF_FLOOR`, `COOLDOWN_S`, `GRACE_MS`, duck threshold, duck on/off, browser TTS.
- Replay controls: start/stop `demo/replay_script.json`.

Planted-contradiction script (also the base of `replay_script.json`; the four rehearsal scripts live in DevPanel.jsx and are mirrored in scripts/checkpoints.py — all live-model validated):

1. "So the pitch is simple: our users hate configuring things. Nobody wants to touch a settings menu."
2. "Everything has to work out of the box. You install it, and it just goes — zero setup, zero questions."
3. "And honestly, it's ten times faster than anything else on the market." ← expect `vague_claim`
4. "Oh, and for the power users, we're going to let them tweak every single knob in the pipeline. Full customization." ← expect `contradiction` refs to the settings block

(Only one may fire immediately due to the cooldown — that's correct behavior; the second fires after the user "answers".)

## 9. Build order — checkpoints to self-verify before moving on

- **Phase 0 — Scaffold:** repo, server boots, vite dev runs, WS connects, DevPanel utterance appears in server log. ✔ round-trip works.
- **Phase 1 — Writer, headless:** Sim-speak 5 sentences → coherent titled doc of 2–3 blocks appears; an "actually, scratch that" self-correction REVISES a block instead of appending. ✔ both behaviors demonstrated.
- **Phase 2 — Critic + Gate, text-only:** Planted script → exactly ONE interrupt fires with correct kind and refs; benign script → zero interrupts; rerunning planted script does not duplicate a prior objection. ✔ all three.
- **Phase 3 — Voice of the Critic:** TTS audio auto-plays on interrupt; orb speaks; refs blocks glow; "Barge-in now" during playback kills audio ≤150ms and the injected text lands in the doc. ✔
- **Phase 4 — Floor machine + echo protection:** "Echo now" during AGENT_SPEAKING and during GRACE → dropped, doc unchanged; barge-in still passes. Volume duck works with real mic (manual check, human does this). ✔ echo tests automated via DevPanel.
- **Phase 5 — Commands + finish:** "draft wrap it up" (typed via sim) → polished final_doc view + export downloads draft.md; "draft read that back" plays last block; "draft ignore that" clears glow and marks dismissed; "draft new document" resets. ✔ all five commands.
- **Phase 6 — Replay + stage polish:** Replay runs the full planted demo end-to-end untouched; dark theme readable at distance; orb/flash animations smooth. ✔ one clean uninterrupted replay run.

Stretch only if everything above is green: Web Speech API toggle in DevPanel as a VoiceOS-independent content-input fallback.

## 10. Out of scope — do NOT build

Auth, accounts, multi-session, DB, mobile layout, collaborative editing, undo history, streaming token-by-token doc rendering, VoiceOS SDK/MCP integration (input is plain typed text), any non-OpenAI model, tests beyond the checkpoint checks, Docker.

## 11. Config & run

`.env.example`:

```
OPENAI_API_KEY=
MODEL_WRITER=gpt-4o
MODEL_CRITIC=gpt-4o        # bump to the strongest chat model this key can access
TTS_MODEL=tts-1
TTS_VOICE=onyx
CONF_FLOOR=0.75
COOLDOWN_S=45
GRACE_MS=2500
PAUSE_MS=700
```

Run: `uvicorn server.main:app --reload --port 8000` from repo root, and `npm run dev` in `web/` (proxy `/ws`, `/tts`, `/replay` to :8000). `README.md` must include a demo-day checklist: mic permission granted, `?dev=1` closed, replay tested, volume levels.

## 12. Known risks (context for decisions, humans own these)

- VoiceOS commit granularity is unknown until demo day → that's why PAUSE_MS is a live slider and the chunker is isolated in one file.
- Echo loop severity depends on room/mic → that's why duck threshold is a slider and headphones are the dev default.
- Critic over-eagerness is a gate-tuning problem, not a prompt problem — tune thresholds first.
- If anything fails live: replay mode IS the demo. It must be flawless before any polish work.

---

## 13. Advisor addenda — binding decisions (resolve spec ambiguities; follow these)

### A. Protocol extensions (minimal, required by §8 DevPanel live-tuning)

1. On WS connect the server sends
   `{"type":"hello","config":{"CONF_FLOOR":0.75,"COOLDOWN_S":45,"GRACE_MS":2500,"PAUSE_MS":700,"MIN_UTTERANCES_BETWEEN":2,"has_openai_key":true}}`
   Client initializes DevPanel sliders from it. `GRACE_MS`/`PAUSE_MS` are enforced client-side but the server is the config source of truth so slider values survive a page reload.
2. New client→server control: `{"type":"control","action":"set_config","key":"CONF_FLOOR","value":0.8}` — server updates runtime config; unknown keys are logged and ignored. After a change the server re-broadcasts `hello` to all clients.
3. New server→client broadcast: `{"type":"objection_update","id":"o3","status":"answered"}` (status `answered` or `dismissed`) — sent whenever an objection leaves `spoken`. This is the authoritative signal for clients to clear glow/banner; without it, a voice-dismiss ("draft, ignore that", routed server-side) would never reach the browser.
4. Refresh semantics: the main tab sends `{"type":"control","action":"fresh_session"}` **once per page load** (not on WS reconnects — a wifi blip must never wipe the doc; `?observe=1` tabs never send it). Server: reset iff the session has content AND no replay is running. Complementarily, on every WS connect the server unicasts a full `doc_update` snapshot (all statuses `unchanged`) when blocks exist, so clients that don't reset see the real session instead of a deceptively blank page.

### B. Objection lifecycle

`spoken` → `answered` when the **next content utterance** arrives; `spoken` → `dismissed` via "draft, ignore that" or `control:dismiss_objection`. The server is authoritative and broadcasts `objection_update` on every transition (§13.A.3); the client may also infer `answered` locally as a fallback. Ref-block glow clears on either transition. The Critic's context lists every objection with its status. `control:barged_in` is log-only on the server (the forwarded utterance that follows does the state work).

### C. Readback echo safety

ANY app-played audio arms the floor machine: enter AGENT_SPEAKING with the played script (objection message OR readback text) as the echo-match reference, then GRACE after it ends. Readback differs only in styling (no banner, no objection orb-state, no glow). The spec's "no gate" for readback means it bypasses the interrupt Gate — not echo protection.

### D. Failure modes (demo resilience — never crash the process)

- Server must boot and serve `/ws` with NO `OPENAI_API_KEY` set: writer/critic/TTS calls log a clear one-line error and skip. All OpenAI errors (network, 4xx, timeout) are caught, logged, and swallowed.
- TTS failure → broadcast the interrupt anyway with `"audio_url": null`. Client shows banner + glow, plays nothing, floor stays USER_FLOOR (no audio → no echo risk).
- Writer JSON parse failure → retry once (append a "Return ONLY valid JSON" reminder); on second failure drop the run and log. Critic parse failure → treat as stay_silent, log.
- Unknown/malformed WS messages → log and ignore.

### E. Implementation decisions

- **Server:** absolute imports (`from server.session import ...`), `server/__init__.py` exists, run as `uvicorn server.main:app --port 8000` **from repo root**. Resolve paths from `Path(__file__).resolve().parent.parent` (= repo root): replay script at `<root>/demo/replay_script.json`, static frontend at `<root>/web/dist` mounted at `/` only if that directory exists (else `/` returns a plain-text hint to run vite dev).
- **OpenAI calls:** official `openai` Python lib, `AsyncOpenAI` client created lazily (not at import time). Writer + Critic: `chat.completions.create` with `response_format={"type":"json_object"}`; writer temperature 0.3, critic temperature 0.2. TTS: `audio.speech.create(model=TTS_MODEL, voice=TTS_VOICE, input=..., response_format="mp3")`.
- **Writer context includes objections:** the writer's user message lists all objections (id/kind/status/refs/message) — its system prompt requires integrating answers into referenced blocks, which is impossible without seeing them.
- **Gate rule 4 similarity:** Jaccard over lowercase punctuation-stripped token sets, ≥ 0.6.
- **Client echo matcher:** `overlap = |incoming ∩ script| / |incoming tokens|` ≥ 0.6 (denominator = incoming utterance, so partial echo fragments still match).
- **IDs:** blocks `b1,b2,…`; objections `o1,o2,…`; readbacks `r1,r2,…`. TTS cache key = that id; URL `/tts/{id}.mp3`, `Content-Type: audio/mpeg`.
- **doc_update statuses are per-update deltas:** a block `revised` in update N is `unchanged` in update N+1 unless touched again.
- **Counters:** `utterances_since_interrupt` +1 per content utterance, reset to 0 when an interrupt fires. `last_interrupt_ts` = server monotonic time at fire.
- **status messages:** send `{"type":"status","writer":"thinking"}` when a writer run starts and `"idle"` when the queue drains.
- **Broadcast:** keep a set of connected WS clients; every server→client message goes to all of them (a second observer tab must work).
- **Logging (stdout, one line each):** utterance in, router decision, writer run start/end (+duration ms, patch count, thrash warning), critic verdict (+confidence), gate decision (+drop reason), TTS synth (+ms). Demo-day debugging depends on these.
- **Frontend stack:** Vite + React + Tailwind v4 via `@tailwindcss/vite`. Vite dev proxy: `/ws` (with `ws: true`), `/tts`, `/replay` → `http://localhost:8000`. Vite on default port 5173.
- **No external runtime resources** (no CDN fonts/scripts/images — stage wifi is unreliable). Use a system serif stack (e.g. `Georgia, 'Iowan Old Style', 'Times New Roman', serif`) and system sans for UI chrome.
- **CaptureField** is a real `<textarea>` (thin strip at the bottom). Focus guard: window-level click/keydown/focus handlers refocus it UNLESS the newly-focused element is inside the DevPanel (DevPanel inputs must remain usable).
- **Sim VoiceOS must drive the real pipeline:** set the textarea value via the native value setter and dispatch real `input` events, in sentence bursts with 300–900ms random gaps — the chunker must not be able to tell it apart from VoiceOS.
- **DevPanel additions** (needed to verify checkpoints): current floor-state readout, connection status, and a rolling last-20 event log (utterance sent / echo dropped / barge-in / interrupt received / command routed).
- **Export:** client builds `draft.md` from the latest `final_doc` markdown (or from current title+blocks if no final_doc yet) and triggers a browser download.
- **Final view:** when `final_doc` arrives, show a clean polished view (render the markdown minimally — `#` title + paragraphs; no markdown library).
- **reset** message → client clears all state (doc, objections, banner, floor → USER_FLOOR).

### F. Reminders

No git init. No tests beyond checkpoint checks. No extra npm/pip dependencies beyond what §3 lists unless genuinely essential (justify in your report). Windows dev machine: PowerShell 5.1, Python 3.14 at `C:\Python314\python.exe`, Node 24.

---

## 14. Sponsor surfaces: MCP server (VoiceOS) + Convex live share (binding addendum)

Extends the working app on branch `mcp-convex`. Hybrid shape: everything in §§1–13 keeps working unchanged; these are additions. Two hard rules: **MCP tools funnel through the existing pipeline helpers (zero logic duplication)**, and **every new integration degrades to a silent no-op when its env key is absent** (no `OPENAI_API_KEY` → tools still succeed with writer/critic skipped; no `CONVEX_URL` → mirror is inert).

### A. MCP surface (server-owned)

**SDK facts (verified against installed `mcp==2.0.0` on this machine — do not re-derive from docs):**
- `from mcp.server import MCPServer` (FastMCP is gone). `@mcp.tool()` decorator exists.
- `mcp.streamable_http_app(streamable_http_path="/", json_response=True, stateless_http=True)` → Starlette app. Those exact kwargs exist on `streamable_http_app` (NOT the constructor); default path is `/mcp` hence the `"/"` override to avoid `/mcp/mcp`; default `host="127.0.0.1"` is fine (localhost VoiceOS).
- **`mcp.session_manager` raises RuntimeError until `streamable_http_app()` has been called** (lazy). Construction order in `main.py` is therefore: state/helpers → `mcp = build_mcp_server(...)` → `mcp_app = mcp.streamable_http_app(...)` → `lifespan` (enters `mcp.session_manager.run()`) → `app = FastAPI(lifespan=lifespan)` → routes → `app.mount("/mcp", mcp_app)` **before** the static catch-all block.
- `server/mcp_server.py` is a factory `build_mcp_server(deps) -> MCPServer` receiving state/broadcast/handler callables from main.py (no import of main at module scope — avoids the circular import).
- **Starlette 1.6 mount quirk (discovered by curl, fixed in main.py):** `Mount("/mcp", ...)` matches only `/mcp/...` (trailing slash required); a bare `POST /mcp` — what an MCP client given `http://host:8000/mcp` actually sends — fell through to the static catch-all (405). An extra exact-path `Route("/mcp", _BareMCPPassthrough(mcp_app))` rewrites the scope path to `/` and delegates to the same app; both URL forms return 200.

**Tools (8) — names, params, result shapes (as shipped):** `draft_add(text)` → `{ok}` · `draft_wrap_up()` → `{ok, markdown}` · `draft_read_back()` → `{ok, text}` · `draft_ignore_objection()` → `{ok, dismissed_id}` · `draft_new_document()` → `{ok, slug}` · `draft_get_document()` → the snapshot `{title, blocks, objections, slug, has_openai_key}` · `draft_export()` → `{ok, markdown}` · `draft_share()` → `{ok, url}`. Every result additionally carries `has_openai_key` and, when an undelivered objection exists, `pending_objection` `{id, kind, message, refs, status}` — including one fired during the current call (that is what `draft_add`'s ≤2s wait exists for; there is no separate `objection` field). Delivery watermark = the numeric objection-id suffix; only the newest undelivered objection is returned and the watermark advances past the gap.
- `draft_add` is **content-path only**: consult `router.route()` defensively; if classification ≠ `content`, log and treat as content anyway — NEVER execute a command branch from `draft_add` (the sibling tools are the command surface).
- `draft_wrap_up`'s description must say: "Call once, at the end, when the user confirms they're done — this runs an irreversible polish rewrite." `draft_read_back` description: "only the most recent paragraph"; `draft_get_document`: "the full document".
- **Objection delivery:** `draft_add` waits ≤ 2s (constant `MCP_OBJECTION_WAIT_S = 2.0` in config) for the critic verdict of ITS OWN utterance via a new optional `on_result` callback parameter on `critic.handle_content_utterance()` — invoked exactly once at the end of the existing `_run()` with the fired `Objection` or `None`. NEVER issue a second critic call. Objections that fire later (or before other tools) surface as `pending_objection` on the NEXT tool result of any kind: track `last_delivered_objection_seq` in the MCP layer; a `spoken`/`answered` objection newer than that is pending.
- **`BROWSER_TTS`** (`runtime_config`, int 1/0, default 1, plus an `explicit`-set flag): when 0, the server passes `audio_url: null` on interrupts AND readbacks (skip TTS synthesis entirely) — reusing the §13.D client path; banner/glow unaffected. On the FIRST MCP tool call, if the user never explicitly set it, flip to 0 and re-broadcast `hello` (second-echo-loop mitigation: our TTS would hit VoiceOS's own mic).
- **REST endpoints** (thin, replay-style): `GET /state` → document snapshot `{title, blocks:[{id,text}], objections:[...], slug, has_openai_key}` via a new `session.snapshot(state)` helper; `POST /rpc` → body passed to `handle_client_message()` verbatim, returns `{ok:true}`. These back scripted testing and a possible demo-day stdio proxy (which is NOT built now).
- `_handle_finish` / `_handle_export` / `_handle_readback` are refactored to **return** their payload (markdown / markdown / text) in addition to broadcasting — backward-compatible.

### B. Share flow + Convex mirror (split ownership)

- **Slug:** `SessionState.slug` — two short lowercase words + 2 digits (e.g. `amber-fox-42`), minted at state creation and on every reset (reset also closes the old Convex row). Include in `hello` config and `GET /state`.
- **Share:** router gains a `share` keyword branch ("draft, share this"); `control:share` action; MCP `draft_share`. All → broadcast `{"type":"share","url": AUDIENCE_BASE_URL-joined-with-slug}` and return the URL. `AUDIENCE_BASE_URL` env (default `http://localhost:5173/watch.html#`); URL construction = `AUDIENCE_BASE_URL + slug` (base ends with `#` — hash routing, GitHub-Pages-safe). Client shows ShareOverlay (QR + giant short URL), dismissed on click or next utterance.
- **Mirror (`server/mirror.py`):** module-level `ConvexClient` (package `convex`, installed) created lazily from `CONVEX_URL`; every public function is fire-and-forget (`asyncio.create_task(asyncio.to_thread(...))`), swallows+logs all errors, and is a no-op without the env. Functions: `ensure(slug)`, `update_doc(slug, title, blocks)`, `upsert_objection(slug, objection)`, `finish(slug, markdown)`, `close_and_rotate(old_slug)`. Call sites: writer after doc_update broadcast; critic after interrupt broadcast; main after objection_update transitions, final_doc (finish only), and reset (`close_and_rotate(old)` + `ensure(new)`); `ensure(initial slug)` also fires once in the FastAPI lifespan.
- **Convex functions (`convex/`):** `schema.ts` + `sessions.ts` **using codegen-free generic builders** — `import { queryGeneric as query, mutationGeneric as mutation } from "convex/server"` and `defineSchema/defineTable` — so nothing requires `_generated/` (which only exists after `npx convex dev`, a user-account step). Mutations: `ensure`, `updateDoc`, `upsertObjection`, `finish` (sets status+finalMarkdown), `close` (status finished). Queries: `getBySlug(slug)`, `list()`. All public; slug is the capability (accepted hackathon risk). Index `by_slug`.
- **Audience page:** second Vite entry `web/watch.html` → `src/watchMain.jsx` → `src/AudienceView.jsx`. Reads slug from `location.hash`. Uses `ConvexProvider`/`ConvexReactClient` with `import.meta.env.VITE_CONVEX_URL` and **`anyApi`** (from `convex/server`) for function refs (no codegen). States: no VITE_CONVEX_URL → "not configured"; no slug/row → "waiting for a live session"; live → title/blocks in the editorial style + objections as amber margin notes + LIVE pulse; finished → render finalMarkdown. Same no-external-resources rule.
- **Vite:** multi-entry build (`rollupOptions.input` = index.html + watch.html), `base: './'` (Pages-safe relative assets).
- **Pages workflow (`.github/workflows/deploy-watch.yml`):** on push to `mcp-convex`/`main`: npm ci, build with `VITE_CONVEX_URL` from repo secret (build proceeds with it empty), upload `web/dist`, deploy via `actions/deploy-pages` (repo Pages source: GitHub Actions).

### C. New env keys (`.env.example`)

`CONVEX_URL=` (server mirror), `AUDIENCE_BASE_URL=` (share URLs; set to `https://thesid42.github.io/voice-draft/watch.html#` once Pages is live). Frontend build-time: `VITE_CONVEX_URL`.
