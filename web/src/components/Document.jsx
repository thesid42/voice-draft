// Document.jsx — SPEC.md §6: big serif type, generous spacing, dark theme,
// readable from the back of a room. status:new fades in, status:revised
// flashes, refs blocks glow (amber ring) while an objection is active.
export default function Document({ title, blocks, updateSeq, glowingBlockIds }) {
  const isEmpty = blocks.length === 0

  return (
    <div className="mx-auto w-full max-w-3xl px-6 pb-40 pt-24 sm:pt-28">
      {isEmpty ? (
        <div className="flex flex-col items-center justify-center gap-3 pt-24 text-center fade-in">
          <p
            style={{
              fontFamily: 'var(--font-serif)',
              fontSize: '1.5rem',
              color: 'var(--ink-dim)',
            }}
          >
            Start speaking. Draft is listening.
          </p>
          <p style={{ fontFamily: 'var(--font-sans)', fontSize: '0.85rem', color: 'var(--ink-faint)' }}>
            The document appears as you think out loud.
          </p>
        </div>
      ) : (
        <>
          <h1
            className="fade-in mb-10"
            style={{
              fontFamily: 'var(--font-serif)',
              fontSize: 'clamp(1.9rem, 3.2vw, 2.6rem)',
              fontWeight: 400,
              color: 'var(--ink)',
              letterSpacing: '-0.01em',
              lineHeight: 1.2,
              padding: '0 0.9rem',
            }}
          >
            {title || 'Untitled'}
          </h1>
          <div className="flex flex-col gap-6">
            {blocks.map((block) => {
              const isGlowing = glowingBlockIds.has(block.id)
              const animKey = block.status === 'unchanged' ? block.id : `${block.id}-u${updateSeq}`
              const statusClass =
                block.status === 'new' ? 'block-new' : block.status === 'revised' ? 'block-revised' : ''
              return (
                <p
                  key={animKey}
                  data-block-id={block.id}
                  className={[statusClass, isGlowing ? 'block-glow' : ''].filter(Boolean).join(' ')}
                  style={{
                    fontFamily: 'var(--font-serif)',
                    fontSize: '1.2rem',
                    lineHeight: 1.75,
                    color: 'var(--ink)',
                    // Constant padding regardless of glow state so the amber
                    // ring toggling on/off never shifts the text layout.
                    padding: '0.6rem 0.9rem',
                    margin: 0,
                  }}
                >
                  {block.text}
                </p>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
