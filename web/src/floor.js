// floor.js — the floor state machine + echo matcher. SPEC.md §6, §13.C.
//
//   USER_FLOOR (default)
//     chunker output -> send as utterance.
//
//   AGENT_SPEAKING (entered the instant app-played audio actually starts —
//   objection OR readback, per §13.C: ANY app-played audio arms the floor)
//     chunker output -> quarantine -> echoMatch(text, currentScript)
//       match    -> drop silently (our own TTS transcribed back)
//       no match -> BARGE-IN: stop audio immediately, send control:barged_in,
//                   forward text as utterance, -> USER_FLOOR.
//
//   GRACE (for GRACE_MS after audio ends)
//     matcher stays armed (VoiceOS's transcription of our audio often lands
//     AFTER playback finishes). Non-matching text = normal utterance,
//     no barge-in control (nothing is playing to kill) -> USER_FLOOR.
//
// echoMatch (§13.E): token-SET overlap = |incoming ∩ script| / |incoming|,
// denominator = incoming utterance's unique tokens, threshold 0.6.

export const FloorState = Object.freeze({
  USER_FLOOR: 'USER_FLOOR',
  AGENT_SPEAKING: 'AGENT_SPEAKING',
  GRACE: 'GRACE',
})

const ECHO_THRESHOLD = 0.6

function tokenize(s) {
  return (s || '')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .split(/\s+/)
    .filter(Boolean)
}

/** Exported standalone so the DevPanel / tests can call it directly. */
export function echoMatch(incoming, script) {
  const incomingTokens = new Set(tokenize(incoming))
  if (incomingTokens.size === 0) return false
  const scriptTokens = new Set(tokenize(script))
  if (scriptTokens.size === 0) return false
  let overlap = 0
  for (const t of incomingTokens) {
    if (scriptTokens.has(t)) overlap += 1
  }
  return overlap / incomingTokens.size >= ECHO_THRESHOLD
}

/**
 * @param {object} callbacks
 * @param {(text: string) => void} callbacks.onSend        forward text as a normal utterance
 * @param {(text: string) => void} callbacks.onBargeIn      real barge-in: stop audio + control:barged_in (text is also sent via onSend right after)
 * @param {(text: string) => void} callbacks.onEchoDropped  echo matched -> silently dropped
 * @param {(state: string) => void} [callbacks.onStateChange]
 */
export function createFloorMachine({ onSend, onBargeIn, onEchoDropped, onStateChange }) {
  let state = FloorState.USER_FLOOR
  let script = ''
  let isObjection = false
  let graceTimer = null

  function setState(next) {
    if (state === next) return
    state = next
    onStateChange?.(state)
  }

  /** Call the instant app-played audio actually starts playing. */
  function armSpeaking(scriptText, opts = {}) {
    clearTimeout(graceTimer)
    graceTimer = null
    script = scriptText || ''
    isObjection = !!opts.isObjection
    setState(FloorState.AGENT_SPEAKING)
  }

  /** Call when the app-played audio ends (or fails to start at all). */
  function audioEnded(graceMs) {
    if (state === FloorState.USER_FLOOR) return
    setState(FloorState.GRACE)
    clearTimeout(graceTimer)
    graceTimer = setTimeout(() => {
      graceTimer = null
      script = ''
      isObjection = false
      setState(FloorState.USER_FLOOR)
    }, Math.max(0, graceMs))
  }

  /** Feed one finished utterance (from the real chunker, or DevPanel sim). */
  function feed(text) {
    if (state === FloorState.USER_FLOOR) {
      onSend(text)
      return
    }

    const matched = echoMatch(text, script)
    if (matched) {
      onEchoDropped(text)
      return
    }

    // No match: real user speech overlapping our own playback/grace window.
    const wasAgentSpeaking = state === FloorState.AGENT_SPEAKING
    clearTimeout(graceTimer)
    graceTimer = null
    script = ''
    isObjection = false
    setState(FloorState.USER_FLOOR)

    if (wasAgentSpeaking) {
      onBargeIn(text)
    }
    onSend(text)
  }

  function reset() {
    clearTimeout(graceTimer)
    graceTimer = null
    script = ''
    isObjection = false
    setState(FloorState.USER_FLOOR)
  }

  return {
    armSpeaking,
    audioEnded,
    feed,
    reset,
    getState: () => state,
    getScript: () => script,
    isObjectionScript: () => isObjection,
  }
}
