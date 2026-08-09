import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createWsClient } from './ws.js'
import { createFloorMachine, FloorState } from './floor.js'
import { createAudioEngine } from './audio.js'
import { makeRehearsalToneUrl } from './devSim.js'
import { parseFinalMarkdown } from './finalMarkdown.js'
import CaptureField from './components/CaptureField.jsx'
import Document from './components/Document.jsx'
import Orb from './components/Orb.jsx'
import InterruptBanner from './components/InterruptBanner.jsx'
import ShareOverlay from './components/ShareOverlay.jsx'
import DevPanel from './components/DevPanel.jsx'

const DEFAULT_CONFIG = {
  CONF_FLOOR: 0.75,
  COOLDOWN_S: 45,
  GRACE_MS: 2500,
  PAUSE_MS: 700,
  MIN_UTTERANCES_BETWEEN: 2,
  has_openai_key: null,
  // §14.A: server default is 1 (truthy); null here just means "not yet
  // heard from the server" — DevPanel treats null/undefined as truthy too.
  BROWSER_TTS: null,
}

// Banner stays up while the objection is spoken so the user can read it
// and reply. It clears on answered/dismissed (server objection_update).
const EVENT_LOG_MAX = 20 // §13.E: rolling last-20 event log
const DEV_PANEL_WIDTH = 360

// Mirrors server/router.py's normalization + dispatch rules (SPEC.md §5),
// client-side, for LOCAL bookkeeping only: the objection answered/dismissed
// transition (§13.B: "server and client both apply this rule
// independently") and the DevPanel event log's "command routed" entries.
// The server remains the sole routing authority — every utterance is sent
// to it verbatim regardless of what this classifier decides.
function classifyUtterance(text) {
  const norm = text
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .trim()
    .replace(/\s+/g, ' ')
  const first = norm.split(' ')[0]
  if (first !== 'draft' && first !== 'draught') return { kind: 'content' }
  if (norm.includes('wrap')) return { kind: 'command', action: 'finish' }
  if (norm.includes('read') && (norm.includes('back') || norm.includes('that'))) {
    return { kind: 'command', action: 'readback' }
  }
  if (norm.includes('ignore') || norm.includes('dismiss')) return { kind: 'command', action: 'dismiss' }
  if (norm.includes('export')) return { kind: 'command', action: 'export' }
  if (norm.includes('new') || norm.includes('start over')) return { kind: 'command', action: 'reset' }
  return { kind: 'content' } // unrecognized after "draft" -> fail open, per §5
}

function buildDraftMarkdown({ finalDoc, title, blocks }) {
  if (finalDoc) return finalDoc
  const body = blocks.map((b) => b.text).join('\n\n')
  return `# ${title || 'Untitled'}\n\n${body}`
}

