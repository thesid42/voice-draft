import { createRoot } from 'react-dom/client'
import { ConvexProvider, ConvexReactClient } from 'convex/react'
import AudienceView from './AudienceView.jsx'
import './index.css'

// watchMain.jsx — SPEC.md §14.B audience-page entry (web/watch.html).
// Separate Vite entry from main.jsx so the primary app bundle never pays
// for the Convex client. No VITE_CONVEX_URL at build time is an expected,
// valid configuration (the repo secret is unset until the user's first
// `npx convex dev`) — constructing ConvexReactClient with an empty/invalid
// URL throws, so skip it entirely and let AudienceView render its
// "not configured" state instead.
const CONVEX_URL =
  import.meta.env.VITE_CONVEX_URL || 'https://veracious-dotterel-468.convex.cloud'
const convexClient = CONVEX_URL ? new ConvexReactClient(CONVEX_URL) : null

function Root() {
  if (!convexClient) return <AudienceView convexConfigured={false} />
  return (
    <ConvexProvider client={convexClient}>
      <AudienceView convexConfigured={true} />
    </ConvexProvider>
  )
}

createRoot(document.getElementById('root')).render(<Root />)
