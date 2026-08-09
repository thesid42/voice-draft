import { useRef, useState } from 'react'
import { speakIntoField } from '../devSim.js'

// DevPanel.jsx — SPEC.md §8 + §13.E. Only mounted behind ?dev=1.
// `data-devpanel-root` marks the subtree the focus guard (App.jsx) must
// leave alone so these inputs stay usable.

// Four rehearsal scripts — one per Critic sense (SPEC.md §8). All validated
// against the live model: the planted lines MUST fire their labeled kinds and
// the benign script MUST stay silent; keep checkpoints.py's copies in sync.
const PLANTED_SCRIPT = [
  'So the pitch is simple: our users hate configuring things. Nobody wants to touch a settings menu.',
  'Everything has to work out of the box. You install it, and it just goes — zero setup, zero questions.',
  "And honestly, it's ten times faster than anything else on the market.",
  "Oh, and for the power users, we're going to let them tweak every single knob in the pipeline. Full customization.",
].join(' ')

const BENIGN_SCRIPT = [
  'I want to get the team offsite planned for the second week of October.',
  'Two full days, so nobody is away from their family longer than that.',
  'Sarah suggested the lake house we rented last year, since everyone who went wants to go back.',
  'Budget is three hundred dollars a person for travel and lodging, which finance has already approved.',
  "I'll send the scheduling poll on Friday so we can lock the dates by end of month.",
].join(' ')

const UNDEFINED_TERM_SCRIPT = [
  'The whole roadmap this quarter hangs on shipping the HDP before the conference.',
  'Marketing wants the HDP on the landing page, and sales wants it in every deck.',
  'If the HDP slips, we push the launch. That is how central it is.',
].join(' ')

const LOST_THREAD_SCRIPT = [
  'I want to write the announcement for our seed round, and the tone has to be confident without being smug.',
  'The key line is that we raised this money to double down on developer experience.',
  'Speaking of experience, the barista this morning poured a leaf pattern into my latte in about four seconds flat.',
  'Anyway, the weather has been wild lately. Apparently it might even snow this weekend, in October.',
].join(' ')

function Row({ label, children }) {
  return (
    <div className="mb-2.5 flex items-center justify-between gap-3">
      <span style={{ fontFamily: 'var(--font-sans)', fontSize: '0.72rem', color: 'var(--ink-dim)' }}>{label}</span>
      {children}
    </div>
  )
}

function SliderRow({ label, value, min, max, step, onChange, format }) {
  return (
    <div className="mb-2.5">
      <div className="mb-1 flex items-center justify-between">
        <span style={{ fontFamily: 'var(--font-sans)', fontSize: '0.72rem', color: 'var(--ink-dim)' }}>{label}</span>
        <span style={{ fontFamily: 'var(--font-sans)', fontSize: '0.72rem', color: 'var(--ink)' }}>
          {format ? format(value) : value}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full"
      />
    </div>
  )
}

function Button({ children, onClick, disabled, tone }) {
  const bg = tone === 'danger' ? 'rgba(201,107,79,0.15)' : 'var(--paper)'
  const border = tone === 'danger' ? 'rgba(201,107,79,0.5)' : 'var(--paper-line)'
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        fontFamily: 'var(--font-sans)',
        fontSize: '0.75rem',
        color: disabled ? 'var(--ink-faint)' : 'var(--ink)',
        background: bg,
        border: `1px solid ${border}`,
        borderRadius: '6px',
        padding: '0.4rem 0.65rem',
        opacity: disabled ? 0.5 : 1,
        cursor: disabled ? 'not-allowed' : 'pointer',
      }}
    >
      {children}
    </button>
  )
}

