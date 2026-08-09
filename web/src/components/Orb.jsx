// Orb.jsx — SPEC.md §6: idle (dim pulse) / thinking (writer status) /
// speaking (bright pulse synced to audio). §13.C: readback speaking uses
// the *plain* speaking style — no distinct "objection" orb-state.
// Pure CSS animation only (no gradients/glassmorphism).
export default function Orb({ writerStatus, speaking, objectionSpeaking }) {
  let mode = 'idle'
  if (speaking) {
    mode = objectionSpeaking ? 'speaking-objection' : 'speaking'
  } else if (writerStatus === 'thinking') {
    mode = 'thinking'
  }

  const coreClass =
    mode === 'idle'
      ? 'orb-core-idle'
      : mode === 'thinking'
        ? 'orb-core-thinking'
        : 'orb-core-speaking'

  const palette = {
    idle: { bg: 'var(--ink-faint)', glow: 'transparent' },
    thinking: { bg: 'var(--ink-dim)', glow: 'rgba(163, 157, 143, 0.35)' },
    speaking: { bg: '#eee7d6', glow: 'rgba(238, 231, 214, 0.45)' },
    'speaking-objection': { bg: 'var(--amber-bright)', glow: 'rgba(231, 185, 85, 0.6)' },
  }[mode]

  return (
    <div className="pointer-events-none fixed right-6 top-6 z-30 flex flex-col items-center gap-2 sm:right-10 sm:top-8">
      <div className="relative flex h-14 w-14 items-center justify-center">
        {mode === 'thinking' && (
          <div
            className="orb-ring-thinking absolute inset-0 rounded-full"
            style={{ border: '1px solid rgba(163,157,143,0.3)', borderTopColor: 'rgba(163,157,143,0.7)' }}
          />
        )}
        <div
          className={coreClass}
          style={{
            width: '1.15rem',
            height: '1.15rem',
            borderRadius: '9999px',
            background: palette.bg,
            boxShadow: `0 0 20px 4px ${palette.glow}`,
          }}
        />
      </div>
      <span
        className="select-none"
        style={{ fontFamily: 'var(--font-sans)', fontSize: '0.62rem', letterSpacing: '0.08em', color: 'var(--ink-faint)', textTransform: 'uppercase' }}
      >
        {mode === 'idle' && 'idle'}
        {mode === 'thinking' && 'thinking'}
        {(mode === 'speaking' || mode === 'speaking-objection') && 'speaking'}
      </span>
    </div>
  )
}
