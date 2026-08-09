// audio.js — TTS playback (objection/readback mp3) + WebAudio mic RMS
// volume-duck fast path. SPEC.md §6 "Volume-duck fast path", §13.D.
//
// Playback: a single reused <audio> element. play(url) resolves once the
// clip actually ends (or fails to start at all, e.g. autoplay blocked —
// treated as "ended immediately", never left hanging).
//
// Ducking: getUserMedia on load (best-effort). Sustained mic energy
// (~200ms) above a threshold while something is playing -> duck to 10%
// instantly. The floor machine's text verdict then decides the rest:
// echo match -> restore(); barge-in -> stopImmediately(). If neither
// verdict arrives (false alarm / stray noise), we auto-restore after a
// short timeout so a cough never leaves playback stuck at 10%.

const DUCK_VOLUME = 0.1
const SUSTAIN_MS = 200
const AUTO_RESTORE_MS = 1500

/**
 * @param {object} opts
 * @param {(speaking: boolean) => void} opts.onSpeakingChange
 * @param {() => boolean} opts.getDuckEnabled       client-local DevPanel toggle
 * @param {() => number} opts.getDuckThreshold       client-local DevPanel slider (RMS 0..1)
 * @param {(available: boolean, detail?: string) => void} [opts.onMicStatusChange]
 * @param {(ducked: boolean) => void} [opts.onDuckChange]
 * @param {(kind: string, detail: string) => void} [opts.onLog]
 */
export function createAudioEngine({
  onSpeakingChange,
  getDuckEnabled,
  getDuckThreshold,
  onMicStatusChange,
  onDuckChange,
  onLog,
}) {
  const el = new Audio()
  el.preload = 'auto'

  let playing = false
  let pendingEndedResolve = null
  let duckRestoreTimer = null

  function log(kind, detail) {
    onLog?.(kind, detail)
  }

  function finishPlayback() {
    if (!playing) return
    playing = false
    clearTimeout(duckRestoreTimer)
    duckRestoreTimer = null
    onSpeakingChange(false)
    const resolve = pendingEndedResolve
    pendingEndedResolve = null
    resolve?.()
  }

  el.addEventListener('ended', finishPlayback)
  el.addEventListener('error', () => {
    if (playing) {
      log('audio_error', el.error?.message || 'unknown playback error')
      finishPlayback()
    }
  })

  /**
   * Play a TTS clip. Resolves when it ends (or immediately if it never
   * managed to start, e.g. blocked autoplay). Never rejects.
   *
   * `onStart` fires at the exact moment playback actually begins (not
   * when `play()` is called) — the caller uses this to arm the floor
   * machine "the instant audio starts", per SPEC.md §6/§13.C. If
   * playback never starts, `onStart` never fires and the floor machine
   * is correctly never armed (nothing is playing -> no echo risk).
   */
  function play(url, onStart) {
    return new Promise((resolve) => {
      if (!url) {
        resolve()
        return
      }
      stopImmediately()
      pendingEndedResolve = resolve
      el.src = url
      el.volume = 1
      const playPromise = el.play()
      if (playPromise && typeof playPromise.then === 'function') {
        playPromise
          .then(() => {
            playing = true
            onSpeakingChange(true)
            onStart?.()
          })
          .catch((err) => {
            log('audio_blocked', String(err?.message || err))
            playing = false
            onSpeakingChange(false)
            const r = pendingEndedResolve
            pendingEndedResolve = null
            r?.()
          })
      } else {
        playing = true
        onSpeakingChange(true)
        onStart?.()
      }
    })
  }

  /** Kill playback right now (barge-in path). Must be near-instant. */
  function stopImmediately() {
    clearTimeout(duckRestoreTimer)
    duckRestoreTimer = null
    if (!el.paused) {
      el.pause()
    }
    el.currentTime = 0
    el.volume = 1
    if (playing) {
      playing = false
      onSpeakingChange(false)
    }
    if (pendingEndedResolve) {
      const r = pendingEndedResolve
      pendingEndedResolve = null
      r()
    }
  }

  function duck() {
    if (el.volume !== DUCK_VOLUME) {
      el.volume = DUCK_VOLUME
      onDuckChange?.(true)
    }
    clearTimeout(duckRestoreTimer)
    duckRestoreTimer = setTimeout(restore, AUTO_RESTORE_MS)
  }

  function restore() {
    clearTimeout(duckRestoreTimer)
    duckRestoreTimer = null
    if (el.volume !== 1) {
      el.volume = 1
      onDuckChange?.(false)
    }
  }

  // --- mic RMS monitor -----------------------------------------------

  let micCtx = null
  let analyser = null
  let micStream = null
  let rafHandle = null
  let sampleBuf = null
  let sustainedSinceMs = null

  async function initMic() {
    if (!navigator.mediaDevices?.getUserMedia) {
      onMicStatusChange?.(false, 'getUserMedia unsupported')
      return
    }
    try {
      micStream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const Ctx = window.AudioContext || window.webkitAudioContext
      micCtx = new Ctx()
      const source = micCtx.createMediaStreamSource(micStream)
      analyser = micCtx.createAnalyser()
      analyser.fftSize = 512
      sampleBuf = new Uint8Array(analyser.fftSize)
      source.connect(analyser)
      onMicStatusChange?.(true)
      rafHandle = requestAnimationFrame(rmsLoop)
    } catch (err) {
      onMicStatusChange?.(false, err?.message || String(err))
    }
  }

  function rmsLoop() {
    rafHandle = requestAnimationFrame(rmsLoop)
    if (!analyser || !sampleBuf) return

    analyser.getByteTimeDomainData(sampleBuf)
    let sumSquares = 0
    for (let i = 0; i < sampleBuf.length; i += 1) {
      const v = (sampleBuf[i] - 128) / 128
      sumSquares += v * v
    }
    const rms = Math.sqrt(sumSquares / sampleBuf.length)
    const threshold = getDuckThreshold()
    const now = performance.now()

    if (rms >= threshold) {
      if (sustainedSinceMs == null) sustainedSinceMs = now
      const sustained = now - sustainedSinceMs >= SUSTAIN_MS
      if (sustained && playing && getDuckEnabled()) {
        duck()
      }
    } else {
      sustainedSinceMs = null
    }
  }

  function dispose() {
    if (rafHandle) cancelAnimationFrame(rafHandle)
    micStream?.getTracks().forEach((t) => t.stop())
    micCtx?.close().catch(() => {})
  }

  return {
    play,
    stopImmediately,
    restore,
    initMic,
    dispose,
    isPlaying: () => playing,
  }
}
