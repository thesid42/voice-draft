import { useEffect, useRef, useState } from 'react'
import QRCode from 'qrcode'

// ShareOverlay.jsx — SPEC.md §14.B: shown on the server's
// {"type":"share","url":...} broadcast (App.jsx stores it as `url`).
// Dismisses on click anywhere on the overlay, or on the next dispatched
// utterance — App bumps `dismissSignal` once per call to
// dispatchUtteranceText (the single funnel for real chunker output AND
// barge-in forwards), mirroring the existing resetSignal convention used by
// CaptureField. The QR is rendered locally via the `qrcode` package
// (canvas -> data URL) — no network round-trip, no CDN, works offline.
const QR_LIGHT = '#eae6dc' // must match --ink in index.css
const QR_DARK = '#131210' // must match --paper in index.css

export default function ShareOverlay({ url, dismissSignal, onDismiss }) {
  const [qrDataUrl, setQrDataUrl] = useState(null)

  useEffect(() => {
    if (!url) {
      setQrDataUrl(null)
      return
    }
    let cancelled = false
    QRCode.toDataURL(url, {
      errorCorrectionLevel: 'M',
      margin: 1,
      width: 480,
      color: { dark: QR_DARK, light: QR_LIGHT },
    })
      .then((dataUrl) => {
        if (!cancelled) setQrDataUrl(dataUrl)
      })
      .catch(() => {
        // Never let a QR-render failure take the overlay down — the URL
        // text underneath is still fully usable on its own.
        if (!cancelled) setQrDataUrl(null)
      })
    return () => {
      cancelled = true
    }
  }, [url])

  // Runs once per dismissSignal bump, including the initial mount (App
  // starts it at 0, same "fires harmlessly on mount" shape as
  // CaptureField's resetSignal effect). Only acts while an overlay is
  // actually showing, so the mount-time fire and any bump that happens
  // while already dismissed are no-ops.
  const onDismissRef = useRef(onDismiss)
  onDismissRef.current = onDismiss
  useEffect(() => {
    if (!url) return
    onDismissRef.current?.()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dismissSignal])

  if (!url) return null

  const displayUrl = url.replace(/^https?:\/\//, '')

  return (
    <div
      className="fade-in fixed inset-0 z-50 flex items-center justify-center p-6"
      style={{ background: 'rgba(10,9,7,0.86)', backdropFilter: 'blur(2px)' }}
      onClick={onDismiss}
      role="button"
      tabIndex={-1}
      aria-label="Dismiss share overlay"
    >
      <div
        className="flex w-full max-w-md flex-col items-center gap-6 text-center"
        style={{
          background: 'var(--paper-raised)',
          border: '1px solid var(--paper-line)',
          borderRadius: '14px',
          padding: '2.25rem 2rem',
          boxShadow: '0 24px 64px rgba(0,0,0,0.55)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <span
          style={{
            fontFamily: 'var(--font-sans)',
            fontSize: '0.7rem',
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            color: 'var(--amber)',
          }}
        >
          Scan to follow live
        </span>

        <div
          style={{
            background: QR_LIGHT,
            borderRadius: '10px',
            padding: '0.85rem',
            lineHeight: 0,
          }}
        >
          {qrDataUrl ? (
            <img
              src={qrDataUrl}
              alt={`QR code linking to ${url}`}
              width={240}
              height={240}
              style={{ display: 'block', width: '240px', height: '240px' }}
            />
          ) : (
            <div style={{ width: 240, height: 240 }} />
          )}
        </div>

        <p
          style={{
            fontFamily: 'var(--font-serif)',
            fontSize: 'clamp(1.4rem, 5.5vw, 2.25rem)',
            color: 'var(--ink)',
            lineHeight: 1.3,
            wordBreak: 'break-all',
            margin: 0,
          }}
        >
          {displayUrl}
        </p>

        <button
          type="button"
          onClick={onDismiss}
          style={{
            fontFamily: 'var(--font-sans)',
            fontSize: '0.78rem',
            color: 'var(--ink-dim)',
            background: 'transparent',
            border: '1px solid var(--paper-line)',
            borderRadius: '6px',
            padding: '0.45rem 0.85rem',
          }}
        >
          Dismiss
        </button>
      </div>
    </div>
  )
}
