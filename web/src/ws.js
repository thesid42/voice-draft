// ws.js — WebSocket client with auto-reconnect + backoff.
// SPEC.md §4 (protocol), §13.A (hello/set_config), §13.D (never crash: the
// server may not be up at all while the frontend runs standalone).

const MAX_BACKOFF_MS = 8000
const BASE_BACKOFF_MS = 600

function wsUrl() {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/ws`
}

/**
 * @param {object} opts
 * @param {(msg: any) => void} opts.onMessage      parsed JSON message from server
 * @param {(status: 'connecting'|'connected'|'disconnected') => void} opts.onStatusChange
 * @param {() => void} [opts.onOpen]               fired after a successful connect
 */
export function createWsClient({ onMessage, onStatusChange, onOpen }) {
  let socket = null
  let attempt = 0
  let closedByUser = false
  let reconnectTimer = null
  let status = 'connecting'

  function setStatus(s) {
    status = s
    onStatusChange?.(s)
  }

  function connect() {
    clearTimeout(reconnectTimer)
    setStatus('connecting')
    try {
      socket = new WebSocket(wsUrl())
    } catch (err) {
      // Malformed URL etc. — should not happen, but never let this throw
      // out of the module. Just retry on the normal backoff schedule.
      scheduleReconnect()
      return
    }

    socket.onopen = () => {
      attempt = 0
      setStatus('connected')
      onOpen?.()
    }

    socket.onmessage = (ev) => {
      let msg
      try {
        msg = JSON.parse(ev.data)
      } catch (err) {
        console.warn('[ws] ignoring malformed message', ev.data)
        return
      }
      try {
        onMessage(msg)
      } catch (err) {
        // A bug in a message handler must never take down the socket.
        console.error('[ws] handler error', err)
      }
    }

    socket.onclose = () => {
      socket = null
      setStatus('disconnected')
      if (!closedByUser) scheduleReconnect()
    }

    socket.onerror = () => {
      // onclose always follows onerror for browser WebSockets; no separate
      // handling needed here beyond avoiding an unhandled exception.
    }
  }

  function scheduleReconnect() {
    attempt += 1
    const backoff = Math.min(BASE_BACKOFF_MS * 2 ** (attempt - 1), MAX_BACKOFF_MS)
    const jitter = Math.random() * 250
    reconnectTimer = setTimeout(connect, backoff + jitter)
  }

  /** Send a plain object as JSON. Returns false (no throw) if not connected. */
  function send(obj) {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(obj))
      return true
    }
    return false
  }

  function getStatus() {
    return status
  }

  function close() {
    closedByUser = true
    clearTimeout(reconnectTimer)
    socket?.close()
  }

  connect()

  return { send, close, getStatus, reconnectNow: connect }
}
