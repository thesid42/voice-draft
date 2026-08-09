// InterruptBanner.jsx — SPEC.md §6: objection text + kind tag + [Ignore].
// Slides in near the orb. Auto-hide timing is owned by App (it depends on
// audio-ended + a 10s timer); this component just renders what it's given.
const KIND_LABELS = {
  contradiction: 'Contradiction',
  vague_claim: 'Vague claim',
  undefined_term: 'Undefined term',
  lost_thread: 'Lost thread',
}

export default function InterruptBanner({ objection, onIgnore }) {
  if (!objection) return null
  const label = KIND_LABELS[objection.kind] || objection.kind

  return (
    <div className="pointer-events-none fixed right-6 top-24 z-20 flex justify-end sm:right-10 sm:top-28">
      <div
        className="banner-enter pointer-events-auto w-72 sm:w-80"
        style={{
          background: 'var(--paper-raised)',
          border: '1px solid var(--paper-line)',
          borderRadius: '10px',
          padding: '0.85rem 1rem',
          boxShadow: '0 12px 32px rgba(0,0,0,0.45)',
        }}
      >
        <div className="mb-1.5 flex items-center justify-between">
          <span
            style={{
              fontFamily: 'var(--font-sans)',
              fontSize: '0.62rem',
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
              color: 'var(--amber)',
            }}
          >
            {label}
          </span>
        </div>
        <p
          style={{
            fontFamily: 'var(--font-sans)',
            fontSize: '0.88rem',
            lineHeight: 1.5,
            color: 'var(--ink)',
            margin: 0,
          }}
        >
          {objection.message}
        </p>
        <div className="mt-2.5 flex justify-end">
          <button
            type="button"
            onClick={onIgnore}
            style={{
              fontFamily: 'var(--font-sans)',
              fontSize: '0.72rem',
              color: 'var(--ink-dim)',
              background: 'transparent',
              border: '1px solid var(--paper-line)',
              borderRadius: '6px',
              padding: '0.3rem 0.6rem',
            }}
          >
            Ignore
          </button>
        </div>
      </div>
    </div>
  )
}