export default function DevPanel({
  connStatus,
  floorState,
  config,
  onSetConfig,
  duckEnabled,
  duckThreshold,
  onSetDuckEnabled,
  onSetDuckThreshold,
  micStatus, // { available: true|false|null, detail }
  textareaRef,
  onBargeInNow,
  onEchoNow,
  onFakeObjection,
  onReplayStart,
  onReplayStop,
  onDownload,
  events,
}) {
  const [simText, setSimText] = useState('')
  const [simBusy, setSimBusy] = useState(false)
  const stopFlagRef = useRef(false)
  const floorStateRef = useRef(floorState)
  floorStateRef.current = floorState

  const floorIdle = floorState === 'USER_FLOOR'

  async function runScript(text) {
    const el = textareaRef.current
    if (!el || simBusy || !text.trim()) return
    stopFlagRef.current = false
    setSimBusy(true)
    try {
      await speakIntoField(el, text.trim(), {
        shouldStop: () => stopFlagRef.current,
        // Don't type the next demo line over Critic TTS — that used to
        // barge-in and cut the objection off mid-sentence.
        shouldPause: () => floorStateRef.current === 'AGENT_SPEAKING',
      })
    } finally {
      setSimBusy(false)
    }
  }

  function stopSim() {
    stopFlagRef.current = true
    setSimBusy(false)
  }

  return (
    <div
      data-devpanel-root="true"
      className="thin-scroll fixed inset-y-0 left-0 z-40 flex w-[360px] flex-col overflow-y-auto"
      style={{
        background: 'var(--paper-raised)',
        borderRight: '1px solid var(--paper-line)',
        padding: '1rem 1.1rem 2rem',
      }}
    >
      <h2 style={{ fontFamily: 'var(--font-sans)', fontSize: '0.85rem', color: 'var(--ink)', margin: '0 0 0.9rem' }}>
        DevPanel <span style={{ color: 'var(--ink-faint)', fontWeight: 400 }}>?dev=1</span>
      </h2>

      {/* --- status ------------------------------------------------- */}
      <section className="mb-4">
        <Row label="connection">
          <span
            style={{
              fontFamily: 'var(--font-sans)',
              fontSize: '0.72rem',
              color:
                connStatus === 'connected' ? '#8fbf8a' : connStatus === 'connecting' ? 'var(--amber)' : 'var(--danger)',
            }}
          >
            {connStatus}
          </span>
        </Row>
        <Row label="floor state">
          <span style={{ fontFamily: 'var(--font-sans)', fontSize: '0.72rem', color: 'var(--ink)' }}>{floorState}</span>
        </Row>
        <Row label="openai key">
          <span style={{ fontFamily: 'var(--font-sans)', fontSize: '0.72rem', color: 'var(--ink)' }}>
            {config.has_openai_key === null ? 'unknown' : config.has_openai_key ? 'present' : 'MISSING'}
          </span>
        </Row>
        <Row label="mic">
          <span style={{ fontFamily: 'var(--font-sans)', fontSize: '0.72rem', color: 'var(--ink)' }}>
            {micStatus.available === null ? 'requesting…' : micStatus.available ? 'ok' : 'denied'}
          </span>
        </Row>
        {micStatus.available === false && (
          <p style={{ fontFamily: 'var(--font-sans)', fontSize: '0.68rem', color: 'var(--ink-faint)', margin: '0.2rem 0 0' }}>
            Ducking disabled ({micStatus.detail || 'permission denied'}) — text-match barge-in still works, ~1s slower.
          </p>
        )}
      </section>

      {/* --- config sliders ------------------------------------------ */}
      <section className="mb-4 border-t pt-3" style={{ borderColor: 'var(--paper-line)' }}>
        <SliderRow
          label="PAUSE_MS"
          value={config.PAUSE_MS}
          min={200}
          max={2000}
          step={50}
          onChange={(v) => onSetConfig('PAUSE_MS', v)}
        />
        <SliderRow
          label="GRACE_MS"
          value={config.GRACE_MS}
          min={500}
          max={6000}
          step={100}
          onChange={(v) => onSetConfig('GRACE_MS', v)}
        />
        <SliderRow
          label="CONF_FLOOR"
          value={config.CONF_FLOOR}
          min={0}
          max={1}
          step={0.01}
          format={(v) => v.toFixed(2)}
          onChange={(v) => onSetConfig('CONF_FLOOR', v)}
        />
        <SliderRow
          label="COOLDOWN_S"
          value={config.COOLDOWN_S}
          min={0}
          max={120}
          step={1}
          onChange={(v) => onSetConfig('COOLDOWN_S', v)}
        />
        <Row label="min utterances between (server)">
          <span style={{ fontFamily: 'var(--font-sans)', fontSize: '0.72rem', color: 'var(--ink)' }}>
            {config.MIN_UTTERANCES_BETWEEN}
          </span>
        </Row>
        <Row label="browser TTS (server)">
          <input
            type="checkbox"
            checked={config.BROWSER_TTS === undefined || config.BROWSER_TTS === null ? true : !!config.BROWSER_TTS}
            onChange={(e) => onSetConfig('BROWSER_TTS', e.target.checked ? 1 : 0)}
          />
        </Row>
      </section>

      {/* --- ducking --------------------------------------------------- */}
      <section className="mb-4 border-t pt-3" style={{ borderColor: 'var(--paper-line)' }}>
        <Row label="duck on/off (client-local)">
          <input type="checkbox" checked={duckEnabled} onChange={(e) => onSetDuckEnabled(e.target.checked)} />
        </Row>
        <SliderRow
          label="duck threshold (RMS)"
          value={duckThreshold}
          min={0.01}
          max={0.3}
          step={0.01}
          format={(v) => v.toFixed(2)}
          onChange={onSetDuckThreshold}
        />
      </section>

      {/* --- sim voiceOS ------------------------------------------------ */}
      <section className="mb-4 border-t pt-3" style={{ borderColor: 'var(--paper-line)' }}>
        <p style={{ fontFamily: 'var(--font-sans)', fontSize: '0.72rem', color: 'var(--ink-dim)', margin: '0 0 0.4rem' }}>
          Sim VoiceOS
        </p>
        <textarea
          value={simText}
          onChange={(e) => setSimText(e.target.value)}
          rows={3}
          placeholder="Type something to dictate…"
          className="thin-scroll w-full"
          style={{
            fontFamily: 'var(--font-sans)',
            fontSize: '0.78rem',
            color: 'var(--ink)',
            background: 'var(--paper)',
            border: '1px solid var(--paper-line)',
            borderRadius: '6px',
            padding: '0.4rem 0.5rem',
            resize: 'vertical',
          }}
        />
        <div className="mt-2 flex flex-wrap gap-2">
          <Button onClick={() => runScript(simText)} disabled={simBusy || !simText.trim()}>
            {simBusy ? 'Speaking…' : 'Speak'}
          </Button>
          <Button onClick={stopSim} disabled={!simBusy} tone="danger">
            Stop
          </Button>
        </div>
        <div className="mt-2 flex flex-wrap gap-2">
          <Button
            onClick={() => {
              setSimText(PLANTED_SCRIPT)
              runScript(PLANTED_SCRIPT)
            }}
            disabled={simBusy}
          >
            Planted-contradiction script
          </Button>
          <Button
            onClick={() => {
              setSimText(BENIGN_SCRIPT)
              runScript(BENIGN_SCRIPT)
            }}
            disabled={simBusy}
          >
            Benign script
          </Button>
        </div>
        <div className="mt-2 flex flex-wrap gap-2">
          <Button
            onClick={() => {
              setSimText(UNDEFINED_TERM_SCRIPT)
              runScript(UNDEFINED_TERM_SCRIPT)
            }}
            disabled={simBusy}
          >
            Undefined-term script
          </Button>
          <Button
            onClick={() => {
              setSimText(LOST_THREAD_SCRIPT)
              runScript(LOST_THREAD_SCRIPT)
            }}
            disabled={simBusy}
          >
            Lost-thread script
          </Button>
        </div>
      </section>

      {/* --- floor tests ------------------------------------------------ */}
      <section className="mb-4 border-t pt-3" style={{ borderColor: 'var(--paper-line)' }}>
        <p style={{ fontFamily: 'var(--font-sans)', fontSize: '0.72rem', color: 'var(--ink-dim)', margin: '0 0 0.4rem' }}>
          Floor machine
        </p>
        <div className="flex flex-wrap gap-2">
          <Button onClick={onFakeObjection} disabled={!floorIdle}>
            Fake objection (client-only)
          </Button>
          <Button onClick={onBargeInNow} disabled={floorIdle}>
            Barge-in now
          </Button>
          <Button onClick={onEchoNow} disabled={floorIdle}>
            Echo now
          </Button>
        </div>
      </section>

      {/* --- replay + export --------------------------------------------- */}
      <section className="mb-4 border-t pt-3" style={{ borderColor: 'var(--paper-line)' }}>
        <div className="flex flex-wrap gap-2">
          <Button onClick={onReplayStart}>Replay start</Button>
          <Button onClick={onReplayStop}>Replay stop</Button>
          <Button onClick={onDownload}>Download draft.md</Button>
        </div>
      </section>

      {/* --- event log --------------------------------------------------- */}
      <section className="border-t pt-3" style={{ borderColor: 'var(--paper-line)' }}>
        <p style={{ fontFamily: 'var(--font-sans)', fontSize: '0.72rem', color: 'var(--ink-dim)', margin: '0 0 0.4rem' }}>
          Event log
        </p>
        <div className="thin-scroll" style={{ maxHeight: '220px', overflowY: 'auto' }}>
          {events.length === 0 && (
            <p style={{ fontFamily: 'var(--font-sans)', fontSize: '0.68rem', color: 'var(--ink-faint)' }}>(empty)</p>
          )}
          {[...events].reverse().map((ev, i) => (
            <div
              key={events.length - i}
              style={{
                fontFamily: 'var(--font-sans)',
                fontSize: '0.66rem',
                color: 'var(--ink-dim)',
                padding: '0.15rem 0',
                borderBottom: '1px solid rgba(255,255,255,0.03)',
              }}
            >
              <span style={{ color: 'var(--ink-faint)' }}>
                {new Date(ev.ts).toLocaleTimeString([], { hour12: false })}
              </span>{' '}
              <span style={{ color: 'var(--amber)' }}>{ev.kind}</span>{' '}
              <span>{ev.detail}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
