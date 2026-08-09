import { Component, useEffect, useMemo, useState } from 'react'
import { useQuery } from 'convex/react'
import { anyApi } from 'convex/server'
import { parseFinalMarkdown } from './finalMarkdown.js'

// AudienceView.jsx — SPEC.md §14.B audience page. A read-only mirror of one
// Draft session, addressed by slug in location.hash, e.g.
// ".../watch.html#amber-fox-42". This page never talks to the Draft
// WebSocket server directly — only to Convex, via `anyApi` function refs
// (no codegen: the Convex-generated helper module does not exist on this
// machine, see convex/sessions.ts). Mobile-first: this is read on phones held up to a
// stage screen, so single column, generous type, no fixed widths, no
// external/CDN resources (same rule as the main app, SPEC.md §13.E).

const KIND_LABELS = {
  contradiction: 'Contradiction',
  vague_claim: 'Vague claim',
  undefined_term: 'Undefined term',
  lost_thread: 'Lost thread',
  implausible_claim: 'Implausible claim',
}

function useSlug() {
  const [slug, setSlug] = useState(() => window.location.hash.replace(/^#/, '').trim())
  useEffect(() => {
    function onHashChange() {
      setSlug(window.location.hash.replace(/^#/, '').trim())
    }
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])
  return slug
}

function Shell({ children }) {
  return (
    <div className="mx-auto flex min-h-screen w-full max-w-2xl flex-col px-5 pb-16 pt-10 sm:px-8">{children}</div>
  )
}

function Wordmark() {
  return (
    <span
      style={{
        fontFamily: 'var(--font-sans)',
        fontSize: '0.68rem',
        letterSpacing: '0.14em',
        textTransform: 'uppercase',
        color: 'var(--amber)',
      }}
    >
      Draft
    </span>
  )
}

function EyebrowLabel({ children }) {
  return (
    <span
      style={{
        fontFamily: 'var(--font-sans)',
        fontSize: '0.66rem',
        letterSpacing: '0.1em',
        textTransform: 'uppercase',
        color: 'var(--ink-faint)',
      }}
    >
      {children}
    </span>
  )
}

function CenteredNotice({ title, detail }) {
  return (
    <Shell>
      <div className="flex flex-1 flex-col items-center justify-center gap-3 py-24 text-center">
        <Wordmark />
        <h1
          style={{
            fontFamily: 'var(--font-serif)',
            fontSize: 'clamp(1.4rem, 6vw, 1.9rem)',
            fontWeight: 400,
            color: 'var(--ink-dim)',
            lineHeight: 1.3,
            margin: 0,
          }}
        >
          {title}
        </h1>
        {detail && (
          <p
            style={{
              fontFamily: 'var(--font-sans)',
              fontSize: '0.85rem',
              lineHeight: 1.5,
              color: 'var(--ink-faint)',
              maxWidth: '26rem',
              margin: 0,
            }}
          >
            {detail}
          </p>
        )}
      </div>
    </Shell>
  )
}

// Small "recording" style indicator. Pure Tailwind (animate-ping is part of
// its default theme) — no bespoke keyframes needed.
function LiveDot() {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="relative flex h-2 w-2">
        <span
          className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60"
          style={{ background: 'var(--amber)' }}
        />
        <span className="relative inline-flex h-2 w-2 rounded-full" style={{ background: 'var(--amber-bright)' }} />
      </span>
      <span
        style={{
          fontFamily: 'var(--font-sans)',
          fontSize: '0.66rem',
          letterSpacing: '0.1em',
          textTransform: 'uppercase',
          color: 'var(--amber)',
        }}
      >
        Live
      </span>
    </span>
  )
}

// One objection rendered as an amber margin note. Active (still-"spoken")
// objections are emphasized; answered/dismissed ones fade back, same
// intent as the main app's block-glow clearing on either transition
// (SPEC.md §13.B) but expressed as a note list instead of a ring glow,
// since this is a single-column read-only page.
function ObjectionNote({ objection }) {
  const active = objection.status === 'spoken'
  const label = KIND_LABELS[objection.kind] || objection.kind
  return (
    <div
      style={{
        borderLeft: `3px solid ${active ? 'var(--amber)' : 'var(--paper-line)'}`,
        background: active ? 'rgba(217,164,65,0.08)' : 'transparent',
        padding: '0.6rem 0.9rem',
        borderRadius: '0 6px 6px 0',
        opacity: active ? 1 : 0.55,
      }}
    >
      <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-0.5">
        <span
          style={{
            fontFamily: 'var(--font-sans)',
            fontSize: '0.62rem',
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            color: active ? 'var(--amber)' : 'var(--ink-faint)',
          }}
        >
          {label}
        </span>
        {!active && (
          <span style={{ fontFamily: 'var(--font-sans)', fontSize: '0.62rem', color: 'var(--ink-faint)' }}>
            · {objection.status}
          </span>
        )}
      </div>
      <p style={{ fontFamily: 'var(--font-sans)', fontSize: '0.88rem', lineHeight: 1.5, color: 'var(--ink)', margin: 0 }}>
        {objection.message}
      </p>
    </div>
  )
}

function LiveSession({ row }) {
  const blocks = Array.isArray(row.blocks) ? row.blocks : []
  // Newest note first, so an audience member glancing at their phone sees
  // the freshest objection without scrolling.
  const objections = Array.isArray(row.objections) ? [...row.objections].reverse() : []

  return (
    <Shell>
      <header className="mb-8 flex items-center justify-between">
        <Wordmark />
        <LiveDot />
      </header>

      {blocks.length === 0 ? (
        <p className="fade-in" style={{ fontFamily: 'var(--font-serif)', fontSize: '1.1rem', color: 'var(--ink-dim)' }}>
          Waiting for the first lines…
        </p>
      ) : (
        <>
          <h1
            className="fade-in mb-8"
            style={{
              fontFamily: 'var(--font-serif)',
              fontSize: 'clamp(1.6rem, 7vw, 2.2rem)',
              fontWeight: 400,
              color: 'var(--ink)',
              lineHeight: 1.25,
              margin: '0 0 2rem',
            }}
          >
            {row.title || 'Untitled'}
          </h1>
          <div className="flex flex-col gap-5">
            {blocks.map((b) => (
              <p
                key={b.id}
                style={{
                  fontFamily: 'var(--font-serif)',
                  fontSize: '1.08rem',
                  lineHeight: 1.75,
                  color: 'var(--ink)',
                  margin: 0,
                }}
              >
                {b.text}
              </p>
            ))}
          </div>
        </>
      )}

      {objections.length > 0 && (
        <section className="mt-12">
          <div className="mb-2.5">
            <EyebrowLabel>Editor&rsquo;s notes</EyebrowLabel>
          </div>
          <div className="flex flex-col gap-2.5">
            {objections.map((o) => (
              <ObjectionNote key={o.id} objection={o} />
            ))}
          </div>
        </section>
      )}
    </Shell>
  )
}

function FinishedSession({ row }) {
  const { title, paragraphs } = useMemo(() => parseFinalMarkdown(row.finalMarkdown || ''), [row.finalMarkdown])
  const hasFinal = Boolean(row.finalMarkdown && row.finalMarkdown.trim())

  return (
    <Shell>
      <header className="mb-8 flex items-center justify-between">
        <Wordmark />
        <EyebrowLabel>Finished</EyebrowLabel>
      </header>
      {hasFinal ? (
        <>
          <h1
            className="fade-in mb-8"
            style={{
              fontFamily: 'var(--font-serif)',
              fontSize: 'clamp(1.6rem, 7vw, 2.2rem)',
              fontWeight: 400,
              color: 'var(--ink)',
              lineHeight: 1.25,
              margin: '0 0 2rem',
            }}
          >
            {title || row.title || 'Untitled'}
          </h1>
          <div className="flex flex-col gap-5">
            {paragraphs.map((p, i) => (
              <p
                key={i}
                style={{
                  fontFamily: 'var(--font-serif)',
                  fontSize: '1.08rem',
                  lineHeight: 1.75,
                  color: 'var(--ink)',
                  margin: 0,
                }}
              >
                {p}
              </p>
            ))}
          </div>
        </>
      ) : (
        <p className="fade-in" style={{ fontFamily: 'var(--font-serif)', fontSize: '1.1rem', color: 'var(--ink-dim)' }}>
          This session has ended.
        </p>
      )}
    </Shell>
  )
}

// Query-consuming subtree, only ever mounted while a ConvexProvider is
// actually present (see AudienceView below) — keeps the useQuery call
// unconditional within its own component, which is all React's rules of
// hooks require.
function ConnectedAudienceView() {
  const slug = useSlug()
  const row = useQuery(anyApi.sessions.getBySlug, slug ? { slug } : 'skip')

  if (!slug) {
    return (
      <CenteredNotice
        title="No session link"
        detail="Open this page from a Draft share link — it carries the session in the URL."
      />
    )
  }

  // undefined = still loading, null = no such row (yet, or ever). Both read
  // as "waiting" to a viewer; SPEC.md §14.B groups them explicitly
  // ("no slug/row -> waiting for a live session").
  if (!row) {
    return (
      <CenteredNotice
        title="Waiting for a live session…"
        detail={`"${slug}" hasn't started yet, or has ended and rotated out. This page updates automatically — no need to refresh.`}
      />
    )
  }

  if (row.status === 'finished') return <FinishedSession row={row} />
  return <LiveSession row={row} />
}

// Convex's useQuery throws into the nearest error boundary on a query
// failure (e.g. the backend's functions haven't been deployed yet via
// `npx convex dev`, or the URL is misconfigured). This page has no other
// safety net, and a silent blank screen would be the worst possible outcome
// for a page an audience is actively looking at — so catch it and degrade
// to a notice instead, in the same spirit as SPEC.md §13.D's "never crash".
class ViewBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }
  static getDerivedStateFromError(error) {
    return { error }
  }
  componentDidCatch(error) {
    console.error('[AudienceView] render error', error)
  }
  render() {
    if (this.state.error) {
      return (
        <CenteredNotice
          title="Trouble reaching the live session"
          detail="The Convex backend may not be deployed yet, or the URL is misconfigured."
        />
      )
    }
    return this.props.children
  }
}

export default function AudienceView({ convexConfigured }) {
  if (!convexConfigured) {
    return (
      <CenteredNotice
        title="Not configured"
        detail="This viewer needs a Convex deployment URL at build time (VITE_CONVEX_URL). Ask the host to set it up."
      />
    )
  }
  return (
    <ViewBoundary>
      <ConnectedAudienceView />
    </ViewBoundary>
  )
}
