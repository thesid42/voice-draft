import { useEffect, useState } from 'react'
import { parseFinalMarkdown } from '../finalMarkdown.js'

// DraftsPanel.jsx — right-hand drawer listing every stored draft (read back
// from the Convex mirror via the server's /drafts endpoints; SPEC.md §14.B).
// Open via the "Drafts" button or the voice command "Draft, history".
// Read-only viewer: the live session stays untouched. No Convex client in
// this bundle — the server proxies the reads.

function fmtWhen(ms) {
  if (!ms) return ''
  try {
    return new Date(ms).toLocaleString([], {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    })
  } catch {
    return ''
  }
}

function Notice({ title, children }) {
  return (
    <div className="px-1 py-6">
      <p style={{ fontFamily: 'var(--font-sans)', fontSize: '0.85rem', color: 'var(--ink-dim)', margin: '0 0 0.5rem' }}>
        {title}
      </p>
      {children && (
        <p style={{ fontFamily: 'var(--font-sans)', fontSize: '0.75rem', lineHeight: 1.5, color: 'var(--ink-faint)', margin: 0 }}>
          {children}
        </p>
      )}
    </div>
  )
}

function StatusTag({ status, isCurrent }) {
  const label = isCurrent ? 'live now' : status === 'finished' ? 'finished' : 'live'
  const amber = isCurrent || status !== 'finished'
  return (
    <span
      style={{
        fontFamily: 'var(--font-sans)',
        fontSize: '0.6rem',
        letterSpacing: '0.08em',
        textTransform: 'uppercase',
        color: amber ? 'var(--amber)' : 'var(--ink-faint)',
      }}
    >
      {label}
    </span>
  )
}

