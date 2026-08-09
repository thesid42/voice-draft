// finalMarkdown.js — minimal "# title" + blank-line-paragraph markdown
// reader, shared by both Vite entries: App.jsx (main app's FinalView, for
// the WS `final_doc` message) and AudienceView.jsx (watch entry, for a
// Convex row's `finalMarkdown` field). No markdown library, per SPEC.md
// §13.E ("render the markdown minimally ... no markdown library").
export function parseFinalMarkdown(md) {
  const lines = (md || '').split('\n')
  let title = ''
  let sawTitle = false
  const rest = []
  for (const line of lines) {
    if (!sawTitle && line.trim().startsWith('# ')) {
      title = line.trim().slice(2).trim()
      sawTitle = true
      continue
    }
    rest.push(line)
  }
  const paragraphs = rest
    .join('\n')
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean)
  return { title, paragraphs }
}
