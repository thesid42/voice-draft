// InterruptBanner — VoiceOS-first: read the objection, speak the answer
// into the capture field (always focused). No typed reply box — that would
// steal VoiceOS targeting. Ignore is also a voice command: "Draft, ignore that."
const KIND_LABELS = {
  contradiction: 'Contradiction',
  vague_claim: 'Vague claim',
  undefined_term: 'Undefined term',
  lost_thread: 'Lost thread',
  implausible_claim: 'Implausible claim',
}

const KIND_WHY = {
  contradiction: 'This clashes with something you said earlier.',
  vague_claim: 'This number or comparison has no anchor.',
  undefined_term: 'This term is doing real work and was never explained.',
  lost_thread: 'The last few lines drifted off the point of the document.',
  implausible_claim: 'This is presented as fact but cannot be true.',
}

export default function InterruptBanner({
  objection,
  refBlocks = [],
  onIgnore,
  onHearAgain,
  canHearAgain = false,
  leftInset = 0,
}) {
  if (!objection) return null

  const label = KIND_LABELS[objection.kind] || objection.kind
  const why = KIND_WHY[objection.kind] || ''

  return (
    <div
      className="pointer-events-none fixed inset-x-0 top-16 z-20 flex justify-center px-4 sm:top-20"
      style={{ left: leftInset }}
    >
      <div
        className="banner-enter pointer-events-auto w-full max-w-xl"
        style={{
          background: 'var(--paper-raised)',
          border: '1px solid var(--amber-soft)',
          borderRadius: '12px',
          padding: '1.1rem 1.25rem 1rem',
          boxShadow: '0 18px 48px rgba(0,0,0,0.5)',
        }}
      >
        <div className="mb-1.5 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span
            style={{
              fontFamily: 'var(--font-sans)',
              fontSize: '0.68rem',
              letterSpacing: '0.1em',
              textTransform: 'uppercase',
              color: 'var(--amber)',
            }}
          >
            Editor · {label}
          </span>
          {why && (
            <span style={{ fontFamily: 'var(--font-sans)', fontSize: '0.72rem', color: 'var(--ink-faint)' }}>
              {why}
            </span>
          )}
        </div>

        <p
          style={{
            fontFamily: 'var(--font-serif)',
            fontSize: 'clamp(1.15rem, 2.4vw, 1.45rem)',
            lineHeight: 1.4,
            color: 'var(--ink)',
            margin: '0 0 0.75rem',
          }}
        >
          {objection.message}
        </p>

        {refBlocks.length > 0 && (
          <div className="mb-3 flex flex-col gap-1.5">
            {refBlocks.map((b) => (
              <p
                key={b.id}
                style={{
                  fontFamily: 'var(--font-serif)',
                  fontSize: '0.88rem',
                  lineHeight: 1.5,
                  color: 'var(--ink-dim)',
                  margin: 0,
                  padding: '0.35rem 0.65rem',
                  borderLeft: '2px solid var(--amber)',
                }}
              >
                {b.text}
              </p>
            ))}
          </div>
        )}

        <p
          style={{
            fontFamily: 'var(--font-sans)',
            fontSize: '0.8rem',
            lineHeight: 1.45,
            color: 'var(--ink-dim)',
            margin: '0 0 0.85rem',
          }}
        >
          Speak your answer — VoiceOS types it in. Or say{' '}
          <span style={{ color: 'var(--ink)' }}>Draft, ignore that</span>.
        </p>

        <div className="flex flex-wrap items-center justify-between gap-2">
          {canHearAgain ? (
            <button
              type="button"
              onClick={onHearAgain}
              style={{
                fontFamily: 'var(--font-sans)',
                fontSize: '0.75rem',
                color: 'var(--ink)',
                background: 'transparent',
                border: '1px solid var(--paper-line)',
                borderRadius: '6px',
                padding: '0.35rem 0.7rem',
              }}
            >
              Hear again
            </button>
          ) : (
            <span />
          )}
          <button
            type="button"
            onClick={onIgnore}
            style={{
              fontFamily: 'var(--font-sans)',
              fontSize: '0.75rem',
              color: 'var(--ink-dim)',
              background: 'transparent',
              border: 'none',
              padding: '0.35rem 0.2rem',
            }}
          >
            Ignore
          </button>
        </div>
      </div>
    </div>
  )
}
