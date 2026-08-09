// chunker.js — turns raw CaptureField input events into utterances.
// SPEC.md §6 "Chunker": close an utterance when
//   - no new characters for PAUSE_MS (default 700, live-tunable), OR
//   - text ends with . ? ! followed by a space/idle beat.
// On close: emit utterance (trimmed), clear the field. Never send empty.
//
// Pure, DOM-free state machine so it's easy to reason about / reuse from
// both real typing and the DevPanel's simulated VoiceOS bursts.

const BEAT_MS = 300 // "idle beat" after terminal punctuation, per §6

const TERMINAL_RE = /[.?!]\s*$/

/**
 * @param {object} opts
 * @param {() => number} opts.getPauseMs   live-tunable PAUSE_MS getter
 * @param {(text: string) => void} opts.onUtterance   fired with trimmed, non-empty text
 * @param {(text: string) => void} [opts.onInFlightChange] fired on every input w/ current buffer
 */
export function createChunker({ getPauseMs, onUtterance, onInFlightChange }) {
  let buffer = ''
  let timer = null

  function clearTimer() {
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
  }

  function close() {
    clearTimer()
    const text = buffer.trim()
    buffer = ''
    if (text.length > 0) {
      onUtterance(text)
    }
  }

  /** Call with the CaptureField's full current value on every input event. */
  function handleInput(value) {
    buffer = value ?? ''
    onInFlightChange?.(buffer)
    clearTimer()

    if (buffer.trim().length === 0) return

    if (TERMINAL_RE.test(buffer)) {
      timer = setTimeout(close, BEAT_MS)
    } else {
      timer = setTimeout(close, getPauseMs())
    }
  }

  /** Discard any in-flight text without emitting an utterance (e.g. on reset). */
  function reset() {
    clearTimer()
    buffer = ''
  }

  return { handleInput, reset }
}