function DetailView({ detail, onBack }) {
  const finished = detail.status === 'finished' && detail.finalMarkdown
  const parsed = finished ? parseFinalMarkdown(detail.finalMarkdown) : null
  const paragraphs = finished ? parsed.paragraphs : (detail.blocks || []).map((b) => b.text)
  const title = (finished && parsed.title) || detail.title || 'Untitled'

  return (
    <div>
      <button
        type="button"
        onClick={onBack}
        style={{
          fontFamily: 'var(--font-sans)',
          fontSize: '0.72rem',
          color: 'var(--ink-dim)',
          background: 'transparent',
          border: 'none',
          padding: '0 0 0.75rem',
          cursor: 'pointer',
        }}
      >
        ← all drafts
      </button>
      <div className="mb-1 flex items-center justify-between gap-2">
        <StatusTag status={detail.status} />
        <span style={{ fontFamily: 'var(--font-sans)', fontSize: '0.65rem', color: 'var(--ink-faint)' }}>
          {fmtWhen(detail.updatedAt)}
        </span>
      </div>
      <h2
        style={{
          fontFamily: 'var(--font-serif)',
          fontSize: '1.25rem',
          fontWeight: 400,
          color: 'var(--ink)',
          lineHeight: 1.3,
          margin: '0 0 1rem',
        }}
      >
        {title}
      </h2>
      {paragraphs.length === 0 ? (
        <Notice title="This draft has no paragraphs." />
      ) : (
        <div className="flex flex-col gap-3">
          {paragraphs.map((p, i) => (
            <p
              key={i}
              style={{ fontFamily: 'var(--font-serif)', fontSize: '0.92rem', lineHeight: 1.65, color: 'var(--ink)', margin: 0 }}
            >
              {p}
            </p>
          ))}
        </div>
      )}
      {(detail.objections || []).length > 0 && (
        <div className="mt-5">
          <p
            style={{
              fontFamily: 'var(--font-sans)',
              fontSize: '0.62rem',
              letterSpacing: '0.1em',
              textTransform: 'uppercase',
              color: 'var(--ink-faint)',
              margin: '0 0 0.4rem',
            }}
          >
            Editor&rsquo;s notes
          </p>
          {(detail.objections || []).map((o) => (
            <p
              key={o.id}
              style={{ fontFamily: 'var(--font-sans)', fontSize: '0.72rem', lineHeight: 1.5, color: 'var(--ink-dim)', margin: '0 0 0.4rem' }}
            >
              {o.message}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

export default function DraftsPanel({ open, onClose }) {
  const [phase, setPhase] = useState('loading') // loading | unconfigured | error | list
  const [drafts, setDrafts] = useState([])
  const [currentSlug, setCurrentSlug] = useState(null)
  const [detail, setDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setPhase('loading')
    setDetail(null)
    fetch('/drafts')
      .then((r) => r.json().then((data) => ({ ok: r.ok, data })))
      .then(({ ok, data }) => {
        if (cancelled) return
        if (!data.configured) setPhase('unconfigured')
        else if (!ok || data.error) setPhase('error')
        else {
          setDrafts(data.drafts || [])
          setCurrentSlug(data.current_slug || null)
          setPhase('list')
        }
      })
      .catch(() => {
        if (!cancelled) setPhase('error')
      })
    return () => {
      cancelled = true
    }
  }, [open])

  async function openDetail(slug) {
    setDetailLoading(true)
    try {
      const r = await fetch(`/drafts/${encodeURIComponent(slug)}`)
      if (r.ok) setDetail(await r.json())
    } catch {
      /* stay on list */
    } finally {
      setDetailLoading(false)
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-40" onClick={onClose} style={{ background: 'rgba(10,9,7,0.45)' }}>
      <aside
        className="thin-scroll fixed inset-y-0 right-0 flex w-[340px] flex-col overflow-y-auto"
        style={{
          background: 'var(--paper-raised)',
          borderLeft: '1px solid var(--paper-line)',
          padding: '1.1rem 1.2rem 2rem',
          boxShadow: '-16px 0 48px rgba(0,0,0,0.4)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <span
            style={{
              fontFamily: 'var(--font-sans)',
              fontSize: '0.68rem',
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              color: 'var(--amber)',
            }}
          >
            Drafts
          </span>
          <button
            type="button"
            onClick={onClose}
            style={{
              fontFamily: 'var(--font-sans)',
              fontSize: '0.72rem',
              color: 'var(--ink-dim)',
              background: 'transparent',
              border: '1px solid var(--paper-line)',
              borderRadius: '6px',
              padding: '0.25rem 0.6rem',
              cursor: 'pointer',
            }}
          >
            Close
          </button>
        </div>

        {phase === 'loading' && <Notice title="Loading…" />}
        {phase === 'unconfigured' && (
          <Notice title="Draft history needs Convex.">
            Run `npx convex login` then `npx convex dev --once`, put the printed URL in .env as CONVEX_URL, and
            restart the server. Every session is stored automatically from then on.
          </Notice>
        )}
        {phase === 'error' && <Notice title="Could not reach the drafts store." >Is the server (and Convex) up?</Notice>}

        {phase === 'list' && detail && <DetailView detail={detail} onBack={() => setDetail(null)} />}

        {phase === 'list' && !detail && (
          <>
            {drafts.length === 0 && (
              <Notice title="No stored drafts yet.">Speak a first draft and it will appear here.</Notice>
            )}
            <div className="flex flex-col">
              {drafts.map((d) => (
                <button
                  key={d.slug}
                  type="button"
                  onClick={() => openDetail(d.slug)}
                  disabled={detailLoading}
                  className="text-left"
                  style={{
                    background: 'transparent',
                    border: 'none',
                    borderBottom: '1px solid var(--paper-line)',
                    padding: '0.7rem 0.1rem',
                    cursor: 'pointer',
                  }}
                >
                  <div className="mb-0.5 flex items-center justify-between gap-2">
                    <StatusTag status={d.status} isCurrent={d.slug === currentSlug} />
                    <span style={{ fontFamily: 'var(--font-sans)', fontSize: '0.62rem', color: 'var(--ink-faint)' }}>
                      {fmtWhen(d.updatedAt)}
                    </span>
                  </div>
                  <div
                    style={{
                      fontFamily: 'var(--font-serif)',
                      fontSize: '0.95rem',
                      color: 'var(--ink)',
                      lineHeight: 1.35,
                    }}
                  >
                    {d.title}
                  </div>
                  <div style={{ fontFamily: 'var(--font-sans)', fontSize: '0.65rem', color: 'var(--ink-faint)' }}>
                    {d.blocks} paragraph{d.blocks === 1 ? '' : 's'}
                    {d.hasFinal ? ' · polished' : ''}
                  </div>
                </button>
              ))}
            </div>
          </>
        )}
      </aside>
    </div>
  )
}
