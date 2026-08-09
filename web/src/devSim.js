// devSim.js — DevPanel's "Sim VoiceOS" helpers. SPEC.md §8, §13.E:
// "Sim VoiceOS must drive the real pipeline: set the textarea value via
// the native value setter and dispatch real input events, in sentence
// bursts with 300-900ms random gaps — the chunker must not be able to
// tell it apart from VoiceOS."

/** Set a DOM input/textarea's value via the *native* setter, bypassing
 * any React-controlled value tracking, then dispatch a real `input`
 * event so listeners (React's onInput, or plain DOM listeners) see it
 * exactly as they would a genuine external keystroke. */
export function setNativeValue(element, value) {
  const proto = Object.getPrototypeOf(element)
  const descriptor = Object.getOwnPropertyDescriptor(proto, 'value')
  const setter = descriptor && descriptor.set
  if (setter) {
    setter.call(element, value)
  } else {
    element.value = value
  }
  element.dispatchEvent(new Event('input', { bubbles: true }))
}

export function sentenceSplit(text) {
  return text
    .split(/(?<=[.?!])\s+/)
    .map((s) => s.trim())
    .filter(Boolean)
}

function wordBursts(sentence) {
  const words = sentence.split(/\s+/).filter(Boolean)
  const bursts = []
  let i = 0
  while (i < words.length) {
    const n = 2 + Math.floor(Math.random() * 3) // 2-4 words per burst
    bursts.push(words.slice(i, i + n).join(' '))
    i += n
  }
  return bursts.length ? bursts : [sentence]
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function randBetween(min, max) {
  return min + Math.random() * (max - min)
}

/**
 * Build a playable WAV (soft 220Hz hum) as a blob URL. Stands in for a
 * real TTS mp3 in the DevPanel's client-only "Fake objection" rehearsal
 * path, so the audio->floor-arm->echo/barge-in chain (§9 Phases 3-4) is
 * exercisable with no server TTS and no OpenAI key.
 */
export function makeRehearsalToneUrl(seconds = 4) {
  const rate = 8000
  const n = Math.floor(rate * seconds)
  const buf = new ArrayBuffer(44 + n * 2)
  const v = new DataView(buf)
  const wstr = (off, s) => {
    for (let i = 0; i < s.length; i += 1) v.setUint8(off + i, s.charCodeAt(i))
  }
  wstr(0, 'RIFF')
  v.setUint32(4, 36 + n * 2, true)
  wstr(8, 'WAVE')
  wstr(12, 'fmt ')
  v.setUint32(16, 16, true)
  v.setUint16(20, 1, true) // PCM
  v.setUint16(22, 1, true) // mono
  v.setUint32(24, rate, true)
  v.setUint32(28, rate * 2, true)
  v.setUint16(32, 2, true)
  v.setUint16(34, 16, true)
  wstr(36, 'data')
  v.setUint32(40, n * 2, true)
  const samples = new Int16Array(buf, 44)
  for (let i = 0; i < n; i += 1) {
    const envelope = Math.min(1, i / 400, (n - i) / 400) // no click at edges
    samples[i] = Math.round(Math.sin((i / rate) * 2 * Math.PI * 220) * 2500 * envelope)
  }
  return URL.createObjectURL(new Blob([buf], { type: 'audio/wav' }))
}

/**
 * Commit `fullText` into `el` sentence-by-sentence, word-burst by
 * word-burst, with 300-900ms gaps between bursts (per spec) — goes
 * through the real chunker exactly like VoiceOS would.
 *
 * @param {HTMLTextAreaElement} el
 * @param {string} fullText
 * @param {object} [opts]
 * @param {() => boolean} [opts.shouldStop]  checked between bursts; abort if true
 * @param {() => boolean} [opts.shouldPause]  while true, wait (Critic speaking)
 * @param {(piece: string) => void} [opts.onBurst]
 */
export async function speakIntoField(el, fullText, opts = {}) {
  const { shouldStop, shouldPause, onBurst } = opts
  const sentences = sentenceSplit(fullText)

  async function waitIfPaused() {
    while (shouldPause?.()) {
      if (shouldStop?.()) return true
      await sleep(100)
    }
    return shouldStop?.()
  }

  for (const sentence of sentences) {
    if (await waitIfPaused()) return
    const bursts = wordBursts(sentence)
    for (let i = 0; i < bursts.length; i += 1) {
      if (await waitIfPaused()) return
      const isLast = i === bursts.length - 1
      const sep = el.value && !el.value.endsWith(' ') ? ' ' : ''
      setNativeValue(el, el.value + sep + bursts[i])
      onBurst?.(bursts[i])
      if (!isLast) {
        await sleep(randBetween(300, 900))
      }
    }
    // Gap between sentences: long enough to clear the chunker's
    // terminal-punctuation "idle beat" (300ms) so this sentence closes
    // as its own utterance before the next one starts appending.
    await sleep(randBetween(500, 900))
  }
}
