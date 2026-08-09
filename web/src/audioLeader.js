// audioLeader.js — exactly ONE tab per origin plays Critic/readback audio.
//
// Every connected tab receives the same interrupt broadcast; without an
// election, N open tabs (a second window, a forgotten DevPanel tab, an
// observer mirror) each play the same mp3 a few hundred ms apart — which
// sounds like an echo even on earphones (three GET /tts/o1.mp3 in the
// server log = three tabs playing).
//
// Web Locks gives us leadership for free: every non-observer tab queues an
// exclusive request for the same lock; the browser grants it to exactly one
// tab at a time and auto-releases it when that tab closes/navigates — at
// which point the next queued tab is granted the lock and seamlessly takes
// over speaking. No polling, no channels, no split-brain.
//
// Module-level on purpose: the held lock must survive React/HMR remounts of
// App.jsx (a component-scoped lock would leak leadership to a dead closure
// after a hot update).

let joined = false
let leader = false
const listeners = new Set()

export function isAudioLeader() {
  return leader
}

/** Subscribe to leadership changes; fires immediately with current state. */
export function subscribeAudioLeader(fn) {
  listeners.add(fn)
  fn(leader)
  return () => listeners.delete(fn)
}

export function joinAudioLeaderElection() {
  if (joined) return
  joined = true
  if (!navigator.locks || typeof navigator.locks.request !== 'function') {
    // Ancient browser: no election possible — better to risk double audio
    // than a silent demo.
    leader = true
    listeners.forEach((fn) => fn(true))
    return
  }
  navigator.locks.request('draft-audio-leader', () => {
    leader = true
    listeners.forEach((fn) => fn(true))
    return new Promise(() => {}) // hold the lock until this tab goes away
  })
}