function downloadTextFile(filename, content) {
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function ConnDot({ status }) {
  const color = status === 'connected' ? '#7fae7a' : status === 'connecting' ? 'var(--amber)' : 'var(--danger)'
  return (
    <div
      className="pointer-events-none fixed left-4 top-4 z-30 sm:left-6 sm:top-6"
      title={`connection: ${status}`}
    >
      <span
        style={{ width: '7px', height: '7px', borderRadius: '9999px', background: color, display: 'inline-block' }}
      />
    </div>
  )
}

function FinalView({ markdown, onDownload }) {
  const { title, paragraphs } = useMemo(() => parseFinalMarkdown(markdown), [markdown])
  return (
    <div className="fade-in mx-auto w-full max-w-3xl px-6 pb-40 pt-24 sm:pt-28">
      <div className="mb-8 flex items-center justify-between">
        <span
          style={{
            fontFamily: 'var(--font-sans)',
            fontSize: '0.68rem',
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            color: 'var(--amber)',
          }}
        >
          Final draft
        </span>
        <button
          type="button"
          onClick={onDownload}
          style={{
            fontFamily: 'var(--font-sans)',
            fontSize: '0.75rem',
            color: 'var(--ink)',
            background: 'var(--paper-raised)',
            border: '1px solid var(--paper-line)',
            borderRadius: '6px',
            padding: '0.4rem 0.75rem',
          }}
        >
          Download draft.md
        </button>
      </div>
      <h1
        style={{
          fontFamily: 'var(--font-serif)',
          fontSize: 'clamp(1.9rem, 3.2vw, 2.6rem)',
          fontWeight: 400,
          color: 'var(--ink)',
          lineHeight: 1.2,
          marginBottom: '1.5rem',
        }}
      >
        {title || 'Untitled'}
      </h1>
      <div className="flex flex-col gap-6">
        {paragraphs.map((p, i) => (
          <p
            key={i}
            style={{ fontFamily: 'var(--font-serif)', fontSize: '1.2rem', lineHeight: 1.75, color: 'var(--ink)', margin: 0 }}
          >
            {p}
          </p>
        ))}
      </div>
    </div>
  )
}

export default function App() {
  const isDev = useMemo(() => new URLSearchParams(window.location.search).get('dev') === '1', [])
  // ?observe=1: read-only second tab — must NEVER wipe the live session.
  const isObserver = useMemo(() => new URLSearchParams(window.location.search).get('observe') === '1', [])

  const captureFieldRef = useRef(null)
  const wsRef = useRef(null)
  // Fresh page load = fresh session (sent once per load, not on reconnects,
  // so a wifi blip mid-demo can never wipe the document).
  const freshSessionSentRef = useRef(false)
  const floorRef = useRef(null)
  const audioRef = useRef(null)

  const configRef = useRef({ ...DEFAULT_CONFIG })
  const [config, setConfigState] = useState(configRef.current)

  const duckEnabledRef = useRef(true)
  const duckThresholdRef = useRef(0.06)
  const [duckEnabled, setDuckEnabledState] = useState(true)
  const [duckThreshold, setDuckThresholdState] = useState(0.06)

  const [connStatus, setConnStatus] = useState('connecting')
  const [doc, setDoc] = useState({ title: '', blocks: [] })
  const [updateSeq, setUpdateSeq] = useState(0)
  const [objections, setObjections] = useState([])
  const [bannerObjectionId, setBannerObjectionId] = useState(null)
  const [writerStatus, setWriterStatus] = useState('idle')
  const [speaking, setSpeaking] = useState(false)
  const [objectionSpeaking, setObjectionSpeaking] = useState(false)
  const [floorState, setFloorState] = useState(FloorState.USER_FLOOR)
  const [finalDoc, setFinalDoc] = useState(null)
  const [events, setEvents] = useState([])
  const [micStatus, setMicStatus] = useState({ available: null, detail: null })
  const [resetSignal, setResetSignal] = useState(0)
  const [shareUrl, setShareUrl] = useState(null)
  const [shareDismissSignal, setShareDismissSignal] = useState(0)

  const logEvent = useCallback((kind, detail = '') => {
    setEvents((prev) => {
      const next = [...prev, { ts: Date.now(), kind, detail: String(detail) }]
      return next.length > EVENT_LOG_MAX ? next.slice(next.length - EVENT_LOG_MAX) : next
    })
  }, [])

  const resolveActiveObjections = useCallback((status) => {
    setObjections((prev) => prev.map((o) => (o.status === 'spoken' ? { ...o, status } : o)))
    setBannerObjectionId(null)
  }, [])

  // Every outgoing utterance (real chunker output, or a barge-in forward)
  // funnels through here: send to server, then apply local-only lifecycle
  // bookkeeping (§13.B) and event logging.
  const dispatchUtteranceText = useCallback(
    (text) => {
      const cls = classifyUtterance(text)
      const sent = wsRef.current?.send({ type: 'utterance', text, ts: Date.now() / 1000 })
      logEvent('utterance_sent', text)
      if (!sent) logEvent('ws_offline', `not delivered: "${text}"`)
      // §14.B: ShareOverlay dismisses on the next dispatched utterance. This
      // is the single funnel point for all outgoing utterances (real
      // chunker output AND barge-in forwards), so bumping the signal here
      // covers both dismiss triggers named in the spec ("click or next
      // utterance_sent event").
      setShareDismissSignal((n) => n + 1)

      if (cls.kind === 'command') {
        logEvent('command_routed', `${cls.action}: "${text}"`)
        if (cls.action === 'dismiss') resolveActiveObjections('dismissed')
        // finish/readback/export/reset are server-driven; the resulting
        // protocol messages (final_doc/readback/reset) drive real state.
      } else {
        resolveActiveObjections('answered')
      }
    },
    [logEvent, resolveActiveObjections],
  )

  const handleServerMessage = useCallback(
    (msg) => {
      if (!msg || typeof msg !== 'object' || typeof msg.type !== 'string') {
        logEvent('ws_ignored', 'malformed message')
        return
      }

      switch (msg.type) {
        case 'hello': {
          const cfg = msg.config || {}
          const merged = {
            CONF_FLOOR: cfg.CONF_FLOOR ?? configRef.current.CONF_FLOOR,
            COOLDOWN_S: cfg.COOLDOWN_S ?? configRef.current.COOLDOWN_S,
            GRACE_MS: cfg.GRACE_MS ?? configRef.current.GRACE_MS,
            PAUSE_MS: cfg.PAUSE_MS ?? configRef.current.PAUSE_MS,
            MIN_UTTERANCES_BETWEEN: cfg.MIN_UTTERANCES_BETWEEN ?? configRef.current.MIN_UTTERANCES_BETWEEN,
            has_openai_key: cfg.has_openai_key ?? configRef.current.has_openai_key,
            // §14.A: server-owned, default 1. Kept in the whitelist so a
            // second observer tab (and a page reload) reflect the real
            // server value instead of always showing DevPanel's fallback.
            BROWSER_TTS: cfg.BROWSER_TTS ?? configRef.current.BROWSER_TTS,
          }
          configRef.current = merged
          setConfigState(merged)
          logEvent('hello', `config synced (PAUSE_MS=${merged.PAUSE_MS} GRACE_MS=${merged.GRACE_MS})`)
          break
        }

        case 'doc_update': {
          const blocks = Array.isArray(msg.blocks) ? msg.blocks : []
          setDoc({ title: msg.title || '', blocks })
          setUpdateSeq((n) => n + 1)
          break
        }

        case 'interrupt': {
          const objection = {
            id: msg.id,
            kind: msg.kind,
            message: msg.message,
            refs: Array.isArray(msg.refs) ? msg.refs : [],
            status: 'spoken',
            audioUrl: msg.audio_url || null,
            ts: Date.now(),
          }
          setObjections((prev) => [...prev.filter((o) => o.id !== objection.id), objection])
          setBannerObjectionId(objection.id)
          logEvent('interrupt_received', `${objection.kind} (${objection.id}): ${objection.message}`)

          if (msg.audio_url) {
            audioRef.current
              ?.play(msg.audio_url, () => {
                floorRef.current?.armSpeaking(objection.message, { isObjection: true })
                setObjectionSpeaking(true)
              })
              .then(() => {
                setObjectionSpeaking(false)
                floorRef.current?.audioEnded(configRef.current.GRACE_MS)
              })
          }
          // No audio → banner + glow only, floor stays USER_FLOOR (§13.D).
          break
        }

        case 'status': {
          const w = msg.writer === 'thinking' ? 'thinking' : 'idle'
          setWriterStatus(w)
          logEvent('status', `writer: ${w}`)
          break
        }

        case 'objection_update': {
          // §13.A.3: server-authoritative lifecycle transition. This is the
          // only path that clears glow for a VOICE dismiss ("draft, ignore
          // that"), which is routed server-side; the local classifier's
          // optimistic clear covers only what this client itself sent.
          setObjections((prev) => prev.map((o) => (o.id === msg.id ? { ...o, status: msg.status } : o)))
          setBannerObjectionId((cur) => (cur === msg.id ? null : cur))
          logEvent('objection_update', `${msg.id} -> ${msg.status}`)
          break
        }

        case 'readback': {
          logEvent('readback_received', msg.text || '')
          if (msg.audio_url) {
            audioRef.current
              ?.play(msg.audio_url, () => {
                floorRef.current?.armSpeaking(msg.text || '', { isObjection: false })
              })
              .then(() => {
                floorRef.current?.audioEnded(configRef.current.GRACE_MS)
              })
          }
          break
        }

        case 'final_doc': {
          setFinalDoc(msg.markdown || '')
          logEvent('final_doc', 'received')
          break
        }

        case 'share': {
          // §14.B: "draft, share this" / control:share / MCP draft_share all
          // land here. Store the URL to show ShareOverlay; it dismisses
          // itself on click or on the next dispatched utterance (see
          // dispatchUtteranceText's shareDismissSignal bump).
          const url = typeof msg.url === 'string' ? msg.url : ''
          setShareUrl(url || null)
          logEvent('share', url)
          break
        }

        case 'reset': {
          setDoc({ title: '', blocks: [] })
          setUpdateSeq(0)
          setObjections([])
          setBannerObjectionId(null)
          setFinalDoc(null)
          setObjectionSpeaking(false)
          audioRef.current?.stopImmediately()
          floorRef.current?.reset()
          setResetSignal((n) => n + 1)
          // A reset rotates the server-side slug (§14.B), so any share link
          // currently on screen would point at a now-closed session.
          setShareUrl(null)
          logEvent('reset', 'session cleared')
          break
        }

        default:
          logEvent('ws_ignored', `unknown type: ${msg.type}`)
      }
    },
    [logEvent],
  )

  // ---- one-time singleton wiring: floor machine, audio engine, ws client
  useEffect(() => {
    floorRef.current = createFloorMachine({
      onSend: (text) => dispatchUtteranceText(text),
      onBargeIn: (text) => {
        audioRef.current?.stopImmediately()
        wsRef.current?.send({ type: 'control', action: 'barged_in' })
        logEvent('barge_in', text)
      },
      onEchoDropped: (text) => logEvent('echo_dropped', text),
      onHold: (text) => logEvent('held_during_critic', text),
      onStateChange: (s) => setFloorState(s),
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const engine = createAudioEngine({
      onSpeakingChange: (s) => setSpeaking(s),
      getDuckEnabled: () => duckEnabledRef.current,
      getDuckThreshold: () => duckThresholdRef.current,
      onMicStatusChange: (available, detail) => {
        setMicStatus({ available, detail: detail || null })
        logEvent('mic', available ? 'permission granted' : `unavailable: ${detail || 'denied'}`)
      },
      onDuckChange: (ducked) => logEvent('duck', ducked ? 'engaged (mic energy)' : 'restored'),
      onLog: (kind, detail) => logEvent(kind, detail),
    })
    audioRef.current = engine
    engine.initMic()
    return () => engine.dispose()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const client = createWsClient({
      onMessage: handleServerMessage,
      onStatusChange: (s) => {
        setConnStatus(s)
        logEvent('connection', s)
      },
      onOpen: () => {
        wsRef.current?.send({ type: 'control', action: 'start_session' })
        if (!freshSessionSentRef.current && !isObserver) {
          freshSessionSentRef.current = true
          wsRef.current?.send({ type: 'control', action: 'fresh_session' })
        }
      },
    })
    wsRef.current = client
    return () => client.close()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ---- focus guard: CaptureField always holds focus, except DevPanel ----
  useEffect(() => {
    function isInsideDevPanel(el) {
      return !!(el && el.closest && el.closest('[data-devpanel-root]'))
    }
    function refocus() {
      const active = document.activeElement
      if (isInsideDevPanel(active)) return
      const field = captureFieldRef.current
      if (field && active !== field) field.focus({ preventScroll: true })
    }
    function scheduleRefocus() {
      // Let the click/keydown's own default focus change land first.
      setTimeout(refocus, 0)
    }
    window.addEventListener('click', scheduleRefocus, true)
    window.addEventListener('keydown', scheduleRefocus, true)
    window.addEventListener('focusin', scheduleRefocus, true)
    captureFieldRef.current?.focus()
    return () => {
      window.removeEventListener('click', scheduleRefocus, true)
      window.removeEventListener('keydown', scheduleRefocus, true)
      window.removeEventListener('focusin', scheduleRefocus, true)
    }
  }, [])

  const glowingBlockIds = useMemo(() => {
    const set = new Set()
    for (const o of objections) {
      if (o.status === 'spoken') {
        for (const ref of o.refs) set.add(ref)
      }
    }
    return set
  }, [objections])

  const bannerObjection = useMemo(
    () => objections.find((o) => o.id === bannerObjectionId) || null,
    [objections, bannerObjectionId],
  )

  function handleIgnoreBanner() {
    const activeId = bannerObjectionId
    if (activeId != null) {
      wsRef.current?.send({ type: 'control', action: 'dismiss_objection', objection_id: activeId })
    }
    resolveActiveObjections('dismissed')
    logEvent('command_routed', 'dismiss (banner button)')
  }

  function handleHearAgain() {
    const url = bannerObjection?.audioUrl
    const script = bannerObjection?.message || ''
    if (!url) return
    audioRef.current
      ?.play(url, () => {
        floorRef.current?.armSpeaking(script, { isObjection: true })
        setObjectionSpeaking(true)
      })
      .then(() => {
        setObjectionSpeaking(false)
        floorRef.current?.audioEnded(configRef.current.GRACE_MS)
      })
    logEvent('hear_again', bannerObjection?.id || '')
  }

  function handleBargeInNow() {
    floorRef.current?.feed(
      "Ignore previous direction, switching topics: let's talk about weekend hiking trails instead.",
      { bargeIn: true },
    )
  }

  function handleEchoNow() {
    const script = floorRef.current?.getScript()
    if (!script) {
      logEvent('echo_dropped', '(no active script to echo)')
      return
    }
    floorRef.current?.feed(script)
  }

  function handleFakeObjection() {
    // Client-only rehearsal lever: drives the REAL server-message path with
    // a locally built doc + interrupt + generated audio, so banner/glow/orb
    // and the audio->floor-arm->echo/barge-in chain (§9 Phases 3-4) are
    // testable with no OpenAI key and no server TTS. Never touches server
    // state; the next real doc_update simply overwrites the fake blocks.
    if (doc.blocks.length === 0) {
      handleServerMessage({
        type: 'doc_update',
        title: 'Rehearsal: our product pitch',
        blocks: [
          { id: 'b1', text: 'Users absolutely hate configuring things — nobody wants settings.', status: 'new' },
          { id: 'b2', text: 'The core flow works with zero setup, straight out of the box.', status: 'new' },
        ],
      })
    }
    handleServerMessage({
      type: 'interrupt',
      id: `fake-${Date.now()}`,
      kind: 'contradiction',
      message: "Earlier you said users hate configuring things — now everything's customizable. Which is it?",
      refs: ['b1', 'b2'],
      audio_url: makeRehearsalToneUrl(4),
    })
    logEvent('fake_objection', 'client-only rehearsal interrupt injected')
  }

  function handleSetServerConfig(key, value) {
    configRef.current = { ...configRef.current, [key]: value }
    setConfigState(configRef.current)
    wsRef.current?.send({ type: 'control', action: 'set_config', key, value })
    logEvent('set_config', `${key}=${value}`)
  }

  function handleSetDuckEnabled(v) {
    duckEnabledRef.current = v
    setDuckEnabledState(v)
  }

  function handleSetDuckThreshold(v) {
    duckThresholdRef.current = v
    setDuckThresholdState(v)
  }

  async function handleReplayStart() {
    try {
      const res = await fetch('/replay/start', { method: 'POST' })
      logEvent('replay', res.ok ? 'started' : `start failed (HTTP ${res.status})`)
    } catch (err) {
      logEvent('replay', `start error: ${err.message}`)
    }
  }

  async function handleReplayStop() {
    try {
      const res = await fetch('/replay/stop', { method: 'POST' })
      logEvent('replay', res.ok ? 'stopped' : `stop failed (HTTP ${res.status})`)
    } catch (err) {
      logEvent('replay', `stop error: ${err.message}`)
    }
  }

  function handleDownload() {
    const content = buildDraftMarkdown({ finalDoc, title: doc.title, blocks: doc.blocks })
    downloadTextFile('draft.md', content)
    logEvent('export', 'draft.md downloaded')
  }

  return (
    <div className="relative min-h-screen">
      <div style={{ marginLeft: isDev ? DEV_PANEL_WIDTH : 0, transition: 'margin-left 0.2s ease' }}>
        {finalDoc != null ? (
          <FinalView markdown={finalDoc} onDownload={handleDownload} />
        ) : (
          <Document title={doc.title} blocks={doc.blocks} updateSeq={updateSeq} glowingBlockIds={glowingBlockIds} />
        )}
      </div>

      <Orb writerStatus={writerStatus} speaking={speaking} objectionSpeaking={objectionSpeaking} />
      <InterruptBanner
        objection={bannerObjection}
        refBlocks={(bannerObjection?.refs || [])
          .map((id) => doc.blocks.find((b) => b.id === id))
          .filter(Boolean)}
        onIgnore={handleIgnoreBanner}
        onHearAgain={handleHearAgain}
        canHearAgain={Boolean(bannerObjection?.audioUrl)}
        leftInset={isDev ? DEV_PANEL_WIDTH : 0}
      />
      <ConnDot status={connStatus} />

      <CaptureField
        textareaRef={captureFieldRef}
        getPauseMs={() => configRef.current.PAUSE_MS}
        onUtterance={(text) => floorRef.current?.feed(text)}
        leftInset={isDev ? DEV_PANEL_WIDTH : 0}
        resetSignal={resetSignal}
        placeholder={
          bannerObjection ? 'Answer out loud — or say Draft, ignore that' : 'listening… VoiceOS types here'
        }
      />

      {isDev && (
        <DevPanel
          connStatus={connStatus}
          floorState={floorState}
          config={config}
          onSetConfig={handleSetServerConfig}
          duckEnabled={duckEnabled}
          duckThreshold={duckThreshold}
          onSetDuckEnabled={handleSetDuckEnabled}
          onSetDuckThreshold={handleSetDuckThreshold}
          micStatus={micStatus}
          textareaRef={captureFieldRef}
          onBargeInNow={handleBargeInNow}
          onEchoNow={handleEchoNow}
          onFakeObjection={handleFakeObjection}
          onReplayStart={handleReplayStart}
          onReplayStop={handleReplayStop}
          onDownload={handleDownload}
          events={events}
        />
      )}

      <ShareOverlay
        url={shareUrl}
        dismissSignal={shareDismissSignal}
        onDismiss={() => setShareUrl(null)}
      />
    </div>
  )
}
