# Draft — you talk, it writes, and it argues back

Voice-first writing tool. An AI **Writer** turns thinking-out-loud into a live document; an AI **Critic** interrupts out loud (own TTS) on contradictions, naked claims, undefined terms, or lost threads. Voice input comes from **VoiceOS** (desktop dictation that types into the focused field) — no SDK integration; it just types into our capture field.

Full spec + binding decisions: [SPEC.md](SPEC.md).

## Run

```powershell
# one-time
copy .env.example .env          # then put your OPENAI_API_KEY in .env
C:\Python314\python.exe -m venv .venv
.venv\Scripts\python.exe -m pip install -r server\requirements.txt
cd web; npm install; cd ..

# terminal 1 — server (from repo root)
.venv\Scripts\python.exe -m uvicorn server.main:app --reload --port 8000

# terminal 2 — frontend
cd web; npm run dev             # http://localhost:5173  (?dev=1 for the DevPanel)
```

Without `OPENAI_API_KEY` the app still boots: routing, chunking, floor machine, replay plumbing all work; Writer/Critic/TTS calls log one line and skip.

## Testing without VoiceOS

Open `http://localhost:5173/?dev=1`:

- **Sim VoiceOS**: type text, hit Speak — it commits into the capture field in dictation-like bursts through the real chunker.
- **Planted script**: expects exactly ONE interrupt (vague_claim on "ten times faster"); the contradiction fires later, after answers + cooldown.
- **Benign script**: expects ZERO interrupts.
- **Fake objection (client-only)**: injects a rehearsal doc + interrupt + locally generated audio through the real message path — banner, glow, orb, and the audio→floor-arm→echo/barge-in chain are all exercisable with **no OpenAI key and no TTS**.
- **Echo now** during/just after Critic audio: must be silently dropped. **Barge-in now**: must kill audio ≤150ms and land in the doc.
- **Replay**: runs `demo/replay_script.json` (~1.5 min golden path incl. both objections and "Draft, wrap it up") through the real pipeline. **Replay mode IS the fallback demo.**
- Sim note: the mandated 300–900ms burst gaps can exceed `PAUSE_MS` 700 and split sentences into multiple utterances — harmless (the transcript accumulates), but raise `PAUSE_MS` to ~1000 on the slider if you want one-utterance-per-sentence sim runs.

## Checkpoint runner

With the server running:

```powershell
.venv\Scripts\python.exe scripts\checkpoints.py all
```

Without a key it verifies the protocol layer (hello/set_config/export/reset/404s). **With a key it also runs the SPEC §9 Phase 1/2/5 checks** — writer coherence + self-correction revise, planted script → exactly one interrupt (kind/refs/audio), benign script → silence, dedup with cooldown zeroed, objection lifecycle broadcast, readback, wrap-up polish. Run it the moment your key lands in `.env`.

## Voice commands (say "Draft, …")

wrap it up · read that back · ignore that · export · share this · new document

**Refresh = new take.** Reloading the main tab starts a fresh session (the old transcript is dropped server-side too). WS reconnects after a network blip never reset, a running replay is never clobbered, and a second read-only tab should use `?observe=1` so it joins without wiping anything (it receives the current document on connect).

## Connect VoiceOS as an MCP client (agent mode)

Draft is also an MCP server: the same pipeline is exposed at `http://localhost:8000/mcp` (streamable HTTP, 8 tools: `draft_add`, `draft_wrap_up`, `draft_read_back`, `draft_ignore_objection`, `draft_new_document`, `draft_get_document`, `draft_export`, `draft_share`). With the Draft server running:

```
voiceos add mcp http://localhost:8000/mcp
```

Then speak naturally in VoiceOS agent mode — "add to my draft: …", "read my draft back", "wrap up my draft". Tool results carry the Critic's objections (`objection` / `pending_objection`) so VoiceOS can voice them; the on-stage browser view updates live from the same in-process state. On the first MCP call the server auto-mutes browser TTS (`BROWSER_TTS` → 0, DevPanel-toggleable) so our Critic audio can't loop back through VoiceOS's mic. If VoiceOS's `add mcp` only accepts a local command (not a URL), a ~60-line stdio proxy over `POST /rpc` + `GET /state` is the demo-day fallback — see SPEC §14.

## Convex live share (audience view)

"Draft, share this" (or the `draft_share` MCP tool) shows a QR code — the audience follows the document and objections **live on their phones** via Convex reactive queries.

One-time setup (your account):

```bash
npx convex login
```

```bash
npx convex dev --once
```

That creates the deployment and prints its URL — put it in `.env` as `CONVEX_URL=` (server mirror) and in the repo secret `VITE_CONVEX_URL` (audience page build). The audience page deploys to GitHub Pages via `.github/workflows/deploy-watch.yml` on push; then set `AUDIENCE_BASE_URL=https://thesid42.github.io/voice-draft/watch.html#` in `.env`. Without `CONVEX_URL` everything still runs — the mirror is a silent no-op.

## Tuning (live sliders in DevPanel; defaults in `.env` / `server/config.py`)

| Knob | Default | Demo-day note |
|---|---|---|
| `PAUSE_MS` | 700 | Raise if VoiceOS commits in slow bursts (utterances splitting mid-thought) |
| `CONF_FLOOR` | 0.75 | Raise if Critic is trigger-happy; tune this before touching prompts |
| `COOLDOWN_S` | 45 | Drop to ~20 for a tighter two-interrupt demo |
| `GRACE_MS` | 2500 | Raise if echo of our TTS lands late and leaks into the doc |
| Duck threshold | — | Room-dependent; disable ducking if mic is hot |

## Demo-day checklist

1. `OPENAI_API_KEY` set in `.env`; server log shows no "key missing" lines.
2. VoiceOS installed, signed in, mic selected, and it types into a test field (Notepad) correctly.
3. Browser mic permission **granted** (needed for volume-duck; app works without it, barge-in just ~1s slower).
4. Full replay run end-to-end clean (`?dev=1` → Replay start) — do this FIRST; it's the fallback if anything fails live.
5. One live run with the planted script spoken aloud; tune `PAUSE_MS` to VoiceOS's real commit rhythm.
6. Speaker volume: loud enough for the room, low enough that ducking + echo matcher cope. Headphones for rehearsal only — the demo needs the room to hear the Critic.
7. Close the DevPanel (`?dev=1` off) for the actual demo. Zoom the browser so the doc is readable from the back.
8. Kill notifications / focus assist on the demo machine (a toast stealing focus breaks VoiceOS targeting).
9. MCP mode: `voiceos add mcp http://localhost:8000/mcp` accepted and a test "add to my draft" lands in the doc; confirm `BROWSER_TTS` auto-muted (DevPanel) so VoiceOS doesn't hear our Critic.
10. Convex: `CONVEX_URL` in `.env`, phone loads the Pages watch URL, "Draft, share this" QR scans from the back row.

## Repo

```
server/   FastAPI: /ws, writer, critic, gate, TTS cache, replay engine
web/      Vite + React + Tailwind: capture field, chunker, floor machine, doc, orb, DevPanel
demo/     replay_script.json (golden-path demo)
```
