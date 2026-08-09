import { useEffect, useRef, useState } from 'react'
import { createChunker } from '../chunker.js'

// CaptureField — SPEC.md §6 "Chunker" / §13.E.
// A real <textarea>, visually minimal, thin strip pinned at the bottom.
// VoiceOS (or the DevPanel sim) types into it; the chunker decides when a
// burst of text becomes a finished utterance. Deliberately UNCONTROLLED:
// the DOM node is the source of truth so that native/synthetic `input`
// events (real VoiceOS keystrokes, or the DevPanel's native-setter sim)
// are picked up identically to a user typing directly into it.
export default function CaptureField({
  textareaRef,
  getPauseMs,
  onUtterance,
  leftInset = 0,
  resetSignal,
  placeholder = 'listening…',
}) {
  const chunkerRef = useRef(null)
  const [justSent, setJustSent] = useState('')
  const [justSentKey, setJustSentKey] = useState(0)
  const [hasText, setHasText] = useState(false)

  useEffect(() => {
    chunkerRef.current = createChunker({
      getPauseMs,
      onUtterance: (text) => {
        const el = textareaRef.current
        if (el) el.value = ''
        setHasText(false)
        setJustSent(text)
        setJustSentKey((k) => k + 1)
        onUtterance(text)
      },
      onInFlightChange: (buf) => {
        setHasText(buf.trim().length > 0)
      },
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Server `reset` (§13.E: "reset -> client clears all state") also
  // discards any in-flight, not-yet-chunked text sitting in the field.
  useEffect(() => {
    if (resetSignal === undefined) return
    chunkerRef.current?.reset()
    if (textareaRef.current) textareaRef.current.value = ''
    setHasText(false)
    setJustSent('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetSignal])

  function handleInput(e) {
    chunkerRef.current?.handleInput(e.target.value)
  }

  return (
    <div
      className="pointer-events-none fixed bottom-0 z-30 flex justify-center pb-4 transition-[left] duration-200"
      style={{ left: leftInset, right: 0 }}
    >
      <div className="pointer-events-auto relative w-full max-w-3xl px-6">
        <div
          className="fade-in"
          style={{
            fontFamily: 'var(--font-sans)',
            fontSize: '0.75rem',
            color: 'var(--ink-faint)',
            height: '1.1rem',
            paddingLeft: '0.9rem',
          }}
        >
          {justSent ? (
            <span key={justSentKey} className="capture-echo">
              {justSent}
            </span>
          ) : null}
        </div>
        <textarea
          ref={textareaRef}
          rows={1}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          aria-label="Voice capture field"
          data-capture-field="true"
          placeholder={hasText ? '' : placeholder}
          onInput={handleInput}
          className="capture-textarea w-full resize-none bg-transparent outline-none"
          style={{
            fontFamily: 'var(--font-sans)',
            fontSize: '0.95rem',
            lineHeight: 1.4,
            color: hasText ? 'var(--ink)' : 'var(--ink-faint)',
            padding: '0.5rem 0.9rem',
            border: 'none',
            borderTop: '1px solid var(--paper-line)',
          }}
        />
      </div>
    </div>
  )
}
